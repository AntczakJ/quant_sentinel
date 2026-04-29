"""Unit tests for tools/build_triple_barrier_labels.py — CLI wrapper.

The CLI delegates math to `src.learning.labels.triple_barrier_labels` +
`r_multiple_labels`. These tests verify the CLI's output schema and
that the library's canonical encoding (-1 / 0 / 1) flows through correctly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Ensure tools/ is importable
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.build_triple_barrier_labels import build_labels_df

# Canonical encoding (matches src/learning/labels/triple_barrier.py)
TP, TIMEOUT, SL = 1, 0, -1


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


def test_build_labels_schema():
    df = _synthetic_df(150)
    out = build_labels_df(df, tp_atr=2.0, sl_atr=1.0, max_holding=20)
    assert len(out) == 150
    expected_cols = {
        "datetime", "close", "atr",
        "label_long", "bars_to_exit_long", "exit_price_long", "r_long",
        "label_short", "bars_to_exit_short", "exit_price_short", "r_short",
    }
    assert expected_cols.issubset(out.columns), \
        f"Missing: {expected_cols - set(out.columns)}"


def test_build_labels_canonical_encoding_values():
    """Encoding must be -1 / 0 / 1 (canonical), never 2."""
    df = _synthetic_df(300)
    out = build_labels_df(df, tp_atr=2.0, sl_atr=1.0, max_holding=20)
    for col in ("label_long", "label_short"):
        unique = set(out[col].unique())
        assert unique.issubset({-1, 0, 1}), (
            f"{col} contains non-canonical values: {unique}. "
            f"Canonical encoding is -1 (SL) / 0 (timeout) / 1 (TP)."
        )


def test_build_labels_long_tp_hit():
    """Construct OHLC where a LONG TP is the first barrier touched."""
    n = 30
    base = 2000.0
    high = np.full(n, base)
    low = np.full(n, base)
    close = np.full(n, base)
    # ATR seed
    high[:14] = base + 1.0
    low[:14] = base - 1.0
    close[:14] = base
    # Wick at bar 16 crosses LONG TP
    high[16] = base + 5.0

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close, "high": high, "low": low, "close": close,
    })
    out = build_labels_df(df, tp_atr=2.0, sl_atr=1.0, max_holding=10)
    assert out.loc[14, "label_long"] == TP


def test_build_labels_short_sl_hit():
    """A rising market should produce SHORT SLs."""
    n = 30
    base = 2000.0
    high = np.full(n, base)
    low = np.full(n, base)
    close = np.full(n, base)
    high[:14] = base + 1.0
    low[:14] = base - 1.0
    high[16] = base + 5.0  # crosses SHORT SL

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close, "high": high, "low": low, "close": close,
    })
    out = build_labels_df(df, tp_atr=2.0, sl_atr=1.0, max_holding=10)
    assert out.loc[14, "label_short"] == SL


def test_build_labels_timeout_when_neither_barrier_touched():
    n = 40
    base = 2000.0
    high = np.full(n, base + 1.0)
    low = np.full(n, base - 1.0)
    close = np.full(n, base)
    # Freeze flat after warmup — neither barrier hit
    high[14:] = base + 0.1
    low[14:] = base - 0.1
    close[14:] = base

    df = pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC"),
        "open": close, "high": high, "low": low, "close": close,
    })
    out = build_labels_df(df, tp_atr=5.0, sl_atr=5.0, max_holding=10)
    assert out.loc[14, "label_long"] == TIMEOUT
    assert out.loc[14, "label_short"] == TIMEOUT


def test_build_labels_xau_5min_realistic_distribution():
    """Sanity: at TP=2*ATR / SL=1*ATR on real XAU 5m, LONG TP rate ~ 25-45%."""
    parquet = _REPO_ROOT / "data" / "historical" / "XAU_USD" / "5min.parquet"
    if not parquet.exists():
        pytest.skip("XAU 5min warehouse parquet not present")
    df = pd.read_parquet(parquet)
    out = build_labels_df(df.iloc[:50_000], tp_atr=2.0, sl_atr=1.0, max_holding=60)
    win_rate = (out["label_long"] == TP).mean()
    assert 0.20 <= win_rate <= 0.45, f"long TP rate {win_rate:.3f} out of expected band"
