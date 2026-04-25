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


class TestDecomposition:
    def test_decompose_shape_preserved(self):
        from src.ml.decompose_model import _decompose_features
        data = np.random.randn(100, 10)
        trend, seasonal, residual = _decompose_features(data)
        assert trend.shape == data.shape
        assert seasonal.shape == data.shape
        assert residual.shape == data.shape

    def test_decompose_sums_approximately(self):
        from src.ml.decompose_model import _decompose_features
        data = np.random.randn(100, 5)
        trend, seasonal, residual = _decompose_features(data)
        # trend + seasonal should approximate original
        reconstructed = trend + seasonal
        # Allow some error from edge effects
        mid = data[20:-20]
        rec_mid = reconstructed[20:-20]
        error = np.abs(mid - rec_mid).mean()
        assert error < 0.01, f"Reconstruction error too high: {error}"


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
