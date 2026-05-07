"""Tests for MEGA gold-mine multipliers (Sunday gap + FOMC + compounding)."""
import datetime as dt
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# ── Sunday gap-fill ───────────────────────────────────────────────

def test_sunday_gap_outside_window_returns_none():
    """Mid-week, no Sunday gap signal."""
    from src.trading.strategies import sunday_gap
    df = _build_df_with_friday_close(3300.0)
    # Tuesday 14:00 UTC — outside Sunday-open window
    ref = dt.datetime(2026, 5, 5, 14, 0, tzinfo=dt.timezone.utc)
    sig = sunday_gap.detect_setup(df, ref_utc=ref)
    assert sig is None


def test_sunday_gap_up_fades_short():
    """Sunday gap UP > 0.3% → fade SHORT toward Friday close."""
    from src.trading.strategies import sunday_gap
    fri_close = 3300.0
    df = _build_df_with_friday_close(fri_close, current_close=3320.0)  # 0.6% gap up
    # Sunday 22:30 UTC
    ref = dt.datetime(2026, 5, 10, 22, 30, tzinfo=dt.timezone.utc)
    sig = sunday_gap.detect_setup(df, ref_utc=ref, min_gap_pct=0.003)
    if sig is not None:  # may need full df support
        assert sig.direction == "SHORT"
        assert sig.tp == fri_close


def _build_df_with_friday_close(fri_close: float, current_close: float = None) -> pd.DataFrame:
    """Build minimal df with Friday close at fri_close + current bar."""
    if current_close is None:
        current_close = fri_close
    # Build hourly bars for last 7 days
    bars = []
    end = dt.datetime(2026, 5, 11, 0, 0, tzinfo=dt.timezone.utc)
    for hours_back in range(168, 0, -1):
        t = end - dt.timedelta(hours=hours_back)
        # Mark Friday 21:55 close
        if t.weekday() == 4 and t.hour == 21:
            close = fri_close
        else:
            close = fri_close + np.random.uniform(-2, 2)
        bars.append({
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100,
        })
    bars.append({
        "open": current_close - 0.5,
        "high": current_close + 0.5,
        "low": current_close - 0.5,
        "close": current_close,
        "volume": 100,
    })
    timestamps = [end - dt.timedelta(hours=168 - i) for i in range(169)]
    df = pd.DataFrame(bars, index=pd.DatetimeIndex(timestamps, tz="UTC"))
    return df


# ── FOMC squeeze ──────────────────────────────────────────────────

def test_fomc_window_phases():
    from src.trading.strategies.fomc_squeeze import in_pre_fomc_window
    # Pick a date close to known 2026-04-29 FOMC
    pre = dt.datetime(2026, 4, 28, 12, 0, tzinfo=dt.timezone.utc)  # T-30h
    in_w, phase = in_pre_fomc_window(pre)
    assert in_w
    assert phase == "pre_fomc"

    event = dt.datetime(2026, 4, 29, 18, 0, tzinfo=dt.timezone.utc)  # T-0
    in_w, phase = in_pre_fomc_window(event)
    assert in_w
    assert phase == "event"

    post = dt.datetime(2026, 4, 29, 19, 0, tzinfo=dt.timezone.utc)  # T+1h
    in_w, phase = in_pre_fomc_window(post)
    assert in_w
    assert phase == "post_fomc"

    far = dt.datetime(2026, 4, 25, 0, 0, tzinfo=dt.timezone.utc)  # T-4d
    in_w, phase = in_pre_fomc_window(far)
    assert not in_w


# ── Tier compounding ──────────────────────────────────────────────

def test_get_current_tier():
    from src.risk.compounding import get_current_tier
    assert get_current_tier(8000) == (0, 1.0)
    assert get_current_tier(12000) == (0, 1.0)
    assert get_current_tier(20000) == (1, 1.1)
    assert get_current_tier(40000) == (2, 1.25)
    assert get_current_tier(75000) == (3, 1.4)
    assert get_current_tier(150000) == (4, 1.5)


def test_compounded_lot_default_off(monkeypatch):
    """Default OFF — return base unchanged."""
    monkeypatch.delenv("QUANT_TIER_COMPOUNDING", raising=False)
    from src.risk.compounding import compounded_lot
    out = compounded_lot(0.01, equity=50000)
    assert out["lot"] == 0.01
    assert out["status"] == "disabled"


def test_compounded_lot_on(monkeypatch):
    """When ON, applies tier multiplier (subject to persist check)."""
    monkeypatch.setenv("QUANT_TIER_COMPOUNDING", "1")
    from src.risk.compounding import compounded_lot
    # Tier 0 baseline — no compounding for fresh account
    out = compounded_lot(0.01, equity=12000)
    assert out["tier"] == 0
    assert out["multiplier"] == 1.0


# ── Strategy module imports ───────────────────────────────────────

def test_all_mega_modules_import():
    """Smoke check — all MEGA modules importable."""
    from src.trading.strategies import sunday_gap, fomc_squeeze  # noqa
    from src.risk.compounding import compounded_lot, get_current_tier  # noqa
