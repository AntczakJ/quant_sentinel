"""src/trading/strategies/mean_reversion.py — intraday range-fade.

2026-05-06 (Phase C.1 scaffold): intraday mean-reversion stub.

Logic: when price reaches Bollinger Band extreme + RSI extreme + volume
spike, fade the move expecting reversion to MA. Designed to be
UNCORRELATED with our SMC trend-follow primary scanner.

Per Lopez de Prado: 4 uncorrelated strategies × Sharpe 0.5 → portfolio
Sharpe ≈ 1.0. Adding mean-rev to our trend-follow gives the best
diversification (negative cross-regime correlation).

Default OFF — wire into scanner via QUANT_MEAN_REV_STRATEGY=1 after
3 months of forward observation on shadow log.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from . import StrategySignal


def detect_setup(df: pd.DataFrame, atr: float, rsi: float) -> Optional[StrategySignal]:
    """Detect intraday mean-reversion setup.

    Conditions for FADE LONG (from oversold extreme):
      - close near Bollinger lower band (< 1σ from mean - 2σ)
      - RSI < 25
      - 20-bar volume z-score > 1.5 (capitulation)

    Conditions for FADE SHORT (from overbought extreme):
      - mirror above

    Returns StrategySignal or None.
    """
    if df is None or len(df) < 20:
        return None

    try:
        close_now = float(df["close"].iloc[-1])
        ma20 = float(df["close"].rolling(20).mean().iloc[-1])
        std20 = float(df["close"].rolling(20).std().iloc[-1])
        if std20 <= 0:
            return None

        # Bollinger position
        upper_band = ma20 + 2 * std20
        lower_band = ma20 - 2 * std20

        # Volume z-score (use tick_volume if available)
        if "volume" in df.columns:
            vol_now = float(df["volume"].iloc[-1])
            vol_mean = float(df["volume"].rolling(20).mean().iloc[-1])
            vol_std = float(df["volume"].rolling(20).std().iloc[-1])
            vol_z = (vol_now - vol_mean) / vol_std if vol_std > 0 else 0
        else:
            vol_z = 0

        # FADE LONG: oversold + capitulation volume
        if close_now <= lower_band and rsi < 25 and vol_z > 1.5:
            return StrategySignal(
                strategy_name="mean_reversion",
                direction="LONG",
                confidence=min(0.85, (25 - rsi) / 25 + 0.5),
                entry=close_now,
                sl=close_now - atr * 1.0,  # tight SL — mean-rev fails fast
                tp=ma20,  # target = mean
                reason=f"oversold_capitulation rsi={rsi:.0f} vol_z={vol_z:.1f}",
                metadata={"upper": upper_band, "lower": lower_band, "ma20": ma20},
            )

        # FADE SHORT: overbought + capitulation volume
        if close_now >= upper_band and rsi > 75 and vol_z > 1.5:
            return StrategySignal(
                strategy_name="mean_reversion",
                direction="SHORT",
                confidence=min(0.85, (rsi - 75) / 25 + 0.5),
                entry=close_now,
                sl=close_now + atr * 1.0,
                tp=ma20,
                reason=f"overbought_capitulation rsi={rsi:.0f} vol_z={vol_z:.1f}",
                metadata={"upper": upper_band, "lower": lower_band, "ma20": ma20},
            )

        return None
    except Exception:
        return None
