"""Unit tests for tools/build_triple_barrier_labels.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure tools/ is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.build_triple_barrier_labels import build_labels, WIN, LOSS, TIMEOUT


def _synthetic_df(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.001, n)
    close = 2000 * np.cumprod(1 + rets)
    high = close + np.abs(rng.normal(0, 1.0, n))
    low = close - np.abs(rng.normal(0, 1.0, n))
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
    })


def test_build_labels_shape_and_columns():
    df = _synthetic_df(150)
    out = build_labels(df, tp_atr=2.0, sl_atr=1.0, max_holding=20)
    assert len(out) == 150
    expected_cols = {
        "datetime", "close", "atr",
        "long_label", "long_r", "long_exit_offset",
        "short_label", "short_r", "short_exit_offset",
    }
    assert expected_cols.issubset(out.columns)


def test_build_labels_anchors_with_no_lookahead_are_sentinel():
    """Last `max_holding` rows can't be resolved → label = -1."""
    df = _synthetic_df(80)
    out = build_labels(df, tp_atr=2.0, sl_atr=1.0, max_holding=20)
    tail = out.tail(20)
    # All last 20 anchors should be sentinel-labeled (no lookahead available)
    assert (tail["long_label"] == -1).all()
    assert (tail["short_label"] == -1).all()


def test_build_labels_long_tp_hit():
    """Construct OHLC where a LONG TP is the first barrier touched."""
    n = 30
    base = 2000.0
    high = np.full(n, base)
    low = np.full(n, base)
    close = np.full(n, base)
    # Bar 5: a wick high that should cross TP for the anchor at t=0
    # ATR(14) on flat data = 0 → must seed some movement
    # Inject small TR for ATR calculation
    high[:14] = base + 1.0
    low[:14] = base - 1.0
    close[:14] = base
    # ATR after warmup ≈ 2
    # At t=14: TP_long = close[14] + 2*ATR = base + 4
    # Make bar 16 high cross that
    high[16] = base + 5.0
    # Anchor at t=14 should resolve to WIN with exit_offset=2

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
    })
    out = build_labels(df, tp_atr=2.0, sl_atr=1.0, max_holding=10)
    assert out.loc[14, "long_label"] == WIN
    assert out.loc[14, "long_r"] == 2.0  # tp_atr / sl_atr


def test_build_labels_short_sl_hit():
    """A rising market should produce SHORT SLs (mirror of TP_hit logic)."""
    n = 30
    base = 2000.0
    high = np.full(n, base)
    low = np.full(n, base)
    close = np.full(n, base)
    high[:14] = base + 1.0
    low[:14] = base - 1.0
    # Big up-move at bar 16: high crosses SHORT SL = base + sl*ATR ≈ base+2
    high[16] = base + 5.0

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
    })
    out = build_labels(df, tp_atr=2.0, sl_atr=1.0, max_holding=10)
    assert out.loc[14, "short_label"] == LOSS
    assert out.loc[14, "short_r"] == -1.0


def test_build_labels_timeout_when_neither_barrier_touched():
    n = 40
    base = 2000.0
    # Create initial volatility so ATR > 0
    high = np.full(n, base + 1.0)
    low = np.full(n, base - 1.0)
    close = np.full(n, base)
    # After warmup, freeze price flat — neither barrier should hit
    high[14:] = base + 0.1
    low[14:] = base - 0.1
    close[14:] = base

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
    })
    out = build_labels(df, tp_atr=5.0, sl_atr=5.0, max_holding=10)
    # Anchor at t=14 should timeout (flat market, wide barriers)
    assert out.loc[14, "long_label"] == TIMEOUT
    assert out.loc[14, "short_label"] == TIMEOUT


def test_build_labels_xau_5min_realistic_distribution():
    """Sanity: at TP=2*ATR / SL=1*ATR / 60-bar timeout on real XAU 5m,
    LONG TP rate should be in the 25–40% band (matches warehouse run)."""
    parquet = _REPO_ROOT / "data" / "historical" / "XAU_USD" / "5min.parquet"
    if not parquet.exists():
        import pytest
        pytest.skip("XAU 5min warehouse parquet not present")
    df = pd.read_parquet(parquet)
    # Take a 50k-row slice for speed
    out = build_labels(df.iloc[:50_000], tp_atr=2.0, sl_atr=1.0, max_holding=60)
    valid = out[out["long_label"] >= 0]
    win_rate = (valid["long_label"] == WIN).mean()
    assert 0.20 <= win_rate <= 0.45, f"long TP rate {win_rate:.3f} out of expected band"
