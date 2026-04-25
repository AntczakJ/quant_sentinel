"""
Triple-barrier labeling (Lopez de Prado).

For each candidate entry bar, set three barriers:
  - TP barrier: entry + (tp_atr * ATR_at_entry)
  - SL barrier: entry - (sl_atr * ATR_at_entry)
  - Time barrier: entry + max_horizon_bars

Walk forward bar-by-bar; first barrier hit wins.

Label encoding:
   1 = TP hit  (winner)
  -1 = SL hit  (loser)
   0 = Time barrier hit (neutral / timeout)

For SHORT direction, TP is below entry and SL above (sign flip handled
internally — caller passes direction).

Why this matters:
  Binary "did move 0.5 ATR in 5 bars" labels conflate winners with mean-
  reverters. Triple-barrier is directly aligned with how we trade
  (TP/SL exit), so the model learns what we actually use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Literal


def triple_barrier_labels(
    df: pd.DataFrame,
    direction: Literal["long", "short", "both"] = "long",
    tp_atr: float = 2.0,
    sl_atr: float = 1.0,
    max_horizon_bars: int = 48,
    atr_col: str = "atr",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    Compute triple-barrier labels for every bar in df.

    Args:
        df: OHLCV dataframe with columns: high, low, close, atr
            Index should be ordered (datetime).
        direction: 'long' = label as if entering LONG at each bar
                   'short' = SHORT
                   'both' = compute both, return label_long + label_short cols
        tp_atr: take-profit distance in ATR multiples
        sl_atr: stop-loss distance in ATR multiples
        max_horizon_bars: max bars to wait before time barrier hits
        atr_col, high_col, low_col, close_col: column names

    Returns:
        DataFrame indexed like df, with columns:
          - label                (-1, 0, 1)         [if single direction]
          - bars_to_exit         (int)
          - exit_price           (float)
          OR
          - label_long, label_short, bars_to_exit_long, ...  [if 'both']

    Performance: O(n * max_horizon_bars) — for 100k bars × 48 horizon
    ~5M ops, runs in ~5-10 sec on typical hardware.
    """
    if direction == "both":
        result_long = triple_barrier_labels(
            df, "long", tp_atr, sl_atr, max_horizon_bars,
            atr_col, high_col, low_col, close_col,
        )
        result_short = triple_barrier_labels(
            df, "short", tp_atr, sl_atr, max_horizon_bars,
            atr_col, high_col, low_col, close_col,
        )
        return pd.DataFrame({
            "label_long": result_long["label"],
            "bars_to_exit_long": result_long["bars_to_exit"],
            "exit_price_long": result_long["exit_price"],
            "label_short": result_short["label"],
            "bars_to_exit_short": result_short["bars_to_exit"],
            "exit_price_short": result_short["exit_price"],
        }, index=df.index)

    n = len(df)
    closes = df[close_col].values
    highs = df[high_col].values
    lows = df[low_col].values
    atrs = df[atr_col].values

    labels = np.zeros(n, dtype=np.int8)
    bars_to_exit = np.full(n, max_horizon_bars, dtype=np.int32)
    exit_prices = closes.copy()

    sign = 1 if direction == "long" else -1

    for i in range(n - 1):
        entry = closes[i]
        atr = atrs[i]
        if not np.isfinite(atr) or atr <= 0:
            labels[i] = 0
            bars_to_exit[i] = 0
            exit_prices[i] = entry
            continue

        tp_price = entry + sign * tp_atr * atr
        sl_price = entry - sign * sl_atr * atr

        # Walk forward up to max_horizon_bars or end of df
        horizon_end = min(i + 1 + max_horizon_bars, n)
        hit_label = 0
        hit_bar = max_horizon_bars
        hit_price = closes[horizon_end - 1] if horizon_end > i + 1 else entry

        for j in range(i + 1, horizon_end):
            high_j = highs[j]
            low_j = lows[j]

            if direction == "long":
                # Note: if both TP and SL hit in the same bar, conservative
                # assumption is SL hit first (worst-case fill).
                hit_sl = low_j <= sl_price
                hit_tp = high_j >= tp_price
                if hit_sl and hit_tp:
                    hit_label = -1
                    hit_price = sl_price
                elif hit_sl:
                    hit_label = -1
                    hit_price = sl_price
                elif hit_tp:
                    hit_label = 1
                    hit_price = tp_price
                else:
                    continue
            else:  # short
                hit_sl = high_j >= sl_price
                hit_tp = low_j <= tp_price
                if hit_sl and hit_tp:
                    hit_label = -1
                    hit_price = sl_price
                elif hit_sl:
                    hit_label = -1
                    hit_price = sl_price
                elif hit_tp:
                    hit_label = 1
                    hit_price = tp_price
                else:
                    continue

            hit_bar = j - i
            break

        labels[i] = hit_label
        bars_to_exit[i] = hit_bar
        exit_prices[i] = hit_price

    return pd.DataFrame({
        "label": labels,
        "bars_to_exit": bars_to_exit,
        "exit_price": exit_prices,
    }, index=df.index)
