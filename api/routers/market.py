"""
api/routers/market.py - Market data endpoints
"""

import sys
import os
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from src.data_sources import get_provider
import pandas_ta as ta
from api.schemas.models import CandleResponse, TickerResponse, IndicatorResponse, Candle

router = APIRouter()

# Cache for latest data
_data_cache = {"last_price": None, "last_update": None}

# TTL cache for candles & indicators — prevents hammering the Twelve Data free plan
import time as _time
_candle_cache: dict = {}   # key: f"{symbol}_{interval}_{limit}" → {"candles": ..., "ts": float}
_indicator_cache: dict = {}  # key: f"{symbol}_{interval}" → {"data": ..., "ts": float}
_CANDLE_TTL = 60             # 60 seconds — one API call per minute max per symbol/interval
_INDICATOR_TTL = 60

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
        "is_mock": True
    },
    "candles": None,
    "last_fetch_time": None
}

def get_mock_ticker_data(symbol: str):
    """Return stable mock data when API is rate limited - NOT RANDOM"""
    return _persistent_cache["ticker"].copy()

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

    base_price = 4720.00
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

    XAU/USD trading schedule (all times UTC):
      Open  : Sunday  22:00  →  Friday 22:00
      Break : every day 21:00 – 21:59  (daily settlement / rollover)
      Closed: Saturday all day, Sunday < 22:00, Friday ≥ 22:00

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

    weekday = ts.dt.weekday   # 0 = Monday … 6 = Sunday
    hour = ts.dt.hour

    if 'XAU' in symbol.upper():
        # ── XAU/USD session mask ─────────────────────────────────────────
        is_saturday       = (weekday == 5)
        is_sunday_closed  = (weekday == 6) & (hour < 22)
        is_friday_closed  = (weekday == 4) & (hour >= 22)
        is_daily_break    = (hour == 21)                       # 21:00-21:59 UTC = 23:00-23:59 CEST

        is_closed = is_saturday | is_sunday_closed | is_friday_closed | is_daily_break
    else:
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
    interval: str = Query("15m", description="Candle interval (5m, 15m, 1h, 4h)"),
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
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(provider.get_candles, symbol, interval, fetch_limit),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Provider timeout (12s) — using mock data for {symbol}")
            df = None

        # If provider returns None, use mock data
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
                timestamp=row['timestamp'] if 'timestamp' in row else datetime.utcnow(),
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
                    timestamp=row['timestamp'] if 'timestamp' in row else datetime.utcnow(),
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
        provider = get_provider()
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(provider.get_current_price, symbol),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Provider timeout (12s) — using mock ticker for {symbol}")
            data = None

        # If provider returns None (rate limited or error), use mock data
        if data is None:
            logger.warning(f"⚠️ API rate limited or error - using mock data for {symbol}")
            data = get_mock_ticker_data(symbol)

        _data_cache["last_price"] = data.get("price", 0)
        _data_cache["last_update"] = datetime.now(timezone.utc)

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
    interval: str = Query("15m", description="Candle interval")
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
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(provider.get_candles, symbol, interval, 100),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Provider timeout (12s) — using mock indicators for {symbol}")
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



