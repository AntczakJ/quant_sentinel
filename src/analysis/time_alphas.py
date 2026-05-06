"""src/analysis/time_alphas.py — calendar / time-of-day alpha computations.

2026-05-06 (Phase A): time-based alphas extracted into one module so
score_setup_quality can consume cleanly.

Alphas implemented:
  - LBMA fix windows (10:30 + 15:00 UTC ±5min) — known dealer hedging
  - January seasonality — Q1 bull bias on gold
  - End-of-month rebalancing — last 3 days dollar flows
  - Pre-NFP positioning (Tue-Thu before first Friday)
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


# LBMA Gold Price fixes — published auctions at 10:30 and 15:00 London time
# (UTC during winter; UTC+1 during BST/summer time). Rather than tracking
# DST complexity, anchor to UTC: dealers worldwide hedge against the fix
# in pre-fix range, releasing pent-up flow post-fix.
#
# Volatility expansion documented:
#   - 10-min PRE: dealers warehouse client orders → range builds
#   - 5-min POST: fix prints, dealers unload → directional break
#
# Source: lbma.org.uk/prices-and-data/lbma-gold-price
LBMA_FIX_WINDOWS_UTC = [
    # (start_h, start_m, end_h, end_m) — capture pre-fix range + 30m post
    (10, 25, 11, 5),
    (14, 55, 15, 35),
]


def in_lbma_fix_window(reference_utc: Optional[dt.datetime] = None) -> dict:
    """Check if current bar falls in LBMA fix window.

    Returns dict:
        in_window: bool
        phase: 'pre_fix' | 'post_fix' | None
        fix_time: 'AM' | 'PM' | None
    """
    if reference_utc is None:
        from src.trading.sim_time import now_utc as _sim_now_utc
        reference_utc = _sim_now_utc()
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=dt.timezone.utc)

    h, m = reference_utc.hour, reference_utc.minute
    minutes = h * 60 + m

    for fix_idx, (sh, sm, eh, em) in enumerate(LBMA_FIX_WINDOWS_UTC):
        win_start = sh * 60 + sm
        win_end = eh * 60 + em
        # Fix prints at start_h+5min approx
        fix_minute = sh * 60 + (sm + 5)
        if win_start <= minutes <= win_end:
            phase = 'pre_fix' if minutes < fix_minute else 'post_fix'
            return {
                'in_window': True,
                'phase': phase,
                'fix_time': 'AM' if fix_idx == 0 else 'PM',
            }
    return {'in_window': False, 'phase': None, 'fix_time': None}


# ── January seasonality ───────────────────────────────────────────────

def january_long_bias(reference_utc: Optional[dt.datetime] = None) -> bool:
    """Q1 bull bias on gold — January historically positive 80% of years.

    Returns True if current month is January OR first 3 weeks of February
    (extension of the seasonal lift). False otherwise.
    """
    if reference_utc is None:
        from src.trading.sim_time import now_utc as _sim_now_utc
        reference_utc = _sim_now_utc()
    month = reference_utc.month
    day = reference_utc.day
    if month == 1:
        return True
    if month == 2 and day <= 21:  # tail of seasonal lift
        return True
    return False


# ── End-of-month rebalancing flow ─────────────────────────────────────

def end_of_month_window(reference_utc: Optional[dt.datetime] = None) -> bool:
    """Last 3 trading days of month — institutional rebalancing flows.

    Returns True if today is in last 3 calendar days of the month.
    """
    if reference_utc is None:
        from src.trading.sim_time import now_utc as _sim_now_utc
        reference_utc = _sim_now_utc()
    # Get last day of this month
    next_month = (reference_utc.replace(day=28) + dt.timedelta(days=4))
    last_day = (next_month - dt.timedelta(days=next_month.day)).day
    return reference_utc.day >= last_day - 2


# ── Pre-NFP positioning (T-2 to T-1 before first Friday) ──────────────

def pre_nfp_window(reference_utc: Optional[dt.datetime] = None) -> bool:
    """Tuesday-Thursday before first Friday of month (NFP day).

    Vol-compression then expansion documented. Use as warning gate.
    """
    if reference_utc is None:
        from src.trading.sim_time import now_utc as _sim_now_utc
        reference_utc = _sim_now_utc()
    # Find first Friday of current month
    d = reference_utc.replace(day=1)
    while d.weekday() != 4:  # 4 = Friday
        d += dt.timedelta(days=1)
    first_friday = d.day
    # T-2 (Wed) and T-1 (Thu) before first Friday
    target_days = {first_friday - 2, first_friday - 1, first_friday - 3}
    return reference_utc.day in target_days
