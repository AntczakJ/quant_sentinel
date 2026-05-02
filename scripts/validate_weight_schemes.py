"""
validate_weight_schemes.py — extended multi-scheme weight comparison.

A/B/C/D variants on same 100 probe points (last 7 days warehouse 5m).
All read-only. No DB writes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd

from src.ml.ensemble_models import get_ensemble_prediction


SCHEMES = {
    "A_current": {
        "smc": 0.05, "attention": 0.20, "lstm": 0.05, "xgb": 0.05,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    },
    "B_rebalanced": {
        "smc": 0.05, "attention": 0.10, "lstm": 0.15, "xgb": 0.20,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    },
    "C_smc_zero": {
        "smc": 0.0, "attention": 0.10, "lstm": 0.15, "xgb": 0.20,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    },
    "D_ml_only_attn_low": {
        "smc": 0.0, "attention": 0.05, "lstm": 0.20, "xgb": 0.25,
        "dqn": 0.05, "deeptrans": 0.05, "v2_xgb": 0.0,
    },
}


def main() -> int:
    parquet = REPO / "data" / "historical" / "XAU_USD" / "5min.parquet"
    if not parquet.exists():
        print(f"ERR: warehouse miss {parquet}")
        return 1
    df = pd.read_parquet(parquet)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)

    cutoff = df["datetime"].max() - pd.Timedelta(days=7)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)
    print(f"Loaded {len(df)} bars from {df['datetime'].min()} -> {df['datetime'].max()}")

    sample = df.iloc[::10].reset_index(drop=True)
    print(f"Sampling every 10 bars -> {len(sample)} probe points")

    counts = {name: {"LONG": 0, "SHORT": 0, "CZEKAJ": 0, "NEUTRAL": 0}
              for name in SCHEMES}
    n = 0
    for i in range(50, len(sample)):
        slice_df = df[df["datetime"] <= sample.iloc[i]["datetime"]].tail(200).copy()
        if len(slice_df) < 50:
            continue
        last = slice_df.iloc[-1]
        ema20 = slice_df["close"].ewm(span=20).mean().iloc[-1]
        trend = "bull" if last["close"] > ema20 else "bear"
        cur_price = float(last["close"])
        try:
            for name, weights in SCHEMES.items():
                res = get_ensemble_prediction(
                    df=slice_df, smc_trend=trend, current_price=cur_price,
                    weights=weights, use_twelve_data=False
                )
                sig = res.get("ensemble_signal", "?")
                counts[name][sig] = counts[name].get(sig, 0) + 1
        except Exception as e:
            print(f"[{i}] err: {e}")
            continue
        n += 1
        if n % 25 == 0:
            print(f"  [{n}] " + " | ".join(
                f"{name}={c}" for name, c in counts.items()
            ))
        if n >= 100:
            break

    print()
    print("=" * 78)
    print(f"SCHEMES tested over {n} probe points (last 7 days warehouse 5m)")
    print("=" * 78)
    print(f"{'scheme':24} {'LONG':>5} {'SHORT':>6} {'CZEKAJ':>7} {'decisive%':>11}")
    for name, c in counts.items():
        decisive = c.get("LONG", 0) + c.get("SHORT", 0)
        pct = (decisive / max(n, 1)) * 100
        print(f"{name:24} {c['LONG']:>5} {c['SHORT']:>6} {c['CZEKAJ']:>7} {pct:>10.1f}%")
    print()

    # Direction balance per scheme
    print("Direction balance (SHORT / total decisive):")
    for name, c in counts.items():
        decisive = c.get("LONG", 0) + c.get("SHORT", 0)
        if decisive == 0:
            print(f"  {name}: no decisive signals")
            continue
        short_pct = (c.get("SHORT", 0) / decisive) * 100
        print(f"  {name}: {short_pct:.1f}% SHORT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
