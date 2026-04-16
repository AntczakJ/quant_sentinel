"""
src/backtest/historical_provider.py — Offline DataProvider for backtest.

Serves historical OHLCV bars "as of" a simulated timestamp. Preloads all
timeframes (5m, 15m, 1h, 4h) for the full backtest window once, then
returns the most recent N bars relative to the current `simulated_now`.

**Isolation**: this module does NOT touch the live `_provider_cache` in
data_sources. It exposes `install_historical_provider()` which monkey-
patches `get_provider` — call it BEFORE any scanner/smc_engine imports.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from src.core.logger import logger
from src.data.data_sources import DataProvider


# Maps canonical TF keys to yfinance-compatible intervals
_YF_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "60min": "1h",
    "4h": "1h",   # yfinance doesn't have 4h — we'll aggregate
    "1d": "1d",
}


class HistoricalProvider(DataProvider):
    """Replays historical OHLCV to the scanner as if live.

    Usage:
        provider = HistoricalProvider.from_yfinance(
            symbol="XAU/USD", period="2y", yf_symbol="GC=F")
        provider.set_simulated_now(pd.Timestamp("2024-06-15 14:30:00"))
        df = provider.get_candles("XAU/USD", "15m", 200)  # last 200 bars as of now
    """

    def __init__(self, cache: dict[str, pd.DataFrame], symbol: str = "XAU/USD"):
        """cache: {interval: DataFrame with 'timestamp' column sorted ascending}"""
        self._cache = cache
        self._symbol = symbol
        self._simulated_now: Optional[pd.Timestamp] = None

    # ── Lifecycle: set time ────────────────────────────────────────────

    def set_simulated_now(self, ts: pd.Timestamp) -> None:
        """Advance the simulated wall-clock. Future data is hidden from get_candles.

        Also clears the SMC analysis cache — it uses wall-clock TTL (60s) which
        makes repeated backtest ticks within the same real second return stale
        data. Without this invalidation every simulated timestamp returns the
        first-cached analysis.
        """
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        self._simulated_now = ts.tz_convert("UTC")

        # Invalidate function-result cache so smc_engine.get_smc_analysis and
        # friends re-compute against the new simulated time.
        try:
            from src.core import cache as _cache_mod
            _cache_mod._cache.clear()
        except Exception:
            pass

    @property
    def simulated_now(self) -> Optional[pd.Timestamp]:
        return self._simulated_now

    def min_bar_time(self, interval: str) -> Optional[pd.Timestamp]:
        """Earliest bar we have — used to decide a valid backtest start."""
        df = self._cache.get(interval)
        if df is None or df.empty:
            return None
        return pd.Timestamp(df["timestamp"].iloc[0])

    def max_bar_time(self, interval: str) -> Optional[pd.Timestamp]:
        df = self._cache.get(interval)
        if df is None or df.empty:
            return None
        return pd.Timestamp(df["timestamp"].iloc[-1])

    # ── DataProvider interface ────────────────────────────────────────

    def get_candles(self, symbol: str, interval: str, count: int) -> Optional[pd.DataFrame]:
        if self._simulated_now is None:
            logger.warning("HistoricalProvider.get_candles called before set_simulated_now()")
            return None
        df = self._cache.get(interval)
        if df is None:
            logger.warning(f"HistoricalProvider: no cache for interval {interval}")
            return None
        # Slice to bars at-or-before simulated_now
        mask = df["timestamp"] <= self._simulated_now
        visible = df.loc[mask]
        if visible.empty:
            return None
        # Return last `count` bars — reset_index so scanner sees 0..n-1
        return visible.tail(count).reset_index(drop=True).copy()

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Current price = close of latest bar visible at simulated_now."""
        # Use 5m for most accurate "live" price, fallback to 15m/1h
        for tf in ("5m", "15m", "1h", "4h", "1d"):
            df = self.get_candles(symbol, tf, 1)
            if df is not None and not df.empty:
                return float(df["close"].iloc[-1])
        return None

    def get_exchange_rate(self, base: str, target: str) -> Optional[float]:
        """FX rate fixed at 1.0 in backtest — not modeled."""
        return 1.0 if base == target else 4.0  # rough fallback

    def prefetch_all_timeframes(self, symbol: str = "XAU/USD", timeframes=None):
        """No-op in backtest (everything already preloaded)."""
        return

    # ── Loader ─────────────────────────────────────────────────────────

    @classmethod
    def from_yfinance(cls, symbol: str = "XAU/USD", period: str = "2y",
                      yf_symbol: str = "GC=F",
                      intervals: tuple = ("5m", "15m", "30m", "1h", "4h"),
                      use_cache: bool = True) -> "HistoricalProvider":
        """Fetch all TFs from yfinance. 5m has 60-day max; we truncate.

        Caches to data/_backtest_cache/{yf_symbol}_{tf}_{period}.parquet with
        a 6-hour TTL. Set use_cache=False to force refresh.
        """
        import contextlib
        import io
        import time as _time
        from pathlib import Path
        import yfinance as yf

        cache_dir = Path("data/_backtest_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        CACHE_TTL_SEC = 6 * 3600

        cache: dict[str, pd.DataFrame] = {}
        for tf in intervals:
            yf_int = _YF_INTERVAL_MAP.get(tf, tf)
            # yfinance intraday limits: 5m/15m/30m max 60d, 1h up to 730d
            yf_period = "60d" if tf in ("5m", "15m", "30m") else period

            # ── Try disk cache first ──
            safe_name = yf_symbol.replace("=", "_").replace("/", "_")
            cache_file = cache_dir / f"{safe_name}_{tf}_{yf_period}.parquet"
            if use_cache and cache_file.exists():
                age = _time.time() - cache_file.stat().st_mtime
                if age < CACHE_TTL_SEC:
                    try:
                        df = pd.read_parquet(cache_file)
                        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                        df = df.sort_values("timestamp").reset_index(drop=True)
                        cache[tf] = df
                        logger.info(f"HistoricalProvider: {tf} from disk cache "
                                    f"({len(df)} bars, age {age/60:.0f}min)")
                        continue
                    except Exception as e:
                        logger.debug(f"Cache read failed for {tf}: {e}")

            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    raw = yf.Ticker(yf_symbol).history(period=yf_period, interval=yf_int)
            except Exception as e:
                logger.warning(f"HistoricalProvider: failed fetching {tf}/{yf_period}: {e}")
                continue
            if raw is None or raw.empty:
                logger.warning(f"HistoricalProvider: empty {tf} data")
                continue
            df = raw.reset_index()
            df.columns = [c.lower() for c in df.columns]
            # Rename index column to 'timestamp' regardless of original name
            ts_col = next((c for c in df.columns if c in ("datetime", "date", "index")), "timestamp")
            if ts_col != "timestamp":
                df = df.rename(columns={ts_col: "timestamp"})
            # Ensure UTC
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df[["timestamp"] + [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]]

            # For 4h, aggregate from 1h
            if tf == "4h" and yf_int == "1h":
                df = df.set_index("timestamp").resample("4h").agg({
                    "open": "first", "high": "max", "low": "min",
                    "close": "last", "volume": "sum",
                }).dropna().reset_index()

            df = df.sort_values("timestamp").reset_index(drop=True)
            cache[tf] = df
            logger.info(f"HistoricalProvider: fetched {tf} — {len(df)} bars "
                        f"({df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]})")
            # Persist to disk cache for next run
            if use_cache:
                try:
                    df.to_parquet(cache_file, index=False)
                except Exception as e:
                    logger.debug(f"Cache write failed for {tf}: {e}")

        if not cache:
            raise RuntimeError(f"HistoricalProvider: no data fetched for {yf_symbol}")
        return cls(cache, symbol=symbol)


def install_historical_provider(provider: HistoricalProvider) -> None:
    """Monkey-patch `src.data.data_sources.get_provider` to always return
    the given HistoricalProvider. Call BEFORE importing scanner.

    Also installs a no-op for `prefetch_all_timeframes` to avoid extra calls.
    """
    import src.data.data_sources as ds

    # Seed cache so any cached returns point to historical
    ds._provider_cache.clear()
    ds._provider_cache["__backtest__"] = provider

    def _get_backtest_provider(name=None):
        return provider

    ds.get_provider = _get_backtest_provider  # type: ignore[assignment]
    os.environ["DATA_PROVIDER"] = "__backtest__"
    logger.info("[backtest] HistoricalProvider installed — get_provider() now returns historical data")
