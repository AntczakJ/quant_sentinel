#!/usr/bin/env python3
"""
walk_forward_v2.py — Honest out-of-sample test of v2 XGB models.

Splits 3-year warehouse data into:
  - Train: first 90% (chronological)
  - Test:  last 10% (truly unseen by model)

Trains XGB v2 (long+short) on train portion ONLY, then runs triple-barrier
backtest on test portion. This eliminates the in-sample bias that makes
'evaluate_v2_models.py' / 'backtest_v2_simple.py' look better than they
really are (those evaluate on data the model trained on).

Output: PF, WR, avg_R per direction on TRULY out-of-sample data.

Usage:
    python scripts/walk_forward_v2.py
    python scripts/walk_forward_v2.py --tf 5min --threshold 0.5 --train-pct 0.9
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd
import xgboost as xgb

WAREHOUSE = Path("data/historical")


def load_features(tf: str = "5min", years: int = 3) -> pd.DataFrame:
    from src.analysis.features_v2 import compute_features_v2
    p = WAREHOUSE / "XAU_USD" / f"{tf}.parquet"
    df = pd.read_parquet(p)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=years * 365)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True).set_index("datetime")
    print(f"Loaded {len(df)} XAU {tf} bars")
    features = compute_features_v2(df)
    return features


def add_r_labels(features: pd.DataFrame, sl_atr: float = 1.0, max_horizon: int = 48):
    from src.learning.labels import r_multiple_labels
    long_lbl = r_multiple_labels(features, "long", sl_atr=sl_atr, max_horizon_bars=max_horizon)
    short_lbl = r_multiple_labels(features, "short", sl_atr=sl_atr, max_horizon_bars=max_horizon)
    features = features.copy()
    features["target_r_long"] = long_lbl["r_realized"].values
    features["target_r_short"] = short_lbl["r_realized"].values
    return features


def train_xgb_simple(X, y, params=None) -> xgb.XGBRegressor:
    """Quick XGB train, no Optuna — uses sensible defaults from quick training."""
    if params is None:
        params = dict(
            n_estimators=200, max_depth=4, learning_rate=0.02,
            subsample=0.85, colsample_bytree=0.85, min_child_weight=6,
        )
    m = xgb.XGBRegressor(
        **params, objective="reg:squarederror",
        tree_method="hist", random_state=42,
    )
    m.fit(X, y, verbose=False)
    return m


def simulate_trades(
    features: pd.DataFrame, long_preds, short_preds,
    threshold: float, cooldown_bars: int,
    tp_atr: float = 2.0, sl_atr: float = 1.0, max_horizon: int = 48,
):
    trades = []
    last_entry = -cooldown_bars - 1
    closes = features["close"].values
    highs = features["high"].values
    lows = features["low"].values
    atrs = features["atr"].values

    for i in range(len(features) - max_horizon):
        if i - last_entry < cooldown_bars:
            continue
        atr = atrs[i]
        if not np.isfinite(atr) or atr <= 0:
            continue
        long_r = long_preds[i]
        short_r = short_preds[i]

        # CONVENTION fix 2026-04-25: r_multiple_labels(direction='short')
        # returns POSITIVE R when SHORT wins (internal sign flip).
        # SHORT entry = positive short_r prediction (NOT <= -threshold).
        if long_r >= threshold and long_r > short_r:
            direction = "LONG"
        elif short_r >= threshold and short_r > long_r:
            direction = "SHORT"
        else:
            continue

        entry = closes[i]
        sign = 1 if direction == "LONG" else -1
        tp_price = entry + sign * tp_atr * atr
        sl_price = entry - sign * sl_atr * atr

        outcome = "TIME"
        r_realized = 0.0
        for j in range(i + 1, min(i + 1 + max_horizon, len(features))):
            if direction == "LONG":
                hit_sl = lows[j] <= sl_price
                hit_tp = highs[j] >= tp_price
            else:
                hit_sl = highs[j] >= sl_price
                hit_tp = lows[j] <= tp_price
            if hit_sl and hit_tp:
                outcome = "SL"; r_realized = -1.0; break
            if hit_sl:
                outcome = "SL"; r_realized = -1.0; break
            if hit_tp:
                outcome = "TP"; r_realized = tp_atr; break
        if outcome == "TIME":
            j = min(i + max_horizon, len(features) - 1)
            r_realized = sign * (closes[j] - entry) / (sl_atr * atr)

        trades.append({
            "ts": features.index[i], "direction": direction,
            "entry": float(entry), "outcome": outcome,
            "r_realized": float(r_realized),
            "long_pred": float(long_r), "short_pred": float(short_r),
        })
        last_entry = i

    return trades


def aggregate(trades):
    if not trades:
        return {"error": "no trades"}
    df = pd.DataFrame(trades)
    n = len(df)
    wins = (df["r_realized"] > 0).sum()
    losses = (df["r_realized"] < 0).sum()
    wr = wins / n * 100
    sum_r = df["r_realized"].sum()
    sum_win = df.loc[df["r_realized"] > 0, "r_realized"].sum()
    sum_loss = -df.loc[df["r_realized"] < 0, "r_realized"].sum()
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")

    cumr = df["r_realized"].cumsum()
    peak = cumr.cummax()
    max_dd = float((cumr - peak).min())

    per_dir = {}
    for d in ("LONG", "SHORT"):
        sub = df[df["direction"] == d]
        if len(sub):
            per_dir[d] = {
                "n": len(sub),
                "wr": float((sub["r_realized"] > 0).sum() / len(sub) * 100),
                "sum_r": float(sub["r_realized"].sum()),
                "avg_r": float(sub["r_realized"].mean()),
            }
        else:
            per_dir[d] = {"n": 0}
    return {
        "n_trades": int(n), "wins": int(wins), "losses": int(losses),
        "wr_pct": float(wr), "sum_r": float(sum_r),
        "avg_r": float(sum_r / n), "profit_factor": float(pf),
        "max_dd_R": max_dd, "per_direction": per_dir,
        "outcome_counts": df["outcome"].value_counts().to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5min")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--train-pct", type=float, default=0.85)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--cooldown-bars", type=int, default=5)
    args = ap.parse_args()

    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS
    print(f"Loading data + computing features...")
    features = load_features(tf=args.tf, years=args.years)
    print(f"Adding R-multiple labels...")
    features = add_r_labels(features)

    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    n_total = len(features)
    split_idx = int(n_total * args.train_pct)
    train = features.iloc[:split_idx].copy()
    test = features.iloc[split_idx:].copy()
    print(f"Train: {len(train)} rows ({train.index[0]} -> {train.index[-1]})")
    print(f"Test:  {len(test)} rows ({test.index[0]} -> {test.index[-1]})")

    # Drop rows with NaN target (warmup, end-of-data)
    train_long = train.dropna(subset=["target_r_long"])
    train_short = train.dropna(subset=["target_r_short"])
    X_long_train = train_long[feature_cols].fillna(0).values.astype(np.float32)
    y_long_train = train_long["target_r_long"].values.astype(np.float32)
    X_short_train = train_short[feature_cols].fillna(0).values.astype(np.float32)
    y_short_train = train_short["target_r_short"].values.astype(np.float32)

    print(f"\nTraining XGB long ({len(X_long_train)} samples)...")
    long_m = train_xgb_simple(X_long_train, y_long_train)
    print(f"Training XGB short ({len(X_short_train)} samples)...")
    short_m = train_xgb_simple(X_short_train, y_short_train)

    # Predict on test
    X_test = test[feature_cols].fillna(0).values.astype(np.float32)
    long_preds = long_m.predict(X_test)
    short_preds = short_m.predict(X_test)

    print(f"\nSimulating trades on test set (threshold={args.threshold}R)...")
    trades = simulate_trades(
        test, long_preds, short_preds,
        threshold=args.threshold, cooldown_bars=args.cooldown_bars,
    )
    result = aggregate(trades)

    print()
    print("=" * 60)
    print(f"WALK-FORWARD V2 (TRUE OUT-OF-SAMPLE)")
    print(f"Train: {len(train)} rows | Test: {len(test)} rows")
    print(f"Threshold: {args.threshold}R | Cooldown: {args.cooldown_bars}bars")
    print("=" * 60)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return
    for k, v in result.items():
        if k in ("per_direction", "outcome_counts"):
            print(f"  {k}:")
            for k2, v2 in v.items():
                print(f"    {k2}: {v2}")
        elif isinstance(v, float):
            print(f"  {k:25s}: {v:.4f}")
        else:
            print(f"  {k:25s}: {v}")

    # Save result
    Path("docs").mkdir(exist_ok=True)
    out_path = f"docs/walk_forward_v2_{args.tf}_thr{args.threshold}.json"
    with open(out_path, "w") as f:
        json.dump({"args": vars(args), "result": result,
                   "train_n": len(train), "test_n": len(test)},
                  f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
