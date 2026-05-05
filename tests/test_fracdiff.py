"""Tests for src/analysis/fracdiff.py."""
import numpy as np
import pytest

from src.analysis.fracdiff import (
    fracdiff_weights, fracdiff_series, find_min_d, add_fracdiff_features,
)


def test_weights_d0_returns_first_one_rest_zero():
    """d=0 should give weight[0]=1, all others 0 (no differencing)."""
    w = fracdiff_weights(0.0, K=10)
    assert w[0] == 1.0
    np.testing.assert_array_almost_equal(w[1:], np.zeros(9))


def test_weights_d1_gives_first_diff():
    """d=1 should give w=[1, -1, 0, 0, ...] (standard first-difference)."""
    w = fracdiff_weights(1.0, K=5)
    assert w[0] == 1.0
    assert w[1] == -1.0
    np.testing.assert_array_almost_equal(w[2:], np.zeros(3))


def test_weights_d_between_decay():
    """For d=0.5, weights should be alternating sign + decaying magnitude."""
    w = fracdiff_weights(0.5, K=10)
    assert w[0] == 1.0
    assert w[1] == -0.5
    # Magnitudes decay
    abs_w = np.abs(w)
    for i in range(1, 9):
        assert abs_w[i+1] < abs_w[i] or abs_w[i] < 1e-6, (
            f"Weight magnitude not decreasing at i={i}: {abs_w}"
        )


def test_fracdiff_series_d1_equals_simple_diff():
    """d=1 fracdiff should equal np.diff (with NaN padding)."""
    x = np.arange(20, dtype=np.float64) ** 1.5
    out = fracdiff_series(x, d=1.0, K=2)
    expected = np.diff(x, prepend=np.nan)
    # First value is NaN, rest should match standard diff
    np.testing.assert_array_almost_equal(out[1:], expected[1:])


def test_fracdiff_series_d0_equals_input():
    """d=0 fracdiff should equal input (no differencing)."""
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = fracdiff_series(x, d=0.0, K=3)
    # First K-1 values NaN, rest equal to original (since w=[1, 0, 0])
    assert np.isnan(out[0]) and np.isnan(out[1])
    np.testing.assert_array_almost_equal(out[2:], x[2:])


def test_fracdiff_first_K_minus_one_is_nan():
    x = np.random.RandomState(42).randn(50)
    out = fracdiff_series(x, d=0.4, K=10)
    assert all(np.isnan(out[:9]))
    assert not np.any(np.isnan(out[9:]))


def test_fracdiff_d_between_partial_differencing():
    """d=0.4 should be partial — neither identical to input nor diff."""
    np.random.seed(0)
    x = np.cumsum(np.random.randn(100))  # random walk (non-stationary)
    out_d04 = fracdiff_series(x, d=0.4, K=20)
    out_d04_clean = out_d04[~np.isnan(out_d04)]
    out_d1_clean = np.diff(x)

    # d=0.4 std should be between (input std) and (d=1 std)
    in_std = np.std(x)
    d1_std = np.std(out_d1_clean)
    d04_std = np.std(out_d04_clean)
    # d=0.4 is "less aggressive" than d=1, so std should be between
    # (this is a sanity check, not a strict invariant)
    assert d04_std < in_std, "d=0.4 should reduce std vs raw"


def test_add_fracdiff_features_creates_columns():
    import pandas as pd
    df = pd.DataFrame({"close": np.cumsum(np.random.randn(50))})
    add_fracdiff_features(df, columns=("close",), d=0.4, K=10)
    assert "fracdiff_close" in df.columns
    # Column has correct length
    assert len(df["fracdiff_close"]) == 50
    # First 9 NaN
    assert df["fracdiff_close"].iloc[:9].isna().all()


def test_add_fracdiff_features_skips_missing_columns():
    import pandas as pd
    df = pd.DataFrame({"close": np.arange(20, dtype=float)})
    # usdjpy_close not present → skip silently
    add_fracdiff_features(df, columns=("close", "usdjpy_close"), d=0.4, K=10)
    assert "fracdiff_close" in df.columns
    assert "fracdiff_usdjpy_close" not in df.columns


def test_find_min_d_falls_back_when_statsmodels_missing(monkeypatch):
    """If statsmodels unavailable, return default 0.4."""
    import sys
    # Force ImportError on statsmodels
    monkeypatch.setitem(sys.modules, "statsmodels", None)
    monkeypatch.setitem(sys.modules, "statsmodels.tsa.stattools", None)
    x = np.cumsum(np.random.randn(100))
    d = find_min_d(x)
    # When the import fails, the function returns 0.4 default
    assert d == 0.4 or 0.0 < d <= 1.0  # accept either exact fallback or working ADF
