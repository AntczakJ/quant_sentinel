"""
src/analysis/regime.py — Market regime classification (rule-based V1, 2026-04-24).

Research conclusion (docs/research/2026-04-24_xau_strategies_research.md):
"Regime classifier is likely the biggest single WR lever — bigger than any new
voter. Fixes the 04-17→22 streak root cause where trend-follow strategies
ran in a ranging regime and got chopped."

Four regimes, derived from three indicators:
  - BBW compression ratio: Bollinger Bandwidth / 50-bar BBW mean
  - ADX (from compute_features, normalized 0-1)
  - ATR ratio: current ATR / 20-bar ATR mean

Regimes:
  squeeze              — BBW compression < 0.6 (bands tight, break imminent)
  trending_high_vol    — ADX > 0.35 AND ATR ratio > 1.3
  trending_low_vol     — ADX > 0.35 AND ATR ratio <= 1.3
  ranging              — everything else (ADX low, or conflicting signals)

Strategy routing (consumed by scanner.py):
  squeeze              → block entries (wait for break direction)
  trending_high_vol    → trust trend-follow voters (LSTM/DQN direction)
  trending_low_vol     → SMC + retracement plays; normal voter weights
  ranging              → mean-reversion, liquidity sweep reversal, fade PDH/PDL
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

Regime = Literal["squeeze", "trending_high_vol", "trending_low_vol", "ranging"]

_BBW_SQUEEZE_RATIO = 0.6     # < this = compression
_ADX_TREND_THRESHOLD = 0.35  # > this = trending (ADX is normalized 0-1)
_ATR_EXPANSION_HIGH = 1.3    # > this × 20-bar mean = high-vol regime


def _bollinger_bandwidth(close: pd.Series, window: int = 20, std_mult: float = 2.0) -> pd.Series:
    """Normalized Bollinger Bandwidth: (upper - lower) / mid.

    Independent of price level — compresses same amount whether gold is $1900
    or $2700. Returns NaN for the first `window` bars.
    """
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return (upper - lower) / (mid + 1e-10)


def classify_regime(df: pd.DataFrame) -> Regime:
    """Classify the current regime from an OHLC dataframe.

    Expects `close` column at minimum. If `adx` or `atr` are pre-computed
    (by compute_features), uses those; otherwise computes lightweight
    substitutes. Defaults to 'ranging' on any exception — safe fallback.
    """
    if df is None or len(df) < 50:
        return "ranging"

    try:
        close = df['close']

        # --- BBW compression ratio ---
        bbw = _bollinger_bandwidth(close, window=20)
        bbw_current = float(bbw.iloc[-1]) if not pd.isna(bbw.iloc[-1]) else None
        bbw_ma = bbw.rolling(50).mean()
        bbw_ma_current = float(bbw_ma.iloc[-1]) if not pd.isna(bbw_ma.iloc[-1]) else None

        compression = (
            bbw_current / bbw_ma_current
            if bbw_current is not None and bbw_ma_current and bbw_ma_current > 0
            else 1.0
        )

        # --- ADX ---
        if 'adx' in df.columns and not pd.isna(df['adx'].iloc[-1]):
            # adx from compute_features is normalized to 0-1
            adx_current = float(df['adx'].iloc[-1])
        else:
            # Lightweight ADX approximation: 20-bar directional move ratio
            high = df['high'] if 'high' in df.columns else close
            low = df['low'] if 'low' in df.columns else close
            up_move = (high - high.shift(1)).clip(lower=0).rolling(14).mean()
            down_move = (low.shift(1) - low).clip(lower=0).rolling(14).mean()
            total = up_move + down_move + 1e-10
            adx_current = float(abs(up_move - down_move).iloc[-1] / total.iloc[-1])

        # --- ATR expansion ---
        if 'atr_expansion' in df.columns and not pd.isna(df['atr_expansion'].iloc[-1]):
            atr_ratio = float(df['atr_expansion'].iloc[-1])
        elif 'atr' in df.columns:
            atr = df['atr']
            atr_mean = atr.rolling(20).mean().iloc[-1]
            atr_ratio = float(atr.iloc[-1] / (atr_mean + 1e-10)) if not pd.isna(atr_mean) else 1.0
        else:
            # Derive from close-range ratio
            rng = (df['high'] - df['low']).rolling(14).mean() if 'high' in df.columns else close.diff().abs().rolling(14).mean()
            atr_ratio = float(rng.iloc[-1] / (rng.rolling(20).mean().iloc[-1] + 1e-10)) if not pd.isna(rng.iloc[-1]) else 1.0

        # --- Classify ---
        if compression < _BBW_SQUEEZE_RATIO:
            return "squeeze"
        if adx_current > _ADX_TREND_THRESHOLD:
            return "trending_high_vol" if atr_ratio > _ATR_EXPANSION_HIGH else "trending_low_vol"
        return "ranging"

    except Exception:
        return "ranging"


def regime_diagnostics(df: pd.DataFrame) -> dict:
    """Return regime + the three indicator values that drove the decision.

    Useful for dashboards and debugging. Never raises — returns a dict with
    `regime` and `error` on failure.
    """
    if df is None or len(df) < 50:
        return {"regime": "ranging", "reason": "insufficient_data"}
    try:
        close = df['close']
        bbw = _bollinger_bandwidth(close, window=20)
        bbw_current = float(bbw.iloc[-1]) if not pd.isna(bbw.iloc[-1]) else None
        bbw_ma_current = float(bbw.rolling(50).mean().iloc[-1])
        compression = bbw_current / bbw_ma_current if bbw_current and bbw_ma_current else 1.0

        if 'adx' in df.columns and not pd.isna(df['adx'].iloc[-1]):
            adx_current = float(df['adx'].iloc[-1])
        else:
            adx_current = np.nan

        atr_ratio = float(df['atr_expansion'].iloc[-1]) if 'atr_expansion' in df.columns and not pd.isna(df['atr_expansion'].iloc[-1]) else np.nan

        regime = classify_regime(df)
        return {
            "regime": regime,
            "bbw_compression_ratio": round(compression, 3),
            "adx": round(adx_current, 3) if not np.isnan(adx_current) else None,
            "atr_expansion": round(atr_ratio, 3) if not np.isnan(atr_ratio) else None,
            "thresholds": {
                "squeeze_below": _BBW_SQUEEZE_RATIO,
                "trending_above_adx": _ADX_TREND_THRESHOLD,
                "high_vol_above_atr_ratio": _ATR_EXPANSION_HIGH,
            },
        }
    except Exception as e:
        return {"regime": "ranging", "error": str(e)}
