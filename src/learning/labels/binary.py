"""
Legacy binary label (kept for back-compat with existing v1 training).

Use case: train_all.py uses src/analysis/compute.compute_target which
returns 0/1 binary based on '>0.5 ATR move in 5 bars'. This module
exposes the same logic explicitly so v2 code can compare label methods.

Prefer triple_barrier or r_multiple for new training.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Literal


def binary_labels(
    df: pd.DataFrame,
    direction: Literal["long", "short"] = "long",
    horizon_bars: int = 5,
    threshold_atr: float = 0.5,
    atr_col: str = "atr",
    close_col: str = "close",
) -> pd.Series:
    """
    Binary label: 1 if price moves >threshold_atr * ATR in next N bars.

    Direction-aware:
      - LONG: 1 if next N-bar high - entry >= threshold_atr * ATR
      - SHORT: 1 if entry - next N-bar low >= threshold_atr * ATR

    Returns a pandas Series of 0/1, same index as df.
    """
    closes = df[close_col].values
    atrs = df[atr_col].values
    high = df["high"].values if "high" in df.columns else closes
    low = df["low"].values if "low" in df.columns else closes

    n = len(df)
    labels = np.zeros(n, dtype=np.int8)
    for i in range(n - horizon_bars):
        atr = atrs[i]
        if not np.isfinite(atr) or atr <= 0:
            continue
        threshold = threshold_atr * atr
        entry = closes[i]
        future_high = high[i + 1:i + 1 + horizon_bars].max()
        future_low = low[i + 1:i + 1 + horizon_bars].min()
        if direction == "long":
            if (future_high - entry) >= threshold:
                labels[i] = 1
        else:
            if (entry - future_low) >= threshold:
                labels[i] = 1
    return pd.Series(labels, index=df.index, name=f"binary_label_{direction}")
