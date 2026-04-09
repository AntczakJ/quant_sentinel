"""
api/routers/market.py - Market data endpoints
"""

import sys
import os
import asyncio
from enum import Enum
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query


class TimeframeEnum(str, Enum):
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from src.data_sources import get_provider
from api.schemas.models import CandleResponse, TickerResponse, IndicatorResponse, Candle

router = APIRouter()

# Cache for latest data
_data_cache = {"last_price": None, "last_update": None}

# TTL cache for candles & indicators — prevents hammering the Twelve Data free plan
import time as _time
_candle_cache: dict = {}   # key: f"{symbol}_{interval}_{limit}" → {"candles": ..., "ts": float}
_indicator_cache: dict = {}  # key: f"{symbol}_{interval}" → {"data": ..., "ts": float}
_ticker_cache: dict = {}   # key: f"{symbol}" → {"data": ..., "ts": float}
_CANDLE_TTL = 120            # 120 seconds — saves API credits (one call per 2 min per symbol/interval)
_INDICATOR_TTL = 120
_TICKER_TTL = 60             # 60 seconds — matches frontend polling cadence (saves credits)
_VP_TTL = 120                # 120 seconds — volume profile reuses candle data anyway

# Dedup locks — only one external API call per resource at a time
import asyncio as _asyncio
_candle_fetch_lock = _asyncio.Lock()
_ticker_fetch_lock = _asyncio.Lock()
_vp_cache: dict = {}         # key: f"{symbol}_{interval}_{limit}" → {"data": ..., "ts": float}

def calculate_rsi(close_prices, period=14):
    """Calculate RSI (Relative Strength Index)"""
    try:
        if len(close_prices) < period:
            return None

        deltas = close_prices.diff()
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period
        rs = up / down if down != 0 else 1
        rsi_values = [100. - 100. / (1. + rs)]

        for i in range(period, len(close_prices)):
            delta = deltas.iloc[i]
            if delta > 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta

            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period
            rs = up / down if down != 0 else 1
            rsi_values.append(100. - 100. / (1. + rs))

        return rsi_values[-1] if rsi_values else None
    except Exception as e:
        logger.error(f"RSI calculation error: {e}")
        return None

def calculate_macd(close_prices, fast=12, slow=26, signal=9):
    """Calculate MACD (Moving Average Convergence Divergence)"""
    try:
        if len(close_prices) < slow:
            return None

        ema_fast = close_prices.ewm(span=fast).mean()
        ema_slow = close_prices.ewm(span=slow).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal).mean()
        macd_hist = macd - macd_signal

        return (
            float(macd.iloc[-1]),
            float(macd_signal.iloc[-1]),
            float(macd_hist.iloc[-1])
        )
    except Exception as e:
        logger.error(f"MACD calculation error: {e}")
        return None

# Stable cache for when API is rate limited (not random, consistent data)
_persistent_cache = {
    "ticker": {
        "price": 4720.00,
        "change": 0.00,
        "change_pct": 0.00,
        "high_24h": 4750.00,
        "low_24h": 4690.00,
        "is_mock": False
    },
    "candles": None,
    "last_fetch_time": None
}

def get_mock_ticker_data(symbol: str):
    """Return stable mock data when API is rate limited - NOT RANDOM"""
    data = _persistent_cache["ticker"].copy()
    data["is_mock"] = True
    return data

def _is_xau_trading_hour(dt) -> bool:
    """Return True if *dt* (UTC) falls inside XAU/USD trading hours."""
    wd = dt.weekday()  # 0=Mon … 6=Sun
    h  = dt.hour
    if wd == 5:                    return False   # Saturday — fully closed
    if wd == 6 and h < 22:        return False   # Sunday before 22:00
    if wd == 4 and h >= 22:       return False   # Friday after 22:00
    if h == 21:                    return False   # Daily settlement break 21:00-21:59
    return True


def get_mock_candles(symbol: str, interval: str, count: int):
    """Return stable mock candle data when API is rate limited."""
    import pandas as pd
    import numpy as np
    import time as _t
    from datetime import datetime, timedelta, timezone as _tz

    interval_minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}.get(interval, 15)

    # Check if we have cached candles and they're still fresh (< 5 min old)
    current_time = _t.time()
    last_fetch = _persistent_cache.get("last_fetch_time", 0)
    cache_key = f"{symbol}_{interval}_{count}"
    cached_key = _persistent_cache.get("candles_key")

    if (_persistent_cache["candles"] is not None and
        cached_key == cache_key and
        (current_time - last_fetch) < 300):
        cached_df = _persistent_cache["candles"]
        if len(cached_df) >= count:
            return cached_df.tail(count).reset_index(drop=True)

    # Seed for deterministic output within a 5-min window
    current_block = int(current_time / 300)
    np.random.seed(current_block % 10000)

    base_price = _persistent_cache["ticker"].get("price", 4720.00)
    candles_list = []

    # Realistic per-interval volatility (XAU/USD)
    body_range  = {5: 3.0, 15: 6.0, 60: 15.0, 240: 35.0}.get(interval_minutes, 6.0)
    wick_range  = body_range * 0.6
    trend_range = body_range * 0.8

    # Walk backward from now, only placing candles during trading hours
    now_utc = datetime.now(_tz.utc)
    cursor  = now_utc
    # We need `count` trading candles — walk back enough to find them
    max_steps = count * 4  # generous over-scan

    timestamps = []
    for _ in range(max_steps):
        cursor -= timedelta(minutes=interval_minutes)
        if _is_xau_trading_hour(cursor):
            timestamps.append(cursor)
        if len(timestamps) >= count:
            break

    timestamps.reverse()  # oldest first

    for ts in timestamps:
        trend = np.random.uniform(-trend_range, trend_range)
        open_price = base_price + trend
        close_price = open_price + np.random.uniform(-body_range, body_range)
        high_price = max(open_price, close_price) + abs(np.random.uniform(0, wick_range))
        low_price  = min(open_price, close_price) - abs(np.random.uniform(0, wick_range))

        candles_list.append({
            'timestamp': ts,
            'open':   round(float(open_price), 2),
            'high':   round(float(high_price), 2),
            'low':    round(float(low_price),  2),
            'close':  round(float(close_price), 2),
            'volume': int(np.random.uniform(5000, 25000)),
        })
        base_price = close_price

    df = pd.DataFrame(candles_list)
    _persistent_cache["candles"] = df.copy()
    _persistent_cache["candles_key"] = cache_key
    _persistent_cache["last_fetch_time"] = _t.time()

    return df


def _filter_trading_candles(df, symbol: str, desired_count: int):
    """
    Filter out non-trading period candles — matches TradingView behaviour.

    XAU/USD trading schedule (CET/CEST — handles DST automatically):
      Open  : Sunday  23:00 CET
      Close : Friday  22:00 CET
      Weekend (pt 22:00 → nd 23:00 CET): CLOSED

    Twelve Data still emits candles during these dead windows (with
    near-zero spread), so we filter them out by timestamp.
    """
    import pandas as pd

    if df is None or df.empty:
        return df

    # ── Parse timestamps to UTC ──────────────────────────────────────────
    if 'timestamp' not in df.columns:
        return df.tail(desired_count).reset_index(drop=True)

    ts = pd.to_datetime(df['timestamp'], errors='coerce', utc=True)
    if ts.isna().all():
        # Fallback: timestamps unparseable → return as-is
        return df.tail(desired_count).reset_index(drop=True)

    if 'XAU' in symbol.upper():
        # ── XAU/USD: convert to CET/CEST for accurate DST-aware filtering ──
        try:
            from zoneinfo import ZoneInfo
            cet = ZoneInfo('Europe/Warsaw')
        except ImportError:
            try:
                import pytz
                cet = pytz.timezone('Europe/Warsaw')
            except ImportError:
                cet = None

        if cet is not None:
            ts_cet = ts.dt.tz_convert(cet)
            weekday = ts_cet.dt.weekday
            hour = ts_cet.dt.hour
        else:
            # Fallback: approximate CET as UTC+1 (no DST)
            weekday = ts.dt.weekday
            hour = (ts.dt.hour + 1) % 24

        is_saturday      = (weekday == 5)                      # Saturday — always closed
        is_sunday_closed = (weekday == 6) & (hour < 23)        # Sunday before 23:00 CET
        is_friday_closed = (weekday == 4) & (hour >= 22)       # Friday ≥22:00 CET

        is_closed = is_saturday | is_sunday_closed | is_friday_closed
    else:
        weekday = ts.dt.weekday
        # Generic forex: skip full weekends only
        is_closed = (weekday == 5) | (weekday == 6)

    active = df[~is_closed]

    if len(active) >= min(30, desired_count // 3):
        logger.info(
            f"📊 Session filter: {len(df)} → {len(active)} candles "
            f"(removed {len(df) - len(active)} off-market) [{symbol}]"
        )
        return active.tail(desired_count).reset_index(drop=True)

    # Not enough active candles (e.g. entire dataset is weekend) → return original
    logger.warning(f"⚠️ Session filter: only {len(active)} active candles, returning unfiltered")
    return df.tail(desired_count).reset_index(drop=True)


@router.get(
    "/candles",
    response_model=CandleResponse,
    summary="Get candlestick data",
    description="Fetch OHLCV candles for specified symbol and interval"
)
async def get_candles(
    symbol: str = Query("XAU/USD", description="Trading symbol (use XAU/USD for gold)"),
    interval: TimeframeEnum = Query(TimeframeEnum.M15, description="Candle interval (5m, 15m, 1h, 4h)"),
    limit: int = Query(200, ge=1, le=500, description="Number of candles")
):
    """
    Get candlestick data for a symbol.

    Supported intervals: 5m, 15m, 1h, 4h
    Falls back to mock data if API rate limit is hit.
    Results are cached for 60 seconds to reduce Twelve Data API usage.
    Non-trading (weekend/closed) candles are filtered out like TradingView.
    """
    cache_key = f"{symbol}_{interval}_{limit}"
    cached = _candle_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _CANDLE_TTL:
        logger.debug(f"✅ Serving candles from cache ({cache_key})")
        return cached["candles"]

    # Overfetch to compensate for dead-market candles that will be filtered out.
    # Weekend = ~48h gap → for 15m that's ~192 dead candles, so 3x covers it.
    fetch_limit = min(limit * 3, 500)

    try:
        provider = get_provider()

        # ── Credit pre-check: skip thread pool entirely when credits are exhausted ──
        # This is the most impactful optimization — a blocked thread holds its pool
        # slot for 5-10s; skipping it frees the slot for DB-only endpoints instantly.
        from src.api_optimizer import get_rate_limiter as _get_rl
        _can, _wait = _get_rl().can_use_credits(1)
        if not _can:
            logger.info(f"⚡ Credits low (wait {_wait:.0f}s) — using mock candles for {symbol}")
            df = get_mock_candles(symbol, interval, limit)
            if df is not None and not df.empty:
                df = _filter_trading_candles(df, symbol, limit)
                candles = [
                    Candle(
                        timestamp=row['timestamp'] if 'timestamp' in row else datetime.now(timezone.utc),
                        open=float(row['open']), high=float(row['high']),
                        low=float(row['low']), close=float(row['close']),
                        volume=int(row['volume']) if 'volume' in row else 0,
                    ) for _, row in df.iterrows()
                ]
                result = CandleResponse(symbol=symbol, interval=interval, candles=candles, limit=len(candles))
                _candle_cache[cache_key] = {"candles": result, "ts": _time.time()}
                return result

        # Dedup lock — if N requests arrive simultaneously, only the first calls the API
        async with _candle_fetch_lock:
            # Re-check cache inside lock (another request may have filled it)
            cached2 = _candle_cache.get(cache_key)
            if cached2 and (_time.time() - cached2["ts"]) < _CANDLE_TTL:
                logger.debug(f"✅ Serving candles from cache (dedup hit: {cache_key})")
                return cached2["candles"]

            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(provider.get_candles, symbol, interval, fetch_limit),
                    timeout=8.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Provider timeout (8s) — using mock data for {symbol}")
                df = None

        # If provider returns None, use mock data
        # NOTE: do NOT touch _persistent_cache["ticker"]["is_mock"] here —
        # only the /ticker endpoint should set that flag, otherwise candle fallback
        # falsely marks the ticker as mock and confuses /market/status.
        if df is None or df.empty:
            logger.warning(f"⚠️ API rate limited or error - using mock data for {symbol}")
            df = get_mock_candles(symbol, interval, limit)

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

        # Filter out non-trading candles (weekend/closed market)
        # — TradingView does the same; it never shows dead flat bars
        df = _filter_trading_candles(df, symbol, limit)

        candles = []
        for idx, row in df.iterrows():
            candles.append(Candle(
                timestamp=row['timestamp'] if 'timestamp' in row else datetime.now(timezone.utc),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=int(row['volume']) if 'volume' in row else 0
            ))

        logger.info(f"📊 Returned {len(candles)} candles for {symbol} {interval}")

        result = CandleResponse(symbol=symbol, interval=interval, candles=candles, limit=len(candles))
        _candle_cache[cache_key] = {"candles": result, "ts": _time.time()}
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching candles: {e}")
        # Final fallback to mock data
        try:
            df = get_mock_candles(symbol, interval, limit)
            candles = []
            for idx, row in df.iterrows():
                candles.append(Candle(
                    timestamp=row['timestamp'] if 'timestamp' in row else datetime.now(timezone.utc),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=int(row['volume']) if 'volume' in row else 0
                ))
            return CandleResponse(
                symbol=symbol,
                interval=interval,
                candles=candles,
                limit=len(candles)
            )
        except Exception as mock_err:
            logger.error(f"Error loading mock candles: {mock_err}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/ticker",
    response_model=TickerResponse,
    summary="Get live ticker",
    description="Get current price and market data for a symbol"
)
async def get_ticker(symbol: str = Query("XAU/USD", description="Trading symbol (use XAU/USD for gold)")):
    """
    Get live ticker data for a symbol.
    Falls back to mock data if API rate limit is hit.
    """
    try:
        # Check ticker cache first
        ticker_cached = _ticker_cache.get(symbol)
        if ticker_cached and (_time.time() - ticker_cached["ts"]) < _TICKER_TTL:
            logger.debug(f"✅ Serving ticker from cache ({symbol})")
            data = ticker_cached["data"]
        else:
            provider = get_provider()
            async with _ticker_fetch_lock:
                # Re-check inside lock (dedup)
                ticker_cached2 = _ticker_cache.get(symbol)
                if ticker_cached2 and (_time.time() - ticker_cached2["ts"]) < _TICKER_TTL:
                    data = ticker_cached2["data"]
                else:
                    # Credit pre-check — skip thread pool when credits exhausted
                    from src.api_optimizer import get_rate_limiter as _get_rl
                    _can, _wait = _get_rl().can_use_credits(1)
                    if not _can:
                        logger.info(f"⚡ Credits low — using mock ticker for {symbol}")
                        data = get_mock_ticker_data(symbol)
                        _persistent_cache["ticker"]["is_mock"] = True
                    else:
                        try:
                            data = await asyncio.wait_for(
                                asyncio.to_thread(provider.get_current_price, symbol),
                                timeout=8.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"⚠️ Provider timeout (8s) — using mock ticker for {symbol}")
                            data = None

                        # If provider returns None (rate limited or error), use mock data
                        if data is None:
                            logger.warning(f"⚠️ API rate limited or error - using mock data for {symbol}")
                            data = get_mock_ticker_data(symbol)
                            _persistent_cache["ticker"]["is_mock"] = True
                        else:
                            _persistent_cache["ticker"]["is_mock"] = False

                    _ticker_cache[symbol] = {"data": data, "ts": _time.time()}

        _data_cache["last_price"] = data.get("price", 0)
        _data_cache["last_update"] = datetime.now(timezone.utc)

        # Update persistent cache with real values (for mock fallback).
        # Guard: only accept if the new price is within ±20% of the current cached price.
        # This prevents a single stale/wrong API response from corrupting the reference.
        if not data.get("is_mock"):
            new_price = float(data.get("price", 0))
            old_price = _persistent_cache["ticker"].get("price", 0)
            price_ok = True
            if old_price > 1000 and new_price > 0:
                deviation = abs(new_price - old_price) / old_price
                if deviation > 0.20:
                    logger.warning(
                        f"⚠️ Ticker price sanity: API=${new_price:.2f} vs cache=${old_price:.2f} "
                        f"(Δ{deviation:.0%}) — NOT updating persistent cache"
                    )
                    price_ok = False

            if price_ok and new_price > 0:
                _persistent_cache["ticker"]["price"] = new_price
            if float(data.get("change", 0)) != 0:
                _persistent_cache["ticker"]["change"] = float(data.get("change", 0))
                _persistent_cache["ticker"]["change_pct"] = float(data.get("change_pct", 0))
            if data.get("high_24h") and price_ok:
                _persistent_cache["ticker"]["high_24h"] = float(data["high_24h"])
            if data.get("low_24h") and price_ok:
                _persistent_cache["ticker"]["low_24h"] = float(data["low_24h"])

        logger.debug(f"💰 {symbol}: {data.get('price', 'N/A')}")

        return TickerResponse(
            symbol=symbol,
            price=float(data.get("price", 0)),
            change=float(data.get("change", 0)),
            change_pct=float(data.get("change_pct", 0)),
            timestamp=datetime.now(timezone.utc),
            high_24h=float(data.get("high_24h")) if data.get("high_24h") else None,
            low_24h=float(data.get("low_24h")) if data.get("low_24h") else None,
        )

    except Exception as e:
        logger.error(f"❌ Error fetching ticker: {e}")
        # Final fallback to mock data even if exception occurs
        try:
            data = get_mock_ticker_data(symbol)
            return TickerResponse(
                symbol=symbol,
                price=float(data.get("price", 0)),
                change=float(data.get("change", 0)),
                change_pct=float(data.get("change_pct", 0)),
                timestamp=datetime.now(timezone.utc),
                high_24h=float(data.get("high_24h")) if data.get("high_24h") else None,
                low_24h=float(data.get("low_24h")) if data.get("low_24h") else None,
            )
        except Exception as mock_err:
            logger.error(f"Error loading mock ticker: {mock_err}")
            raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/indicators",
    response_model=IndicatorResponse,
    summary="Get technical indicators",
    description="Calculate technical indicators (RSI, MACD, Bollinger Bands)"
)
async def get_indicators(
    symbol: str = Query("XAU/USD", description="Trading symbol (use XAU/USD for gold)"),
    interval: TimeframeEnum = Query(TimeframeEnum.M15, description="Candle interval")
):
    """
    Get technical indicators for a symbol.
    Falls back to mock data if API rate limit is hit.
    Results are cached for 60 seconds.
    """
    cache_key = f"{symbol}_{interval}"
    cached = _indicator_cache.get(cache_key)
    if cached and (_time.time() - cached["ts"]) < _INDICATOR_TTL:
        logger.debug(f"✅ Serving indicators from cache ({cache_key})")
        return cached["data"]

    try:
        provider = get_provider()

        # Credit pre-check — use mock data when credits exhausted
        from src.api_optimizer import get_rate_limiter as _get_rl
        _can, _ = _get_rl().can_use_credits(1)
        if not _can:
            logger.info(f"⚡ Credits low — using mock indicators for {symbol}")
            df = get_mock_candles(symbol, interval, 100)
        else:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(provider.get_candles, symbol, interval, 100),
                    timeout=8.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Provider timeout (8s) — using mock indicators for {symbol}")
                df = None

        # If provider returns None, use mock data
        if df is None or df.empty:
            logger.warning(f"⚠️ API rate limited - using mock indicators for {symbol}")
            df = get_mock_candles(symbol, interval, 100)

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"Could not fetch data for {symbol}")

        # Calculate indicators
        rsi = None
        macd_val = None
        macd_sig = None
        macd_hist = None
        bb_upper = None
        bb_mid = None
        bb_lower = None

        try:
            rsi = calculate_rsi(df['close'])
        except Exception as rsi_err:
            logger.debug(f"RSI calculation skipped: {rsi_err}")

        try:
            macd_result = calculate_macd(df['close'])
            if macd_result:
                macd_val, macd_sig, macd_hist = macd_result
        except Exception as macd_err:
            logger.debug(f"MACD calculation skipped: {macd_err}")

        # Bollinger Bands (20-period SMA ± 2 std)
        try:
            if len(df['close']) >= 20:
                sma20 = df['close'].rolling(window=20).mean()
                std20 = df['close'].rolling(window=20).std()
                bb_mid = float(sma20.iloc[-1])
                bb_upper = float(sma20.iloc[-1] + 2 * std20.iloc[-1])
                bb_lower = float(sma20.iloc[-1] - 2 * std20.iloc[-1])
        except Exception as bb_err:
            logger.debug(f"Bollinger Bands calculation skipped: {bb_err}")

        logger.info(f"📈 Indicators for {symbol}: RSI={rsi}")

        result = IndicatorResponse(
            symbol=symbol,
            rsi=rsi,
            macd=macd_val,
            macd_signal=macd_sig,
            macd_histogram=macd_hist,
            bb_upper=bb_upper,
            bb_middle=bb_mid,
            bb_lower=bb_lower,
            timestamp=datetime.now(timezone.utc)
        )
        _indicator_cache[cache_key] = {"data": result, "ts": _time.time()}
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error calculating indicators: {e}")
        # Return minimal response on error
        return IndicatorResponse(
            symbol=symbol,
            rsi=None,
            macd=None,
            macd_signal=None,
            macd_histogram=None,
            bb_upper=None,
            bb_middle=None,
            bb_lower=None,
            timestamp=datetime.now(timezone.utc)
        )

@router.get("/status", summary="Get market status")
async def get_market_status():
    """
    Get current market status and API connection state.
    Returns is_mock=True if API is rate limited and using cached data.
    """
    return {
        "status": "open",
        "last_price": _data_cache.get("last_price"),
        "last_update": _data_cache.get("last_update"),
        "is_mock": _persistent_cache["ticker"].get("is_mock", False),
        "api_status": "DISCONNECTED" if _persistent_cache["ticker"].get("is_mock") else "CONNECTED",
        "timestamp": datetime.now(timezone.utc)
    }


@router.get("/volume-profile", summary="Get Volume Profile data")
async def get_volume_profile(
    symbol: str = Query("XAU/USD", description="Symbol"),
    interval: TimeframeEnum = Query(TimeframeEnum.M15, description="Interval"),
    limit: int = Query(100, description="Number of candles"),
):
    """
    Zwraca Volume Profile: POC, VAH, VAL i histogram price-volume dla wizualizacji.
    Reuses the candle cache when possible to avoid extra Twelve Data API credits.
    Results are cached for 60 seconds.
    """
    vp_key = f"{symbol}_{interval}_{limit}"
    cached_vp = _vp_cache.get(vp_key)
    if cached_vp and (_time.time() - cached_vp["ts"]) < _VP_TTL:
        logger.debug(f"✅ Serving volume-profile from cache ({vp_key})")
        return cached_vp["data"]

    try:
        from src.indicators import volume_profile as calc_vp

        # Try to reuse candle cache first (0 credits)
        candle_key = f"{symbol}_{interval}_{limit}"
        candle_cached = _candle_cache.get(candle_key)
        # Also try overfetch key used by /candles endpoint
        candle_key_200 = f"{symbol}_{interval}_200"
        candle_cached_200 = _candle_cache.get(candle_key_200)

        df = None
        if candle_cached and (_time.time() - candle_cached["ts"]) < _CANDLE_TTL:
            logger.debug(f"✅ VP reusing candle cache ({candle_key})")
            # Reconstruct a minimal DataFrame from cached Candle objects
            import pandas as pd
            rows = [{"open": c.open, "high": c.high, "low": c.low, "close": c.close,
                      "volume": c.volume, "timestamp": c.timestamp}
                    for c in candle_cached["candles"].candles[-limit:]]
            df = pd.DataFrame(rows) if rows else None
        elif candle_cached_200 and (_time.time() - candle_cached_200["ts"]) < _CANDLE_TTL:
            logger.debug(f"✅ VP reusing candle cache ({candle_key_200})")
            import pandas as pd
            rows = [{"open": c.open, "high": c.high, "low": c.low, "close": c.close,
                      "volume": c.volume, "timestamp": c.timestamp}
                    for c in candle_cached_200["candles"].candles[-limit:]]
            df = pd.DataFrame(rows) if rows else None

        # Fallback: fetch from provider (costs 1 credit) — only if credits available
        if df is None or df.empty:
            from src.api_optimizer import get_rate_limiter as _get_rl
            _can, _ = _get_rl().can_use_credits(1)
            if not _can:
                logger.info(f"⚡ Credits low — returning empty VP for {symbol}")
                return {"poc": 0, "vah": 0, "val": 0, "histogram": [], "is_mock": True}
            provider = get_provider()
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(provider.get_candles, symbol, interval, limit),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ VP provider timeout — returning empty")
                return {"poc": 0, "vah": 0, "val": 0, "histogram": [], "is_mock": True}

        if df is None or df.empty:
            return {"poc": 0, "vah": 0, "val": 0, "histogram": [], "is_mock": True}

        vp = calc_vp(df)
        result = {
            "poc": vp.get("poc"),
            "vah": vp.get("vah"),
            "val": vp.get("val"),
            "histogram": vp.get("histogram", []),
            "symbol": symbol,
            "interval": interval,
            "is_mock": False,
        }
        _vp_cache[vp_key] = {"data": result, "ts": _time.time()}
        return result
    except Exception as e:
        logger.error(f"Volume profile error: {e}")
        return {"poc": 0, "vah": 0, "val": 0, "histogram": [], "error": str(e)}
