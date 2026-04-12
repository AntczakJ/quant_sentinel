"""tests/test_historical_provider.py — HistoricalProvider time-slicing + monkey-patch.

No-network tests: we build the provider with synthetic OHLCV data so the
suite doesn't depend on yfinance availability / rate limits.
"""
import pandas as pd
import pytest


def _make_df(start="2026-01-01", periods=100, freq="15min", base=1000.0):
    idx = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    prices = [base + i * 0.5 for i in range(periods)]
    return pd.DataFrame({
        "timestamp": idx,
        "open": prices,
        "high": [p + 0.3 for p in prices],
        "low": [p - 0.3 for p in prices],
        "close": prices,
        "volume": [100.0] * periods,
    })


class TestHistoricalProvider:
    def test_get_candles_before_set_now_returns_none(self):
        from src.backtest.historical_provider import HistoricalProvider
        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        assert provider.get_candles("XAU/USD", "15m", 10) is None

    def test_get_candles_returns_n_bars_at_or_before_now(self):
        from src.backtest.historical_provider import HistoricalProvider
        df = _make_df(periods=200)
        provider = HistoricalProvider({"15m": df}, symbol="XAU/USD")
        cutoff = df["timestamp"].iloc[100]
        provider.set_simulated_now(cutoff)
        result = provider.get_candles("XAU/USD", "15m", 20)
        assert result is not None
        assert len(result) == 20
        assert result["timestamp"].iloc[-1] <= cutoff
        # No leakage of future data
        assert (result["timestamp"] <= cutoff).all()

    def test_get_candles_unknown_interval_returns_none(self):
        from src.backtest.historical_provider import HistoricalProvider
        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        provider.set_simulated_now(pd.Timestamp("2026-01-05", tz="UTC"))
        assert provider.get_candles("XAU/USD", "1d", 10) is None

    def test_get_candles_handles_simulated_now_before_data(self):
        from src.backtest.historical_provider import HistoricalProvider
        provider = HistoricalProvider({"15m": _make_df(start="2026-06-01")}, symbol="XAU/USD")
        provider.set_simulated_now(pd.Timestamp("2026-01-01", tz="UTC"))
        assert provider.get_candles("XAU/USD", "15m", 10) is None

    def test_get_current_price_uses_latest_bar(self):
        from src.backtest.historical_provider import HistoricalProvider
        df = _make_df(periods=50, base=2000.0)
        provider = HistoricalProvider({"15m": df}, symbol="XAU/USD")
        cutoff = df["timestamp"].iloc[20]
        provider.set_simulated_now(cutoff)
        price = provider.get_current_price("XAU/USD")
        assert price == df.loc[20, "close"]

    def test_set_simulated_now_clears_smc_cache(self):
        """Critical: cache clear must happen so SMC re-analyzes each tick."""
        from src.backtest.historical_provider import HistoricalProvider
        from src.core import cache as cache_mod
        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        # Seed the cache with a fake entry
        cache_mod._cache["smc_analysis_1h"] = {"val": "stale", "ts": 0}
        provider.set_simulated_now(pd.Timestamp("2026-01-05", tz="UTC"))
        assert "smc_analysis_1h" not in cache_mod._cache

    def test_set_simulated_now_accepts_naive_timestamp(self):
        from src.backtest.historical_provider import HistoricalProvider
        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        # Naive (no tzinfo) should be coerced to UTC
        provider.set_simulated_now(pd.Timestamp("2026-01-05"))
        assert provider.simulated_now is not None
        assert provider.simulated_now.tzinfo is not None

    def test_min_max_bar_time(self):
        from src.backtest.historical_provider import HistoricalProvider
        df = _make_df(periods=50)
        provider = HistoricalProvider({"15m": df}, symbol="XAU/USD")
        assert provider.min_bar_time("15m") == df["timestamp"].iloc[0]
        assert provider.max_bar_time("15m") == df["timestamp"].iloc[-1]
        assert provider.min_bar_time("unknown") is None

    def test_get_exchange_rate_identity(self):
        from src.backtest.historical_provider import HistoricalProvider
        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        assert provider.get_exchange_rate("USD", "USD") == 1.0
        # Non-identity rates are stubbed constant — backtest doesn't model FX
        rate = provider.get_exchange_rate("USD", "PLN")
        assert isinstance(rate, float)


class TestInstallHistoricalProvider:
    def test_monkeypatches_get_provider(self):
        from src.backtest.historical_provider import HistoricalProvider, install_historical_provider
        from src.data import data_sources

        provider = HistoricalProvider({"15m": _make_df()}, symbol="XAU/USD")
        original = data_sources.get_provider
        try:
            install_historical_provider(provider)
            # Any call to get_provider returns our historical instance
            assert data_sources.get_provider() is provider
            assert data_sources.get_provider("twelve_data") is provider
            # Cache is reset
            assert "__backtest__" in data_sources._provider_cache
        finally:
            # Restore so other tests aren't polluted
            data_sources.get_provider = original
            data_sources._provider_cache.clear()
