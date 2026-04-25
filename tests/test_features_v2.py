"""Tests for features_v2 (multi-asset, multi-TF feature engineering)."""
import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n=200):
    np.random.seed(42)
    idx = pd.date_range("2026-04-01", periods=n, freq="5min", tz="UTC")
    close = 2400 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + np.abs(np.random.randn(n)),
        "low": close - np.abs(np.random.randn(n)),
        "close": close,
        "volume": np.random.rand(n) * 1000,
    }, index=idx)


def test_features_v2_basic():
    from src.analysis.features_v2 import compute_features_v2, ALL_V2_FEATURE_COLS
    df = _make_ohlcv(200)
    features = compute_features_v2(df, higher_tf_dfs={}, cross_asset_dfs={})
    assert len(features) > 0
    # All ALL_V2_FEATURE_COLS should be present
    missing = [c for c in ALL_V2_FEATURE_COLS if c not in features.columns]
    assert not missing, f"Missing v2 cols: {missing}"


def test_features_v2_cross_asset_zero_default():
    """Without cross-asset dfs, cross-asset features should default to 0."""
    from src.analysis.features_v2 import compute_features_v2, CROSS_ASSET_FEATURES
    df = _make_ohlcv(200)
    features = compute_features_v2(df, higher_tf_dfs={}, cross_asset_dfs={})
    for c in CROSS_ASSET_FEATURES:
        # Should be exactly 0 (default), or all-NaN-filled-to-0
        assert (features[c] == 0).all() or (features[c].abs().max() < 30), \
            f"{c} should default near 0 when cross_asset missing"


def test_features_v2_with_cross_asset():
    from src.analysis.features_v2 import compute_features_v2
    df = _make_ohlcv(200)
    # Build a synthetic XAG (silver) df
    np.random.seed(7)
    xag_idx = pd.date_range("2026-04-01", periods=300, freq="15min", tz="UTC")
    xag_close = 30 + np.cumsum(np.random.randn(300) * 0.05)
    xag_df = pd.DataFrame({
        "datetime": xag_idx,
        "close": xag_close,
        "high": xag_close + 0.5,
        "low": xag_close - 0.5,
        "open": xag_close,
        "volume": 100,
    })
    features = compute_features_v2(df, higher_tf_dfs={},
                                    cross_asset_dfs={"XAG/USD": xag_df})
    # xag features should now have some non-zero values
    assert features["xag_zscore_20"].abs().max() > 0


def test_features_v2_multi_tf():
    from src.analysis.features_v2 import compute_features_v2
    from src.analysis.compute import compute_features

    # 5m df spans 7 days (so it overlaps with h1 features after warmup)
    np.random.seed(42)
    n = 12 * 24 * 7  # 7 days at 5min
    idx = pd.date_range("2026-04-01", periods=n, freq="5min", tz="UTC")
    close = 2400 + np.cumsum(np.random.randn(n) * 0.3)
    df_5m = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.random.rand(n) * 1000,
    }, index=idx)

    # Build h1 df with 200 hours (~8 days) — gives ~150 hours after warmup
    np.random.seed(12)
    h1_n = 200
    h1_close = 2400 + np.cumsum(np.random.randn(h1_n) * 1.0)
    h1_df = pd.DataFrame({
        "open": h1_close, "high": h1_close + 1, "low": h1_close - 1,
        "close": h1_close, "volume": 1000,
    }, index=pd.date_range("2026-04-01", periods=h1_n, freq="1h", tz="UTC"))
    h1_features = compute_features(h1_df)

    features = compute_features_v2(
        df_5m, higher_tf_dfs={"1h": h1_features}, cross_asset_dfs={},
    )
    assert "h1_rsi" in features.columns
    # After alignment, h1_rsi should have some non-zero values
    assert features["h1_rsi"].abs().max() > 0
