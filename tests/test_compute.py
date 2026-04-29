"""
tests/test_compute.py — Tests for feature computation, decomposition, ML models
"""

import pytest
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_sample_df(n=200):
    """Create sample OHLCV DataFrame for testing."""
    np.random.seed(42)
    close = 2000 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame({
        'open': close + np.random.randn(n) * 0.5,
        'high': close + abs(np.random.randn(n) * 2),
        'low': close - abs(np.random.randn(n) * 2),
        'close': close,
        'volume': np.random.randint(1000, 50000, n),
    })


class TestFeatureComputation:
    def test_compute_features_returns_dataframe(self):
        from src.analysis.compute import compute_features, FEATURE_COLS
        df = _make_sample_df()
        features = compute_features(df)
        assert isinstance(features, pd.DataFrame)
        for col in FEATURE_COLS:
            assert col in features.columns, f"Missing feature: {col}"

    def test_feature_count(self):
        from src.analysis.compute import FEATURE_COLS
        # 31 baseline + 3 macro (USDJPY) + 2 VWAP = 36 as of 2026-04-24
        assert len(FEATURE_COLS) == 36

    def test_compute_target(self):
        from src.analysis.compute import compute_features, compute_target
        df = _make_sample_df()
        features = compute_features(df)
        target = compute_target(features)
        assert len(target) == len(features)
        assert set(target.dropna().unique()).issubset({0, 1})


# TestDecomposition — dropped 2026-04-30 (P2.5).
# Decompose voter was removed from production fusion (Batch C.1)
# because np.convolve(mode='same') is a centered kernel that pulls 10
# future bars into trend at bar t — confirmed leak in audit
# docs/strategy/2026-04-29_audit_1_data_leaks.md P1.1. The
# src/ml/decompose_model.py module has been deleted; these tests are
# now stale.


class TestCandlestickPatterns:
    def test_engulfing(self):
        from src.analysis.candlestick_patterns import engulfing
        df = _make_sample_df(50)
        result = engulfing(df)
        assert result in ('bullish', 'bearish', False)

    def test_pin_bar(self):
        from src.analysis.candlestick_patterns import pin_bar
        df = _make_sample_df(50)
        result = pin_bar(df)
        assert result in ('bullish', 'bearish', False)

    def test_inside_bar(self):
        from src.analysis.candlestick_patterns import inside_bar
        df = _make_sample_df(50)
        result = inside_bar(df)
        assert result in (True, False)  # accepts both Python bool and numpy bool
