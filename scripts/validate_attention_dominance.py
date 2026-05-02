"""
validate_attention_dominance.py — read-only A/B comparison of ensemble
direction split with current vs rebalanced weights on warehouse 5m XAU.

Hypothesis: attention voter (44.4% effective weight, walk-forward acc
0.575) dominates fusion → LONG-bias against bear bars. Rebalancing to
xgb/lstm-heavy should produce more SHORT votes in a falling regime.

Validates by:
1. Sampling last 7 days of 5m XAU bars from warehouse
2. Computing per-voter raw output for each bar
3. Combining with weights_A (current DB) vs weights_B (rebalanced)
4. Reporting direction split (LONG/SHORT/CZEKAJ) for each scheme

DOES NOT touch live DB, models, or API. DOES NOT trade.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Suppress logfire warning
os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

# Need ONNX for attention/xgb on Windows DirectML
from src.ml.ensemble_models import get_ensemble_prediction


def main():
    # Load warehouse 5m XAU
    parquet = REPO / "data" / "historical" / "XAU_USD" / "5min.parquet"
    if not parquet.exists():
        print(f"ERR: warehouse miss {parquet}")
        return 1
    df = pd.read_parquet(parquet)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)

    # Last 7 calendar days of bars (skip weekend gaps)
    cutoff = df["datetime"].max() - pd.Timedelta(days=7)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)
    print(f"Loaded {len(df)} bars from {df['datetime'].min()} -> {df['datetime'].max()}")

    # Sample every 10 bars (every 50min) so we don't run 2000 inferences
    sample = df.iloc[::10].reset_index(drop=True)
    print(f"Sampling every 10 bars → {len(sample)} probe points")

    weights_current = {
        "smc": 0.05, "attention": 0.20, "lstm": 0.05, "xgb": 0.05,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    }
    weights_rebalanced = {
        "smc": 0.05, "attention": 0.10, "lstm": 0.15, "xgb": 0.20,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    }

    counts_a = {"LONG": 0, "SHORT": 0, "CZEKAJ": 0, "NEUTRAL": 0}
    counts_b = {"LONG": 0, "SHORT": 0, "CZEKAJ": 0, "NEUTRAL": 0}

    n = 0
    for i in range(50, len(sample)):  # skip warmup
        slice_df = df[df["datetime"] <= sample.iloc[i]["datetime"]].tail(200).copy()
        if len(slice_df) < 50:
            continue
        try:
            # Derive smc_trend from the slice (last EMA20 vs price)
            last = slice_df.iloc[-1]
            ema20 = slice_df["close"].ewm(span=20).mean().iloc[-1]
            trend = "bull" if last["close"] > ema20 else "bear"
            cur_price = float(last["close"])
            res_a = get_ensemble_prediction(
                df=slice_df, smc_trend=trend, current_price=cur_price,
                weights=weights_current, use_twelve_data=False
            )
            res_b = get_ensemble_prediction(
                df=slice_df, smc_trend=trend, current_price=cur_price,
                weights=weights_rebalanced, use_twelve_data=False
            )
        except Exception as e:
            print(f"[{i}] Error: {e}")
            continue
        sa = res_a.get("ensemble_signal", "?")
        sb = res_b.get("ensemble_signal", "?")
        counts_a[sa] = counts_a.get(sa, 0) + 1
        counts_b[sb] = counts_b.get(sb, 0) + 1
        n += 1
        if n % 20 == 0:
            print(f"  [{n}] A={counts_a} B={counts_b}")
        if n >= 100:  # cap probes to keep it fast
            break

    print()
    print("=" * 60)
    print(f"PROBE POINTS: {n}")
    print(f"WINDOW: last 7 days of 5m XAU warehouse")
    print()
    print(f"WEIGHTS A (current — attention=0.20):  {counts_a}")
    print(f"WEIGHTS B (rebalanced — xgb=0.20):    {counts_b}")
    print()
    if counts_a.get("SHORT", 0) == 0 and counts_b.get("SHORT", 0) > 0:
        print("✓ Hypothesis SUPPORTED: rebalanced weights produce SHORT signals where current does not.")
    elif counts_a.get("SHORT", 0) > 0 and counts_b.get("SHORT", 0) > counts_a.get("SHORT", 0):
        print(f"✓ Hypothesis SUPPORTED: SHORT count {counts_a['SHORT']} → {counts_b['SHORT']}.")
    else:
        print(f"✗ Hypothesis NOT supported: SHORT counts equal or B<A.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
