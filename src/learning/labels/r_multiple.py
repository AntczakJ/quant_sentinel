"""
R-multiple regression labels.

For each entry bar, compute how many "R" (units of risk = SL distance)
the trade made before the time barrier or first SL hit.

Two variants:
  1. R_realized: assume we hold to first TP/SL/timeout (matches triple-barrier)
  2. R_mfe: maximum favorable excursion in R units within horizon
            (captures "how good could it have been")

R-multiple captures magnitude:
  +2.5R = winner that hit 2.5x the risk
  -1.0R = stopped out at 1R
  +0.0R = barely moved
  -0.3R = closed at small loss before SL

Use as continuous regression target instead of binary 0/1 — the model
learns to predict ROUND TRIP MAGNITUDE, not just direction.

Encoding for direction='short' is handled internally (sign flip on returns).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Literal


def r_multiple_labels(
    df: pd.DataFrame,
    direction: Literal["long", "short", "both"] = "long",
    sl_atr: float = 1.0,
    max_horizon_bars: int = 48,
    atr_col: str = "atr",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    Compute R-multiple labels for every bar.

    Returns DataFrame with columns:
      - r_realized: R earned by holding to SL hit or timeout (no TP cap)
      - r_mfe:      maximum favorable excursion in R within horizon
      - r_mae:      maximum adverse excursion in R (always negative)
      - bars_to_sl: bars until SL hit (0 if never hit)

    For 'both' direction, returns columns r_realized_long, r_realized_short, etc.
    """
    if direction == "both":
        long_r = r_multiple_labels(
            df, "long", sl_atr, max_horizon_bars,
            atr_col, high_col, low_col, close_col,
        )
        short_r = r_multiple_labels(
            df, "short", sl_atr, max_horizon_bars,
            atr_col, high_col, low_col, close_col,
        )
        return pd.DataFrame({
            "r_realized_long": long_r["r_realized"],
            "r_mfe_long": long_r["r_mfe"],
            "r_mae_long": long_r["r_mae"],
            "bars_to_sl_long": long_r["bars_to_sl"],
            "r_realized_short": short_r["r_realized"],
            "r_mfe_short": short_r["r_mfe"],
            "r_mae_short": short_r["r_mae"],
            "bars_to_sl_short": short_r["bars_to_sl"],
        }, index=df.index)

    n = len(df)
    closes = df[close_col].values
    highs = df[high_col].values
    lows = df[low_col].values
    atrs = df[atr_col].values

    r_realized = np.zeros(n, dtype=np.float32)
    r_mfe = np.zeros(n, dtype=np.float32)
    r_mae = np.zeros(n, dtype=np.float32)
    bars_to_sl = np.zeros(n, dtype=np.int32)

    sign = 1 if direction == "long" else -1

    for i in range(n - 1):
        entry = closes[i]
        atr = atrs[i]
        if not np.isfinite(atr) or atr <= 0:
            continue
        risk = sl_atr * atr  # 1R in price units
        sl_price = entry - sign * risk

        horizon_end = min(i + 1 + max_horizon_bars, n)
        max_fav = 0.0
        max_adv = 0.0
        sl_hit_bar = 0
        sl_hit = False

        for j in range(i + 1, horizon_end):
            high_j = highs[j]
            low_j = lows[j]

            if direction == "long":
                fav_excursion = (high_j - entry) / risk  # in R
                adv_excursion = (low_j - entry) / risk
                if low_j <= sl_price and not sl_hit:
                    sl_hit = True
                    sl_hit_bar = j - i
            else:
                fav_excursion = (entry - low_j) / risk
                adv_excursion = (entry - high_j) / risk
                if high_j >= sl_price and not sl_hit:
                    sl_hit = True
                    sl_hit_bar = j - i

            max_fav = max(max_fav, fav_excursion)
            max_adv = min(max_adv, adv_excursion)

            if sl_hit:
                break

        if sl_hit:
            r_realized[i] = -1.0  # stopped out at exactly 1R loss (assumption)
        else:
            # Hold to timeout — R = (final_close - entry) / risk
            final_close = closes[horizon_end - 1]
            r_realized[i] = sign * (final_close - entry) / risk

        r_mfe[i] = max_fav
        r_mae[i] = max_adv
        bars_to_sl[i] = sl_hit_bar

    return pd.DataFrame({
        "r_realized": r_realized,
        "r_mfe": r_mfe,
        "r_mae": r_mae,
        "bars_to_sl": bars_to_sl,
    }, index=df.index)
