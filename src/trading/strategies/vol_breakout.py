"""src/trading/strategies/vol_breakout.py — ATR-percentile breakout.

2026-05-06 (Phase C.3 scaffold): when ATR is at multi-day percentile
extreme, breakout from a contracted range often runs.

Logic: low-vol consolidation (ATR at <30th percentile of last 50 bars)
followed by close > previous-N-bar-high (or < low) = breakout signal.

Designed to capture momentum bursts after consolidation. Different
profile from SMC trend-follow (which catches established trends) and
mean-reversion (which fades extremes).

Default OFF.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import StrategySignal


def detect_setup(df: pd.DataFrame, atr: float) -> Optional[StrategySignal]:
    """Detect volatility-contraction breakout."""
    if df is None or len(df) < 50:
        return None

    try:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_series = tr.rolling(14).mean().tail(50)
        if len(atr_series) < 30:
            return None

        atr_now = float(atr_series.iloc[-1])
        atr_pct = (atr_series < atr_now).sum() / len(atr_series)
        if atr_pct >= 0.30:
            return None

        lookback = df.iloc[-21:-1]
        range_high = float(lookback["high"].max())
        range_low = float(lookback["low"].min())
        close_now = float(close.iloc[-1])

        if close_now > range_high:
            return StrategySignal(
                strategy_name="vol_breakout",
                direction="LONG",
                confidence=0.6 + (1 - atr_pct) * 0.3,
                entry=close_now,
                sl=range_low,
                tp=close_now + (close_now - range_low) * 2,
                reason=f"vol_contraction_breakout atr_pct={atr_pct:.0%}",
                metadata={"range_high": range_high, "range_low": range_low},
            )

        if close_now < range_low:
            return StrategySignal(
                strategy_name="vol_breakout",
                direction="SHORT",
                confidence=0.6 + (1 - atr_pct) * 0.3,
                entry=close_now,
                sl=range_high,
                tp=close_now - (range_high - close_now) * 2,
                reason=f"vol_contraction_breakdown atr_pct={atr_pct:.0%}",
                metadata={"range_high": range_high, "range_low": range_low},
            )

        return None
    except Exception:
        return None
