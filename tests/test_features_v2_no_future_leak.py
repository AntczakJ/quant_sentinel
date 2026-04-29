"""Regression tests locking in the 2026-04-29 features_v2 ffill leak fix.

Audit `docs/strategy/2026-04-29_audit_features_v2_ffill.md` found that
warehouse parquets label bars by their START time, so a 5m anchor at 14:30
ffilled with the 1h bar labeled 14:00 read a `close` that materializes at
15:00 (+30 min look-ahead). Fix shifts source index FORWARD by one
source-interval before reindexing.

These tests construct synthetic OHLC where the future is *known to be
different* from the present, then assert that mutating the future does
NOT change the value of the projected feature at the anchor — which is
the literal definition of leak-free.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_5m_anchor_at(ts: pd.Timestamp) -> pd.DatetimeIndex:
    """A single anchor bar at `ts` for the 5m timeline."""
    return pd.DatetimeIndex([ts], tz="UTC")


def test_align_to_index_does_not_read_future_bar():
    """5m anchor at 14:30 with 1h source labeled 14:00 must NOT pull the
    14:00 bar's close (which materializes at 15:00). Should pull the bar
    that already CLOSED at 14:00, i.e. the 13:00 bar."""
    from src.analysis.features_v2 import _align_to_index

    target_ts = pd.Timestamp("2025-01-15T14:30:00", tz="UTC")
    target_idx = _make_5m_anchor_at(target_ts)

    source = pd.DataFrame({
        "datetime": pd.date_range("2025-01-15T08:00", periods=10, freq="1h", tz="UTC"),
        "close":    [100.0, 110.0, 120.0, 130.0, 140.0,
                     150.0, 160.0, 170.0, 180.0, 190.0],
    })
    # Indices in `source['datetime']` correspond to 08:00, 09:00, ..., 17:00.
    # Without the fix: 14:30 anchor reads the 14:00 bar -> close=160 (FUTURE close).
    # With the fix:    14:30 anchor reads the 13:00 bar -> close=150 (already CLOSED).
    out = _align_to_index(source, target_idx, col="close", source_interval="1h")
    val = float(out.iloc[0])
    assert val == 150.0, (
        f"5m anchor at 14:30 should read the 13:00 bar (close=150 = bar that "
        f"already CLOSED at 14:00), not 160 (the 14:00 bar that closes at 15:00). "
        f"Got {val}."
    )


def test_align_to_index_immune_to_future_mutation():
    """Mutating bars STRICTLY AFTER the anchor must not change projected value."""
    from src.analysis.features_v2 import _align_to_index

    target_ts = pd.Timestamp("2025-01-15T14:30:00", tz="UTC")
    target_idx = _make_5m_anchor_at(target_ts)

    base = pd.DataFrame({
        "datetime": pd.date_range("2025-01-15T08:00", periods=10, freq="1h", tz="UTC"),
        "close":    [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0],
    })
    val_before = float(_align_to_index(base, target_idx, "close", "1h").iloc[0])

    # Mutate bars at 14:00, 15:00, 16:00 -- ALL strictly AT or after anchor.
    mutated = base.copy()
    mutated.loc[mutated["datetime"] >= pd.Timestamp("2025-01-15T14:00", tz="UTC"), "close"] = 999.0
    val_after = float(_align_to_index(mutated, target_idx, "close", "1h").iloc[0])

    assert val_before == val_after, (
        f"Anchor value changed from {val_before} to {val_after} when mutating "
        f"future bars — there's still a leak."
    )


def test_align_to_index_picks_up_past_mutation():
    """Sanity: mutating bars STRICTLY BEFORE the anchor SHOULD change the
    projected value (otherwise our shift went too far backward)."""
    from src.analysis.features_v2 import _align_to_index

    target_ts = pd.Timestamp("2025-01-15T14:30:00", tz="UTC")
    target_idx = _make_5m_anchor_at(target_ts)

    base = pd.DataFrame({
        "datetime": pd.date_range("2025-01-15T08:00", periods=10, freq="1h", tz="UTC"),
        "close":    [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0],
    })
    val_before = float(_align_to_index(base, target_idx, "close", "1h").iloc[0])

    # Mutate the 13:00 bar (the one whose close materializes at 14:00 — the
    # bar our shifted anchor SHOULD read).
    mutated = base.copy()
    mutated.loc[mutated["datetime"] == pd.Timestamp("2025-01-15T13:00", tz="UTC"), "close"] = 0.123
    val_after = float(_align_to_index(mutated, target_idx, "close", "1h").iloc[0])

    assert val_before != val_after, (
        f"Anchor value did NOT change ({val_before}) when mutating the 13:00 bar — "
        f"the shift may have moved past it."
    )
    assert val_after == 0.123


def test_compute_features_macro_immune_to_future_usdjpy_mutation():
    """compute_features's USDJPY block must not pull future USDJPY data."""
    from src.analysis.compute import compute_features

    n = 100
    xau = pd.DataFrame({
        "open":  np.full(n, 2000.0),
        "high":  np.full(n, 2010.0),
        "low":   np.full(n, 1990.0),
        "close": np.full(n, 2000.0) + np.arange(n) * 0.1,
        "volume": np.full(n, 1000),
    })
    xau.index = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")

    usdjpy_base = pd.DataFrame({
        "close": np.full(n, 150.0) + np.arange(n) * 0.001,
    })
    usdjpy_base.index = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    usdjpy_base.index.name = "datetime"
    usdjpy_base = usdjpy_base.reset_index()

    feats_before = compute_features(xau.copy(), usdjpy_df=usdjpy_base.copy())

    # compute_features may drop early warmup rows; pick anchor by timestamp,
    # not positional index, and skip if filtered out.
    anchor_ts = xau.index[60]  # well after typical 50-bar warmup
    if anchor_ts not in feats_before.index:
        pytest.skip(f"anchor {anchor_ts} got dropped during warmup — bump n")
    usdjpy_mutated = usdjpy_base.copy()
    usdjpy_mutated.loc[usdjpy_mutated["datetime"] > anchor_ts, "close"] = 99.99

    feats_after = compute_features(xau.copy(), usdjpy_df=usdjpy_mutated)

    # The macro features at the anchor row must not change.
    macro_cols = [c for c in feats_before.columns
                  if c.startswith("usdjpy_") or c.startswith("xau_usdjpy_")]
    assert len(macro_cols) > 0, "no macro feature columns generated"

    for col in macro_cols:
        b = feats_before.loc[anchor_ts, col]
        a = feats_after.loc[anchor_ts, col]
        if pd.isna(b) and pd.isna(a):
            continue
        assert np.isclose(b, a, atol=1e-9, equal_nan=True), (
            f"Future USDJPY mutation changed {col} at anchor: {b} -> {a}"
        )


def test_add_multi_tf_features_immune_to_future_htf_mutation():
    """add_multi_tf_features projecting 1h features onto 5m must not leak
    future 1h bars into the 5m anchor."""
    from src.analysis.features_v2 import add_multi_tf_features

    # 5m timeline (one trading day)
    n_5m = 288  # 24h * 12 bars/h
    main = pd.DataFrame({
        "open":  np.full(n_5m, 2000.0),
        "high":  np.full(n_5m, 2010.0),
        "low":   np.full(n_5m, 1990.0),
        "close": np.full(n_5m, 2000.0),
        "datetime": pd.date_range("2025-01-15T00:00", periods=n_5m, freq="5min", tz="UTC"),
    }).set_index("datetime")

    # 1h timeline with a feature column that increments per bar
    n_1h = 24
    h1 = pd.DataFrame({
        "rsi":           np.linspace(20.0, 80.0, n_1h),     # monotonic ↑
        "atr":           np.full(n_1h, 1.5),
        "above_ema20":   np.ones(n_1h),
        "trend_strength": np.full(n_1h, 0.5),
        "macd":          np.full(n_1h, 0.1),
        "volatility_percentile": np.full(n_1h, 0.4),
    })
    h1.index = pd.date_range("2025-01-15T00:00", periods=n_1h, freq="1h", tz="UTC")
    h1.index.name = "datetime"
    h1 = h1.reset_index()

    out_before = add_multi_tf_features(main.copy(), {"1h": h1.copy()})

    # Mutate 1h rsi at and after a chosen anchor hour
    anchor_5m_ts = pd.Timestamp("2025-01-15T14:30", tz="UTC")
    h1_mut = h1.copy()
    h1_mut.loc[h1_mut["datetime"] >= pd.Timestamp("2025-01-15T14:00", tz="UTC"), "rsi"] = -999.0

    out_after = add_multi_tf_features(main.copy(), {"1h": h1_mut})

    # 5m anchor at 14:30 should be reading the 13:00 1h bar (closed at 14:00)
    # — NOT the 14:00 1h bar (closes at 15:00). Mutating bars 14:00+ must
    # not change the 5m anchor's h1_rsi.
    val_before = out_before.loc[anchor_5m_ts, "h1_rsi"]
    val_after = out_after.loc[anchor_5m_ts, "h1_rsi"]
    assert val_before == val_after, (
        f"5m anchor at 14:30 changed when mutating 1h bars at 14:00+: "
        f"{val_before} -> {val_after}. Future leak still present."
    )
    assert val_before > 0, f"sanity: anchor read a real value, got {val_before}"
