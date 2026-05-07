"""src/trading/strategies/fomc_squeeze.py — Pre-FOMC volatility compression breakout.

Empirical pattern (Fed Reserve research + market microstructure papers):
Gold compresses 24-48h BEFORE FOMC announcement (dealers reduce
exposure to event risk). Then 30-60 min POST-announcement, vol expands
as positions re-establish.

Strategy:
  1. Detect pre-FOMC window (T-2 days to T-30min)
  2. Mark consolidation range (high/low of that period)
  3. Wait for FOMC announcement (T+0)
  4. After T+30min, if price breaks out of pre-FOMC range:
     → trade in direction of break with vol-targeted stop
  5. Hold until next major event OR 4h max

Edge: ~2R per FOMC × 8 FOMCs/year = +16R/year. Combined with existing
post_news_2nd_rotation factor.

Risk: surprise hawkish/dovish move can trap; SL must be tight.

Default OFF — env-flag QUANT_FOMC_SQUEEZE_LIVE=1.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from . import StrategySignal


# FOMC announcement schedule (publicly known via FOMC calendar).
# 8 meetings/year, typically Wed 18:00 UTC (= 14:00 ET).
# Operator updates this list each January when Fed publishes calendar.
FOMC_DATES_UTC = [
    # 2026 schedule
    "2026-01-28T19:00",
    "2026-03-18T18:00",
    "2026-04-29T18:00",
    "2026-06-17T18:00",
    "2026-07-29T18:00",
    "2026-09-16T18:00",
    "2026-11-04T19:00",  # post-DST
    "2026-12-16T19:00",
]


def _next_fomc(ref_utc: dt.datetime) -> Optional[dt.datetime]:
    """Find next upcoming FOMC date from schedule."""
    for d in FOMC_DATES_UTC:
        announce = dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc)
        if announce > ref_utc:
            return announce
    return None


def _nearest_fomc(ref_utc: dt.datetime) -> Optional[dt.datetime]:
    """Find FOMC closest to ref (past or future). Needed for post-FOMC
    phase where next-FOMC may be months away but previous-FOMC was hours ago."""
    if not FOMC_DATES_UTC:
        return None
    parsed = [dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc)
              for d in FOMC_DATES_UTC]
    return min(parsed, key=lambda d: abs((d - ref_utc).total_seconds()))


def in_pre_fomc_window(ref_utc: Optional[dt.datetime] = None) -> tuple[bool, str]:
    """Return (in_window, phase).

    Phases:
      'pre_fomc'  — T-48h to T-30min (compression period)
      'event'     — T-30min to T+30min (announcement, no trade)
      'post_fomc' — T+30min to T+4h (breakout window)
      ''          — outside any window
    """
    if ref_utc is None:
        from src.trading.sim_time import now_utc as _sim_now
        ref_utc = _sim_now()
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=dt.timezone.utc)

    nearest = _nearest_fomc(ref_utc)
    if nearest is None:
        return False, ""
    delta = (nearest - ref_utc).total_seconds()
    # delta > 0 = nearest FOMC is in future; delta < 0 = past
    # T-48h .. T-30min = pre-FOMC compression
    if 1800 < delta <= 48 * 3600:
        return True, "pre_fomc"
    if -1800 <= delta <= 1800:
        return True, "event"
    if -4 * 3600 <= delta < -1800:
        return True, "post_fomc"
    return False, ""


def detect_setup(df: pd.DataFrame, atr: float,
                 ref_utc: Optional[dt.datetime] = None) -> Optional[StrategySignal]:
    """Detect pre-FOMC compression → post-announcement breakout."""
    if ref_utc is None:
        from src.trading.sim_time import now_utc as _sim_now
        ref_utc = _sim_now()

    in_win, phase = in_pre_fomc_window(ref_utc)
    if not in_win or phase != "post_fomc":
        return None  # Only fire in post-FOMC breakout window

    if df is None or len(df) < 200:
        return None

    # Find pre-FOMC range: bars from T-48h to T-30min
    next_fomc = _next_fomc(ref_utc - dt.timedelta(hours=8))  # find FOMC just past
    if next_fomc is None:
        return None

    pre_start = next_fomc - dt.timedelta(hours=48)
    pre_end = next_fomc - dt.timedelta(minutes=30)

    try:
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        mask = (idx >= pre_start) & (idx <= pre_end)
        pre_window = df[mask]
        if len(pre_window) < 20:
            return None

        range_high = float(pre_window["high"].max())
        range_low = float(pre_window["low"].min())
        current = float(df["close"].iloc[-1])

        # Bullish breakout
        if current > range_high:
            return StrategySignal(
                strategy_name="fomc_squeeze",
                direction="LONG",
                confidence=0.7,
                entry=current,
                sl=range_low,
                tp=current + (current - range_low) * 2,  # 2R target
                reason=f"fomc_breakout_up post-{next_fomc.date()}",
                metadata={"range_high": range_high, "range_low": range_low,
                          "fomc_date": str(next_fomc.date())},
            )
        if current < range_low:
            return StrategySignal(
                strategy_name="fomc_squeeze",
                direction="SHORT",
                confidence=0.7,
                entry=current,
                sl=range_high,
                tp=current - (range_high - current) * 2,
                reason=f"fomc_breakout_down post-{next_fomc.date()}",
                metadata={"range_high": range_high, "range_low": range_low,
                          "fomc_date": str(next_fomc.date())},
            )
        return None
    except Exception:
        return None
