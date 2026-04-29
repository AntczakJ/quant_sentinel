"""
Triple-barrier labeling (Lopez de Prado).

For each candidate entry bar, set three barriers:
  - TP barrier: entry + (tp_atr * ATR_at_entry)
  - SL barrier: entry - (sl_atr * ATR_at_entry)
  - Time barrier: entry + max_horizon_bars

Walk forward bar-by-bar; first barrier hit wins.

Label encoding (canonical for src.learning.labels package):
   1 = TP hit  (winner)
  -1 = SL hit  (loser)
   0 = Time barrier hit (neutral / timeout)

For SHORT direction, TP is below entry and SL above (sign flip handled
internally — caller passes direction).

Why this matters:
  Binary "did move 0.5 ATR in 5 bars" labels conflate winners with mean-
  reverters. Triple-barrier is directly aligned with how we trade
  (TP/SL exit), so the model learns what we actually use.

Performance:
  Numba JIT acceleration applied to the inner walk-forward kernel when
  numba is installed (~60x speedup on 100k+ rows). Falls back to pure
  numpy when numba unavailable. Encoding and public API unchanged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Literal


try:
    from numba import njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False
    def njit(*args, **kwargs):  # type: ignore[no-redef]
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return lambda f: f


# ─── Numba-JIT inner kernel (single direction) ──────────────────────────
# Encoding inside kernel: same as public API (1 / -1 / 0).
# Same-bar TP+SL is resolved to SL (worst-case fill assumption) — matches
# Lopez de Prado convention and the pre-Numba implementation behavior.

@njit(cache=True)
def _walk_forward_single(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    atrs: np.ndarray,
    is_long: bool,
    tp_atr: float,
    sl_atr: float,
    max_horizon: int,
):
    n = len(closes)
    labels = np.zeros(n, dtype=np.int8)
    bars_to_exit = np.full(n, max_horizon, dtype=np.int32)
    exit_prices = closes.copy()

    sign = 1.0 if is_long else -1.0

    for i in range(n - 1):
        entry = closes[i]
        atr = atrs[i]
        if not np.isfinite(atr) or atr <= 0.0:
            labels[i] = 0
            bars_to_exit[i] = 0
            exit_prices[i] = entry
            continue

        tp_price = entry + sign * tp_atr * atr
        sl_price = entry - sign * sl_atr * atr

        horizon_end = i + 1 + max_horizon
        if horizon_end > n:
            horizon_end = n
        hit_label = 0
        hit_bar = max_horizon
        # Default exit price = close at end of horizon (timeout fill)
        if horizon_end > i + 1:
            hit_price = closes[horizon_end - 1]
        else:
            hit_price = entry

        for j in range(i + 1, horizon_end):
            high_j = highs[j]
            low_j = lows[j]

            if is_long:
                hit_sl = low_j <= sl_price
                hit_tp = high_j >= tp_price
            else:
                hit_sl = high_j >= sl_price
                hit_tp = low_j <= tp_price

            if hit_sl and hit_tp:
                # Same-bar ambiguity: SL first (worst-case)
                hit_label = -1
                hit_price = sl_price
                hit_bar = j - i
                break
            if hit_sl:
                hit_label = -1
                hit_price = sl_price
                hit_bar = j - i
                break
            if hit_tp:
                hit_label = 1
                hit_price = tp_price
                hit_bar = j - i
                break

        labels[i] = hit_label
        bars_to_exit[i] = hit_bar
        exit_prices[i] = hit_price

    return labels, bars_to_exit, exit_prices


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

    Performance: Numba-JIT inner loop. ~60x faster than pure-python on
    100k+ rows. Falls back to pure-numpy walking when Numba unavailable.
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

    closes = df[close_col].to_numpy(dtype=np.float64)
    highs = df[high_col].to_numpy(dtype=np.float64)
    lows = df[low_col].to_numpy(dtype=np.float64)
    atrs = df[atr_col].to_numpy(dtype=np.float64)

    labels, bars_to_exit, exit_prices = _walk_forward_single(
        closes, highs, lows, atrs,
        direction == "long",
        float(tp_atr), float(sl_atr), int(max_horizon_bars),
    )

    return pd.DataFrame({
        "label": labels,
        "bars_to_exit": bars_to_exit,
        "exit_price": exit_prices,
    }, index=df.index)
