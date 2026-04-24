"""
src/trading/asia_orb.py — Asia Session Opening Range Breakout detector (2026-04-24).

Research-backed edge (docs/research/2026-04-24_xau_strategies_research.md):
  TradeThatSwing backtest: +411%/yr on gold futures with auto-rules ORB.
  Profit factor 7.29 on the Asia-open variant.

Mechanism:
  Asia session (00:00-07:00 UTC, roughly) is genuinely low-liquidity for
  gold. Institutional participation is minimal. Ranges established in Asia
  cluster retail stops. London open (07:00 UTC) forces European bank desks
  to reallocate, breaking through stop clusters in whichever direction
  institutions actually need to position. First-break of Asia H/L with
  HTF trend filter is a repeatable edge.

Signal logic:
  1. At 07:00 UTC (London open), compute Asia session H/L from prior 7h.
  2. Current bar closes > Asia H → signal LONG
     Current bar closes < Asia L → signal SHORT
  3. Filter: HTF 200 EMA must agree with direction (no counter-trend ORB).
  4. Invalidation: 2 hours past London open without break → stand down.

Fails on:
  - NFP/FOMC days (gap-through, stops wiped by volatility not direction)
  - Holiday Asia (thin volume → fake breaks)
  - Already-at-extremes (ORB plus an exhausted trend = failure)
"""
from __future__ import annotations

import datetime as dt
from typing import Literal, Optional

import pandas as pd


ORBDirection = Literal["LONG", "SHORT", "NONE"]


def _parse_ts(val) -> Optional[dt.datetime]:
    """Best-effort parse of various timestamp representations."""
    if isinstance(val, dt.datetime):
        return val if val.tzinfo else val.replace(tzinfo=dt.timezone.utc)
    if isinstance(val, pd.Timestamp):
        try:
            ts = val.to_pydatetime()
            return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
        except Exception:
            return None
    try:
        ts = pd.Timestamp(val).to_pydatetime()
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _asia_window_bounds(reference_utc: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """Return (asia_start, asia_end) UTC timestamps for the current/just-ended
    Asia session.

    Asia session = 00:00-07:00 UTC (seven hours, ends at London open).
    If reference is before 07:00 UTC, Asia isn't finished — return the
    window that will END at the next 07:00. Caller is expected to use this
    function AFTER 07:00 UTC.
    """
    date = reference_utc.date()
    # If it's before 07:00 UTC today, Asia ends today 07:00
    asia_end = dt.datetime.combine(date, dt.time(7, 0, tzinfo=dt.timezone.utc))
    if reference_utc < asia_end:
        # Asia ending today
        asia_start = asia_end - dt.timedelta(hours=7)
    else:
        # Asia already ended today; next run uses today's Asia window
        asia_start = asia_end - dt.timedelta(hours=7)
    return asia_start, asia_end


def get_asia_range(df: pd.DataFrame, reference_utc: Optional[dt.datetime] = None) -> Optional[dict]:
    """Extract the Asia-session high/low from OHLC data.

    Args:
        df: OHLC dataframe with DatetimeIndex (UTC). Must contain 'high' and 'low'.
        reference_utc: anchor time for selecting the Asia window. Defaults to
            `datetime.utcnow()`.

    Returns None if insufficient bars in the Asia window, else:
        {'high': float, 'low': float, 'start': dt, 'end': dt, 'bars': int}
    """
    if df is None or len(df) == 0:
        return None
    if reference_utc is None:
        reference_utc = dt.datetime.now(dt.timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=dt.timezone.utc)

    asia_start, asia_end = _asia_window_bounds(reference_utc)

    try:
        # Ensure index is datetime UTC
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'timestamp' in df.columns:
                df = df.set_index(pd.DatetimeIndex(df['timestamp']))
            else:
                return None
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize('UTC')
        mask = (idx >= asia_start) & (idx < asia_end)
        # Boolean mask must be passed as positional, not label-based (`.loc[mask]`
        # would reinterpret mask as labels). Use np.ndarray mask + .iloc.
        import numpy as _np
        window = df.iloc[_np.asarray(mask)]
        if len(window) < 3:
            return None  # not enough Asia bars; holiday or early session
        return {
            'high': float(window['high'].max()),
            'low': float(window['low'].min()),
            'start': asia_start,
            'end': asia_end,
            'bars': len(window),
        }
    except Exception:
        return None


def detect_orb_signal(
    df: pd.DataFrame,
    htf_ema200: Optional[float] = None,
    reference_utc: Optional[dt.datetime] = None,
    max_post_open_hours: float = 2.0,
) -> dict:
    """Detect an Asia ORB breakout signal at current bar.

    Args:
        df: OHLC with DatetimeIndex UTC. Should include at least last ~24h.
        htf_ema200: if provided, require breakout direction to match trend
            (close > EMA200 for LONG breakout, close < EMA200 for SHORT).
            Pass None to skip HTF filter.
        reference_utc: current time anchor. Defaults to now.
        max_post_open_hours: invalidate signal if this many hours have
            elapsed since London open (default 2h — first-move edge decays).

    Returns:
        {
          'direction': 'LONG' | 'SHORT' | 'NONE',
          'asia_high': float | None,
          'asia_low': float | None,
          'current_close': float | None,
          'reason': human-readable string,
        }
    """
    if reference_utc is None:
        reference_utc = dt.datetime.now(dt.timezone.utc)
    if reference_utc.tzinfo is None:
        reference_utc = reference_utc.replace(tzinfo=dt.timezone.utc)

    result: dict = {
        'direction': 'NONE',
        'asia_high': None,
        'asia_low': None,
        'current_close': None,
        'reason': '',
    }

    asia = get_asia_range(df, reference_utc)
    if asia is None:
        result['reason'] = 'insufficient_asia_data'
        return result
    result['asia_high'] = asia['high']
    result['asia_low'] = asia['low']

    # Time gate: only fire between London open and +max_post_open_hours
    london_open = asia['end']
    minutes_since_open = (reference_utc - london_open).total_seconds() / 60
    if minutes_since_open < 0:
        result['reason'] = 'pre_london_open'
        return result
    if minutes_since_open > max_post_open_hours * 60:
        result['reason'] = f'stale (>{max_post_open_hours}h after London open)'
        return result

    # Get current close (last bar of df)
    try:
        current_close = float(df['close'].iloc[-1])
        result['current_close'] = current_close
    except (KeyError, IndexError, TypeError):
        result['reason'] = 'no_current_close'
        return result

    # Breakout check
    bull_break = current_close > asia['high']
    bear_break = current_close < asia['low']

    if not bull_break and not bear_break:
        result['reason'] = 'inside_asia_range'
        return result

    # HTF filter (optional)
    if htf_ema200 is not None:
        if bull_break and current_close < htf_ema200:
            result['reason'] = 'bull_break_below_ema200'
            return result
        if bear_break and current_close > htf_ema200:
            result['reason'] = 'bear_break_above_ema200'
            return result

    result['direction'] = 'LONG' if bull_break else 'SHORT'
    result['reason'] = (
        f"{'bull' if bull_break else 'bear'}_break_of_asia_"
        f"{'high' if bull_break else 'low'}"
    )
    return result
