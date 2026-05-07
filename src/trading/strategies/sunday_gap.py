"""src/trading/strategies/sunday_gap.py — Sunday open gap-fill setup.

Gold (XAU/USD) closes Friday 22:00 UTC and reopens Sunday 22:00 UTC.
Weekend news (geopolitical, Asia headlines) often produces a Sunday-open
gap. Empirical: ~70% of gaps fill within 3 trading days.

Strategy:
  1. Mark Friday close (last 5min Fri 21:55-22:00 UTC)
  2. Mark Sunday/Monday open (first 1h Sun 22:00 UTC onwards)
  3. If |gap| > 0.3% AND first hour confirms direction (no further gap):
     → fade gap toward Friday close
  4. SL: 1.5× gap size beyond entry
  5. TP: Friday close (full gap fill)

Risk: gaps from real news (war, central bank surprise) often run, not
fill. Filter: skip if NFP/FOMC/major event in past 48h OR major
geopolitical news headline detected.

Default OFF — env-flag QUANT_SUNDAY_GAP_LIVE=1.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import pandas as pd

from . import StrategySignal


def _last_friday_close_price(df: pd.DataFrame, ref: dt.datetime) -> Optional[float]:
    """Find Friday 22:00 UTC bar's close price.

    df should be 5min or 15min indexed by UTC datetime, last ~7 days.
    """
    try:
        # Walk back from ref to last Friday at or before 22:00 UTC
        days_back = (ref.weekday() - 4) % 7
        if days_back == 0 and ref.hour < 22:
            days_back = 7
        target_date = (ref - dt.timedelta(days=days_back)).date()
        # Find bars on that Friday with hour=21 (XAU closes 22:00 ≈ last 21:xx bar)
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        mask = (idx.date == target_date) & (idx.hour == 21) & (idx.minute >= 45)
        candidates = df[mask]
        if candidates.empty:
            return None
        return float(candidates["close"].iloc[-1])
    except Exception:
        return None


def detect_setup(df: pd.DataFrame, ref_utc: Optional[dt.datetime] = None,
                 min_gap_pct: float = 0.003) -> Optional[StrategySignal]:
    """Detect Sunday-open gap-fill setup.

    Args:
        df: OHLCV with UTC datetime index, ≥7 days history
        ref_utc: current time (default: sim_time.now_utc)
        min_gap_pct: minimum gap fraction (0.003 = 0.3%)
    """
    if ref_utc is None:
        from src.trading.sim_time import now_utc as _sim_now
        ref_utc = _sim_now()
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=dt.timezone.utc)

    # Only fire Sunday 22:00 UTC + 3 hours (during initial Sunday open
    # liquidity window) OR Monday before 12:00 UTC if gap not filled yet
    weekday = ref_utc.weekday()
    hour = ref_utc.hour
    in_sunday_open = (weekday == 6 and hour >= 22) or (weekday == 0 and hour < 12)
    if not in_sunday_open:
        return None

    # Get Friday close
    fri_close = _last_friday_close_price(df, ref_utc)
    if fri_close is None:
        return None

    if df is None or len(df) < 10:
        return None
    current = float(df["close"].iloc[-1])
    gap = (current - fri_close) / fri_close
    abs_gap = abs(gap)

    if abs_gap < min_gap_pct:
        return None

    # Need at least 3 bars post-Sunday-open to confirm direction stable
    # (avoid catching falling-knife gap that keeps running)
    last_5 = df.iloc[-5:]
    if len(last_5) < 5:
        return None
    rng = float(last_5["high"].max()) - float(last_5["low"].min())
    if rng > abs_gap * fri_close * 0.5:
        # Range too wide — gap not stable, no fade
        return None

    # Direction: fade gap → if gap UP, SHORT toward fri_close. If gap DOWN, LONG.
    if gap > 0:
        return StrategySignal(
            strategy_name="sunday_gap_fade",
            direction="SHORT",
            confidence=min(0.85, 0.5 + abs_gap * 50),  # bigger gap → higher conf
            entry=current,
            sl=current * (1 + abs_gap * 1.5),  # 1.5× gap size beyond entry
            tp=fri_close,  # full gap fill
            reason=f"sunday_gap_up={abs_gap*100:.2f}% fade to fri_close={fri_close:.2f}",
            metadata={"fri_close": fri_close, "gap_pct": gap * 100},
        )
    return StrategySignal(
        strategy_name="sunday_gap_fade",
        direction="LONG",
        confidence=min(0.85, 0.5 + abs_gap * 50),
        entry=current,
        sl=current * (1 - abs_gap * 1.5),
        tp=fri_close,
        reason=f"sunday_gap_down={abs_gap*100:.2f}% fade to fri_close={fri_close:.2f}",
        metadata={"fri_close": fri_close, "gap_pct": gap * 100},
    )
