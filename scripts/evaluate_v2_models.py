#!/usr/bin/env python3
"""
evaluate_v2_models.py — Inspect trained v2 models: feature importance,
prediction distribution, sample-level predictions vs actuals.

Usage:
    python scripts/evaluate_v2_models.py
    python scripts/evaluate_v2_models.py --tf 5min --years 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

MODELS_V2 = Path("models/v2")
WAREHOUSE = Path("data/historical")


def load_features_with_labels(tf: str = "5min", years: int = 1) -> pd.DataFrame:
    from src.analysis.features_v2 import compute_features_v2
    from src.learning.labels import r_multiple_labels

    p = WAREHOUSE / "XAU_USD" / f"{tf}.parquet"
    df = pd.read_parquet(p)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=years * 365)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)
    df = df.set_index("datetime")
    features = compute_features_v2(df)
    long_lbl = r_multiple_labels(features, direction="long")
    short_lbl = r_multiple_labels(features, direction="short")
    features["target_r_long"] = long_lbl["r_realized"].values
    features["target_r_short"] = short_lbl["r_realized"].values
    return features


def evaluate_xgb(direction: str, features: pd.DataFrame) -> dict:
    import xgboost as xgb
    from sklearn.metrics import mean_squared_error, r2_score
    p = MODELS_V2 / f"xau_{direction}_xgb_v2.json"
    meta_p = MODELS_V2 / f"xau_{direction}_xgb_v2.meta.json"
    if not p.exists():
        return {"error": f"{p} not found"}

    with open(meta_p) as f:
        meta = json.load(f)
    feature_cols = meta["feature_cols"]

    model = xgb.XGBRegressor()
    model.load_model(str(p))

    X = features[feature_cols].values
    y = features[f"target_r_{direction}"].values
    mask = ~np.isnan(y)
    X = X[mask]
    y = y[mask]

    pred = model.predict(X)
    mse = mean_squared_error(y, pred)
    r2 = r2_score(y, pred)
    pred_mean = float(pred.mean())
    pred_std = float(pred.std())
    actual_mean = float(y.mean())
    actual_std = float(y.std())

    # Top 10 features by importance
    imp = model.feature_importances_
    top_idx = np.argsort(imp)[-10:][::-1]
    top_features = [(feature_cols[i], float(imp[i])) for i in top_idx]

    # Buckets: pred > 0.5R, pred 0-0.5R, pred negative
    high_conf = pred > 0.5
    n_high = int(high_conf.sum())
    if n_high > 0:
        actual_when_high = float(y[high_conf].mean())
        wr_when_high = float((y[high_conf] > 0).mean())
    else:
        actual_when_high = 0.0
        wr_when_high = 0.0

    return {
        "direction": direction,
        "n_samples": int(len(X)),
        "mse": float(mse),
        "r2": float(r2),
        "pred_mean": pred_mean,
        "pred_std": pred_std,
        "actual_mean": actual_mean,
        "actual_std": actual_std,
        "n_high_conf_pred": n_high,
        "actual_R_when_high_conf": actual_when_high,
        "wr_when_high_conf": wr_when_high,
        "top_features": top_features,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5min")
    ap.add_argument("--years", type=int, default=1)
    args = ap.parse_args()

    print(f"Loading XAU {args.tf} for {args.years}y...")
    features = load_features_with_labels(tf=args.tf, years=args.years)
    print(f"Features: {len(features)} rows")
    print()

    for d in ("long", "short"):
        print("=" * 60)
        print(f"XGB {d.upper()}")
        print("=" * 60)
        r = evaluate_xgb(d, features)
        if "error" in r:
            print(f"  {r['error']}")
            continue
        print(f"  Samples:                   {r['n_samples']}")
        print(f"  MSE:                       {r['mse']:.4f}")
        print(f"  R²:                        {r['r2']:.4f}")
        print(f"  Pred mean / std:           {r['pred_mean']:+.3f} / {r['pred_std']:.3f}")
        print(f"  Actual mean / std:         {r['actual_mean']:+.3f} / {r['actual_std']:.3f}")
        print(f"  N high-conf preds (>0.5R): {r['n_high_conf_pred']} "
              f"({r['n_high_conf_pred']/r['n_samples']*100:.1f}%)")
        print(f"  Actual R when high-conf:   {r['actual_R_when_high_conf']:+.3f}")
        print(f"  WR when high-conf:         {r['wr_when_high_conf']*100:.1f}%")
        print(f"  Top 10 features:")
        for fname, imp in r["top_features"]:
            print(f"    {fname:30s}: {imp:.4f}")
        print()


if __name__ == "__main__":
    main()
