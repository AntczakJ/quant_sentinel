"""
data_sources.py — Professional API data provider with rate limiting
Implements: Leaky Bucket rate limiting, batch requests, aggressive caching, exponential backoff
             + WebSocket streaming for real-time price (Grow plan: 1 WS connection)
             + Multi-timeframe prefetch to maximize cache hits
Spec: 55 credits/min limit (Twelve Data Grow plan)
"""

import os
import pandas as pd
import requests
import time
import threading
import json
from typing import Optional, List, Dict
from src.config import TD_API_KEY, ALPHA_VANTAGE_KEY
from src.logger import logger
from src.api_optimizer import (
    get_rate_limiter,
    get_batch_grouper,
    CreditWeights
)
from src.persistent_cache import get_persistent_cache


# Session for connection pooling
session = requests.Session()
session.headers.update({'User-Agent': 'QuantSentinel/2.3'})


# ============================================================================
# MODULE-LEVEL LIVE PRICE STORE (filled by WebSocket, read by get_current_price)
# ============================================================================
_live_prices: Dict[str, dict] = {}  # symbol → {price, timestamp}
_live_price_lock = threading.Lock()


class DataProvider:
    def get_candles(self, symbol: str, interval: str, count: int) -> Optional[pd.DataFrame]:
        raise NotImplementedError
    def get_current_price(self, symbol: str) -> Optional[float]:
        raise NotImplementedError
    def get_exchange_rate(self, base: str, target: str) -> Optional[float]:
        raise NotImplementedError


class TwelveDataProvider(DataProvider):
    """
    Twelve Data API provider with professional rate limiting

    Implements:
    - Leaky Bucket rate limiting (55 credits/min)
    - Batch requests for multiple symbols
    - Persistent disk caching
    - Exponential backoff on 429 errors
    """

    def __init__(self, api_key):
        self.api_key = api_key
        self.base = "https://api.twelvedata.com"
        self.rate_limiter = get_rate_limiter()
        self.batch_grouper = get_batch_grouper()
        self.persistent_cache = get_persistent_cache()

        logger.info("🚀 TwelveDataProvider initialized with rate limiting (55 credits/min)")

    def _check_429_and_wait(self, attempt: int = 0, max_attempts: int = 2):
        """Handle 429 Too Many Requests error"""
        if attempt >= max_attempts:
            logger.error("❌ Max retry attempts exhausted after 429 errors")
            return False

        # Short backoff: 2s, 4s (max)
        wait_time = 2 ** (attempt + 1)
        wait_time = min(wait_time, 4)  # cap at 4s to avoid request timeout
        logger.warning(f"⚠️ Rate limited (429). Waiting {wait_time}s before retry (attempt {attempt + 1}/{max_attempts})")
        time.sleep(wait_time)
        return True

    def _req(self, endpoint: str, params: dict, num_symbols: int = 1) -> dict:
        """
        Make API request with rate limiting

        Args:
            endpoint: API endpoint (price, time_series, etc)
            params: Query parameters
            num_symbols: Number of symbols in request (for batch calculations)

        Returns:
            API response JSON
        """
        # Validate endpoint cost
        is_affordable, cost, error = self.rate_limiter.validate_endpoint_cost(endpoint, num_symbols)
        if not is_affordable:
            logger.error(f"❌ Cannot execute request: {error}")
            return {}

        # Wait for credits if needed (with short timeout to avoid blocking API responses)
        if not self.rate_limiter.wait_for_credits(cost, max_wait_seconds=5):
            logger.warning(f"⚠️ Credits unavailable for {cost} credits — returning empty (fallback to mock)")
            return {}

        # Use credits
        if not self.rate_limiter.use_credits(
            cost,
            endpoint=endpoint,
            symbol=params.get('symbol', 'batch')
        ):
            return {}

        # Make request with session (connection pooling)
        params['apikey'] = self.api_key
        max_retries = 2

        for attempt in range(max_retries):
            try:
                response = session.get(
                    f"{self.base}/{endpoint}",
                    params=params,
                    timeout=8
                )

                # Handle 429 rate limit errors
                if response.status_code == 429:
                    if not self._check_429_and_wait(attempt, max_retries):
                        return {}
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout:
                logger.error(f"⏱️ Timeout on {endpoint} - attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    time.sleep(1)
            except requests.exceptions.RequestException as e:
                logger.error(f"🌐 Request error on {endpoint}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)

        return {}

    def get_candles(self, symbol: str, interval: str, count: int):
        """
        Get candlestick data with intelligent caching

        - Daily data: 24h cache (minimal API calls)
        - Intraday: Memory cache only (frequent updates)
        """
        logger.debug(f"📊 Fetching candles: {symbol} {interval}")

        # Check persistent cache for daily data
        if interval == '1d':
            cached = self.persistent_cache.get_daily_ohlc(symbol)
            if cached is not None:
                logger.info(f"✅ Cached daily OHLC: {symbol}")
                return cached

        # Try intraday memory cache
        cached = self.persistent_cache.get_intraday_data(symbol, interval)
        if cached is not None and len(cached) >= count:
            logger.info(f"✅ Cached intraday: {symbol} {interval} ({len(cached)} candles)")
            return cached

        # Convert interval format
        td_interval = interval if 'min' in interval else interval.replace('m', 'min')

        # Make API request
        data = self._req('time_series', {
            'symbol': symbol,
            'interval': td_interval,
            'outputsize': min(count, 5000)  # API limit
        })

        if 'values' not in data:
            logger.warning(f"⚠️ No candle data for {symbol}")
            return None

        # Parse response
        df = pd.DataFrame(data['values'])
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].apply(pd.to_numeric)
        df = df.iloc[::-1].reset_index(drop=True)

        # Twelve Data returns 'datetime' field — rename to 'timestamp' for consistency
        # Forex timestamps from Twelve Data are in UTC
        if 'datetime' in df.columns:
            df['timestamp'] = pd.to_datetime(df['datetime'], utc=True)
        elif 'timestamp' not in df.columns:
            df['timestamp'] = pd.Timestamp.now(tz='UTC')

        # XAU/USD (forex) has no volume — add placeholder
        if 'volume' not in df.columns:
            df['volume'] = 0

        # Cache result
        if interval == '1d':
            self.persistent_cache.set_daily_ohlc(symbol, df)
        else:
            self.persistent_cache.set_intraday_data(symbol, interval, df)

        logger.info(f"✅ Fetched {len(df)} candles: {symbol} {interval}")
        return df

    def get_current_price(self, symbol: str):
        """
        Get current price with layered fallback:
        1. WebSocket live price (0 credits, <1s latency)
        2. Short-lived cache (0 credits, <30s old)
        3. REST API call (1 credit)
        """
        # --- Layer 1: WebSocket live price (free, real-time) ---
        with _live_price_lock:
            if symbol in _live_prices:
                data = _live_prices[symbol]
                age = time.time() - data.get('timestamp', 0)
                if age < 30:  # WS price is fresh (< 30s)
                    logger.debug(f"💰 WS live price: {symbol} = ${data['price']} (age {age:.0f}s)")
                    return {
                        'price': data['price'],
                        'change': 0.0,
                        'change_pct': 0.0,
                        'high_24h': None,
                        'low_24h': None,
                        'source': 'websocket'
                    }

        # --- Layer 2: Short-lived REST cache (avoid duplicate calls within 15s) ---
        cache_key = f"price_{symbol}"
        cached = self.persistent_cache.get_intraday_data(symbol, '__price__')
        if cached is not None and not cached.empty:
            cached_price = cached['close'].iloc[-1]
            logger.debug(f"💰 Cached price: {symbol} = ${cached_price}")
            return {
                'price': float(cached_price),
                'change': 0.0,
                'change_pct': 0.0,
                'high_24h': None,
                'low_24h': None,
                'source': 'cache'
            }

        # --- Layer 3: REST API (1 credit) ---
        logger.debug(f"💰 Fetching price (REST): {symbol}")

        data = self._req('price', {'symbol': symbol})

        if 'price' not in data:
            logger.warning(f"⚠️ No price for {symbol}")
            return None

        result = {
            'price': float(data['price']),
            'change': 0.0,
            'change_pct': 0.0,
            'high_24h': None,
            'low_24h': None,
            'source': 'rest'
        }

        # Cache for 15s to avoid duplicate REST calls
        price_df = pd.DataFrame([{'close': result['price']}])
        self.persistent_cache.set_intraday_data(symbol, '__price__', price_df)

        logger.info(f"✅ Price: {symbol} = ${result['price']}")
        return result

    # ===== WebSocket Streaming (Grow plan: 1 WS connection, 0 credits) =====

    def start_price_stream(self, symbols: List[str] = None):
        """
        Start WebSocket price stream for real-time prices (0 API credits).
        Grow plan supports 1 WebSocket connection.
        Prices are stored in module-level _live_prices dict.
        """
        if symbols is None:
            symbols = ['XAU/USD']

        def _ws_thread():
            try:
                import websocket
            except ImportError:
                logger.warning("⚠️ websocket-client not installed, WS streaming disabled")
                return

            ws_url = "wss://ws.twelvedata.com/v1/quotes/price"
            subscribe_msg = {
                "action": "subscribe",
                "params": {
                    "symbols": ",".join(symbols)
                }
            }

            def on_message(ws, message):
                try:
                    data = json.loads(message)
                    if 'price' in data and 'symbol' in data:
                        with _live_price_lock:
                            _live_prices[data['symbol']] = {
                                'price': float(data['price']),
                                'timestamp': time.time()
                            }
                except Exception as e:
                    logger.debug(f"WS parse error: {e}")

            def on_open(ws):
                logger.info(f"🔌 WebSocket connected, subscribing to: {symbols}")
                ws.send(json.dumps(subscribe_msg))

            def on_error(ws, error):
                logger.warning(f"⚠️ WebSocket error: {error}")

            def on_close(ws, code, msg):
                logger.info(f"🔌 WebSocket closed ({code}). Reconnecting in 5s...")
                time.sleep(5)
                _ws_thread()  # Reconnect

            try:
                ws = websocket.WebSocketApp(
                    f"{ws_url}?apikey={self.api_key}",
                    on_message=on_message,
                    on_open=on_open,
                    on_error=on_error,
                    on_close=on_close
                )
                ws.run_forever(ping_interval=30)
            except Exception as e:
                logger.error(f"❌ WebSocket fatal error: {e}")
                time.sleep(10)

        thread = threading.Thread(target=_ws_thread, daemon=True, name="TwelveData-WS")
        thread.start()
        logger.info(f"🚀 WebSocket price stream started for {symbols}")

    # ===== Multi-Timeframe Prefetch =====

    def prefetch_all_timeframes(self, symbol: str = 'XAU/USD',
                                 timeframes: List[str] = None,
                                 count: int = 200):
        """
        Prefetch candles for all standard timeframes in one cycle.
        Populates cache so subsequent get_candles() calls are free.
        Called once at the top of each scanner cycle.
        """
        if timeframes is None:
            timeframes = ['5m', '15m', '1h', '4h']

        fetched = 0
        for tf in timeframes:
            cached = self.persistent_cache.get_intraday_data(symbol, tf)
            if cached is not None and len(cached) >= count * 0.8:
                logger.debug(f"✅ Prefetch skip (cached): {symbol} {tf}")
                continue
            df = self.get_candles(symbol, tf, count)
            if df is not None and not df.empty:
                fetched += 1
                logger.debug(f"✅ Prefetched: {symbol} {tf} ({len(df)} candles)")
            else:
                logger.warning(f"⚠️ Prefetch failed: {symbol} {tf}")

        if fetched > 0:
            logger.info(f"📦 Prefetched {fetched} timeframes for {symbol}")
        return fetched

    def get_current_prices_batch(self, symbols: List[str]):
        """
        Get prices for multiple symbols in batch (more efficient)

        Reduces HTTP overhead and helps with rate limiting
        """
        if not symbols:
            return {}

        logger.info(f"📦 Batch fetch prices for: {', '.join(symbols)}")

        # Group symbols into batches (max 10 per request)
        batches = self.batch_grouper.group_symbols(symbols)
        results = {}

        for batch in batches:
            symbol_str = ','.join(batch)
            data = self._req('price', {'symbol': symbol_str}, num_symbols=len(batch))

            if 'data' in data:
                for item in data['data']:
                    symbol = item['symbol']
                    results[symbol] = {
                        'price': float(item['price']),
                        'change': 0.0,
                        'change_pct': 0.0,
                    }
            elif 'price' in data:
                # Single symbol response
                symbol = batch[0]
                results[symbol] = {
                    'price': float(data['price']),
                    'change': 0.0,
                    'change_pct': 0.0,
                }

        logger.info(f"✅ Batch fetch complete: {len(results)} symbols")
        return results

    def get_exchange_rate(self, base: str, target: str):
        """Get exchange rate (1 credit)"""
        logger.debug(f"💱 Fetching exchange rate: {base}/{target}")

        data = self._req('price', {'symbol': f'{base}/{target}'})

        if 'price' in data:
            rate = float(data['price'])
            logger.info(f"✅ Exchange rate: {base}/{target} = {rate}")
            return rate

        logger.warning(f"⚠️ No exchange rate for {base}/{target}")
        return None

    def get_rate_limiter_stats(self):
        """Get current rate limiter statistics"""
        return self.rate_limiter.get_stats()


class AlphaVantageProvider(DataProvider):
    """AlphaVantage provider (fallback)"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base = "https://www.alphavantage.co/query"

    def _req(self, function, params):
        params['apikey'] = self.api_key
        params['function'] = function
        try:
            r = requests.get(self.base, params=params, timeout=10)
            return r.json()
        except Exception as e:
            logger.error(f"AlphaVantage error: {e}")
            return {}

    def get_candles(self, symbol, interval, count):
        interval_map = {'5m':'5min','15m':'15min','1h':'60min','4h':'60min'}
        av_interval = interval_map.get(interval, '60min')
        data = self._req('TIME_SERIES_INTRADAY', {'symbol': symbol, 'interval': av_interval, 'outputsize': 'full'})
        key = f'Time Series ({av_interval})'
        if key not in data:
            return None
        df = pd.DataFrame.from_dict(data[key], orient='index')
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().tail(count)
        df[['1. open','2. high','3. low','4. close']] = df[['1. open','2. high','3. low','4. close']].apply(pd.to_numeric)
        df.columns = ['open','high','low','close','volume']
        return df.reset_index(drop=True)

    def get_current_price(self, symbol):
        data = self._req('GLOBAL_QUOTE', {'symbol': symbol})
        if 'Global Quote' in data and '05. price' in data['Global Quote']:
            return {
                'price': float(data['Global Quote']['05. price']),
                'change': 0.0,
                'change_pct': 0.0,
                'high_24h': None,
                'low_24h': None
            }
        return None

    def get_exchange_rate(self, base, target):
        data = self._req('CURRENCY_EXCHANGE_RATE', {'from_currency': base, 'to_currency': target})
        if 'Realtime Currency Exchange Rate' in data:
            return float(data['Realtime Currency Exchange Rate']['5. Exchange Rate'])
        return None


_provider_cache: dict = {}  # name → DataProvider singleton


def get_provider(name=None):
    """Get data provider with optimization enabled (cached singleton)"""
    name = name or os.getenv('DATA_PROVIDER', 'twelve_data')
    if name in _provider_cache:
        return _provider_cache[name]

    if name == 'twelve_data':
        provider = TwelveDataProvider(TD_API_KEY)
    elif name == 'alpha_vantage':
        provider = AlphaVantageProvider(ALPHA_VANTAGE_KEY)
    else:
        provider = TwelveDataProvider(TD_API_KEY)

    _provider_cache[name] = provider
    return provider


