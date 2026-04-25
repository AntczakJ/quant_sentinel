#!/usr/bin/env python3
"""
test_shadow_pipeline.py — End-to-end test of shadow mode pipeline.

Simulates 2 weeks of shadow predictions (using v2 models on warehouse data)
then runs compare_v1_v2_shadow.py to validate the full evaluation flow.

This proves the pipeline works BEFORE real shadow data accumulates Mon onwards.

Usage:
    python scripts/test_shadow_pipeline.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import xgboost as xgb
import numpy as np

WAREHOUSE = Path("data/historical")
MODELS_V2 = Path("models/v2")
SHADOW_LOG_BACKUP = Path("data/shadow_predictions_real.jsonl.bak")
SHADOW_LOG = Path("data/shadow_predictions.jsonl")
SHADOW_LOG_TEST = Path("data/shadow_predictions_synthetic.jsonl")


def main():
    # Load v2 models
    long_m = xgb.XGBRegressor()
    long_m.load_model(str(MODELS_V2 / "xau_long_xgb_v2.json"))
    short_m = xgb.XGBRegressor()
    short_m.load_model(str(MODELS_V2 / "xau_short_xgb_v2.json"))
    with open(MODELS_V2 / "xau_long_xgb_v2.meta.json") as f:
        meta = json.load(f)
    feature_cols = meta["feature_cols"]

    # Load XAU 5min (last 14 days = 2 weeks worth of bars)
    from src.analysis.features_v2 import compute_features_v2
    df = pd.read_parquet(WAREHOUSE / "XAU_USD" / "5min.parquet")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True).set_index("datetime")
    print(f"Loaded {len(df)} bars (last 14 days)")
    features = compute_features_v2(df)

    # Simulate shadow predictions every 5min (i.e. every bar)
    X = features[feature_cols].fillna(0).values.astype(np.float32)
    long_preds = long_m.predict(X)
    short_preds = short_m.predict(X)

    # Backup any existing shadow log
    if SHADOW_LOG.exists():
        SHADOW_LOG.rename(SHADOW_LOG_BACKUP)
        print(f"Backed up existing shadow log -> {SHADOW_LOG_BACKUP}")

    SHADOW_LOG.parent.mkdir(exist_ok=True)
    n_actionable = 0
    with open(SHADOW_LOG, "w") as f:
        for i, ts in enumerate(features.index):
            long_r = float(long_preds[i])
            short_r = float(short_preds[i])
            if long_r >= 0.3 and long_r > -short_r:
                v2_signal = "LONG"
            elif short_r <= -0.3 and -short_r > long_r:
                v2_signal = "SHORT"
                n_actionable += 1
            else:
                v2_signal = "WAIT"
            if v2_signal != "WAIT":
                n_actionable += (1 if v2_signal == "LONG" else 0)

            record = {
                "ts": ts.isoformat(),
                "tf": "5m",
                "v1_signal": "WAIT",
                "v1_score": None,
                "v2_long_r_pred": long_r,
                "v2_short_r_pred": short_r,
                "v2_signal": v2_signal,
                "v2_confidence": max(abs(long_r), abs(short_r)),
                "price": float(features["close"].iloc[i]),
                "atr": float(features["atr"].iloc[i]) if "atr" in features.columns else None,
                "models_loaded": ["xgb_long", "xgb_short"],
            }
            f.write(json.dumps(record, default=str) + "\n")

    n_records = len(features)
    print(f"Wrote {n_records} synthetic shadow predictions, {n_actionable} actionable")
    print(f"File: {SHADOW_LOG}")

    # Run comparison
    print("\n" + "=" * 60)
    print("Running compare_v1_v2_shadow.py on synthetic data...")
    print("=" * 60)
    import subprocess
    result = subprocess.run(
        [".venv/Scripts/python.exe", "scripts/compare_v1_v2_shadow.py",
         "--horizon-bars", "12"],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-500:])

    # Restore real shadow log if any
    if SHADOW_LOG_BACKUP.exists():
        SHADOW_LOG.rename(SHADOW_LOG_TEST)
        SHADOW_LOG_BACKUP.rename(SHADOW_LOG)
        print(f"\nRestored real shadow log; synthetic moved to {SHADOW_LOG_TEST}")
    else:
        SHADOW_LOG.rename(SHADOW_LOG_TEST)
        print(f"\nSynthetic moved to {SHADOW_LOG_TEST} (no prior real log)")


if __name__ == "__main__":
    main()
