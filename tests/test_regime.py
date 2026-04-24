"""tests/test_regime.py — Regime classifier (src/analysis/regime.py)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analysis.regime import classify_regime, regime_diagnostics  # noqa: E402


def _build_df(closes, highs=None, lows=None):
    """Helper: build OHLC df from close series."""
    n = len(closes)
    if highs is None:
        highs = [c + 0.5 for c in closes]
    if lows is None:
        lows = [c - 0.5 for c in closes]
    return pd.DataFrame({
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
    })


class TestClassifyRegime:
    def test_insufficient_data_defaults_to_ranging(self):
        # Fewer than 50 bars — not enough history for BBW 20 + rolling 50
        df = _build_df([2000 + i for i in range(10)])
        assert classify_regime(df) == "ranging"

    def test_empty_or_none_defaults_to_ranging(self):
        assert classify_regime(None) == "ranging"
        assert classify_regime(pd.DataFrame()) == "ranging"

    def test_monotonic_trend_classified_as_trending(self):
        # Monotonic uptrend over 100 bars → should be trending (low vol
        # because constant slope, no ATR expansion)
        closes = [2000 + i * 0.5 for i in range(100)]
        df = _build_df(closes)
        result = classify_regime(df)
        assert result in ("trending_high_vol", "trending_low_vol"), \
            f"monotonic trend should be trending, got {result}"

    def test_sine_wave_not_trending_high_vol(self):
        # Sine wave oscillating without net direction — should NOT be
        # trending_high_vol. (Exact regime depends on ADX fallback used
        # when adx column not pre-computed; can be ranging or
        # trending_low_vol depending on where the last window lands in
        # the oscillation. High-vol trend is the clear failure mode.)
        rng = np.random.default_rng(42)
        n = 100
        closes = [2000 + 3 * np.sin(i / 5) + rng.standard_normal() * 0.3 for i in range(n)]
        df = _build_df(closes)
        assert classify_regime(df) != "trending_high_vol"

    def test_vol_expansion_after_quiet_period(self):
        # First 60 bars flat, last 40 bars expanding → should be
        # trending_high_vol or squeeze (depending on compression)
        rng = np.random.default_rng(7)
        quiet = [2000 + rng.standard_normal() * 0.1 for _ in range(60)]
        expand = [2000 + i * 0.8 + rng.standard_normal() * 0.5 for i in range(40)]
        df = _build_df(quiet + expand)
        result = classify_regime(df)
        # Post-quiet expansion can read as trending_high_vol or squeeze
        # (if BBW just started expanding from very low baseline)
        assert result in ("trending_high_vol", "squeeze", "trending_low_vol")

    def test_never_raises_on_bad_data(self):
        # Missing close column → should fall back to ranging, not raise
        df = pd.DataFrame({"open": [1, 2, 3] * 20, "high": [1, 2, 3] * 20})
        assert classify_regime(df) == "ranging"


class TestRegimeDiagnostics:
    def test_returns_regime_key(self):
        closes = [2000 + i * 0.5 for i in range(100)]
        diag = regime_diagnostics(_build_df(closes))
        assert "regime" in diag
        assert diag["regime"] in ("squeeze", "trending_high_vol", "trending_low_vol", "ranging")

    def test_insufficient_data_returns_reason(self):
        diag = regime_diagnostics(_build_df([2000] * 10))
        assert diag["regime"] == "ranging"
        assert "reason" in diag and diag["reason"] == "insufficient_data"

    def test_thresholds_exposed(self):
        closes = [2000 + i * 0.5 for i in range(100)]
        diag = regime_diagnostics(_build_df(closes))
        assert "thresholds" in diag
        t = diag["thresholds"]
        assert t["squeeze_below"] == 0.6
        assert t["trending_above_adx"] == 0.35
        assert t["high_vol_above_atr_ratio"] == 1.3

    def test_includes_indicator_values(self):
        closes = [2000 + i * 0.5 for i in range(100)]
        diag = regime_diagnostics(_build_df(closes))
        # BBW compression should be populated
        assert "bbw_compression_ratio" in diag
        assert diag["bbw_compression_ratio"] is not None
