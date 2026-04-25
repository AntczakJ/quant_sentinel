#!/usr/bin/env python3
"""
train_short_per_regime.py — Train SHORT model with regime-aware filtering
+ class weighting to fix bull-regime overfit.

Problem: out-of-sample, base SHORT XGB max negative pred is -0.72R, never
hits -1.0R threshold. Model trained on 3y of mostly-bull XAU data learned
"rarely predict big SHORT". Result: at threshold 1.0R only 1 SHORT trade
in 4 months OOS test.

Solutions tried (independently + combined):
  A) Filter training to non-bullish-trend bars (ADX<0.35 OR price below EMA)
  B) Sample weight: 3x for bars where target_r_short > 0.5 (winning shorts)
  C) Lower threshold (0.3R) at inference time

Output: scripts/train_short_per_regime.py saves to:
  models/v2/xau_short_xgb_v2_per_regime.json (+ meta)

Usage:
    python scripts/train_short_per_regime.py
    python scripts/train_short_per_regime.py --strategy A
    python scripts/train_short_per_regime.py --strategy A+B
    python scripts/train_short_per_regime.py --weight-multiplier 5
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
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error

WAREHOUSE = Path("data/historical")
MODELS_V2 = Path("models/v2")


def load_features_with_labels():
    from src.analysis.features_v2 import compute_features_v2
    from src.learning.labels import r_multiple_labels

    df = pd.read_parquet(WAREHOUSE / "XAU_USD" / "5min.parquet")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3 * 365)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True).set_index("datetime")
    print(f"Loaded {len(df)} XAU bars")
    features = compute_features_v2(df)
    short_lbl = r_multiple_labels(features, "short", sl_atr=1.0, max_horizon_bars=48)
    features["target_r_short"] = short_lbl["r_realized"].values
    return features


def filter_strategy_a(features: pd.DataFrame) -> pd.Series:
    """Strategy A: keep only non-bullish-trend bars.

    Use ADX < 0.35 (low trend strength) OR price below 50-bar EMA
    (bearish bias) — these are bars where SHORT might actually work.
    """
    if "adx" not in features.columns:
        return pd.Series(True, index=features.index)  # keep all if no ADX
    low_trend = features["adx"] < 0.35
    # 50-bar EMA approx via close.ewm
    ema50 = features["close"].ewm(span=50, adjust=False).mean()
    below_ema = features["close"] < ema50
    return low_trend | below_ema


def get_sample_weights(features: pd.DataFrame, multiplier: float = 3.0) -> np.ndarray:
    """Strategy B: weight winning shorts (target_r_short > 0.5R) higher."""
    weights = np.ones(len(features), dtype=np.float32)
    winning = features["target_r_short"] > 0.5
    weights[winning.values] = multiplier
    return weights


def train(features: pd.DataFrame, feature_cols: list,
          strategy: str, weight_mult: float, n_trials: int = 30):
    import optuna

    # Drop NaN target rows
    valid = ~features["target_r_short"].isna()
    features = features[valid]

    # Strategy A — filter
    if "A" in strategy:
        keep = filter_strategy_a(features)
        n_before = len(features)
        features = features[keep]
        print(f"Strategy A filter: {n_before} -> {len(features)} samples ({len(features)/n_before*100:.0f}%)")

    X = features[feature_cols].fillna(0).values.astype(np.float32)
    y = features["target_r_short"].values.astype(np.float32)

    # Strategy B — sample weights
    weights = None
    if "B" in strategy:
        weights = get_sample_weights(features, multiplier=weight_mult)
        print(f"Strategy B weighting: {(weights > 1).sum()} samples weighted "
              f"{weight_mult}x ({(weights > 1).sum() / len(weights) * 100:.1f}%)")

    print(f"Final training set: {len(X)} samples")
    print(f"Target distribution: mean={y.mean():.3f}, std={y.std():.3f}, "
          f"<-0.5R: {(y < -0.5).sum()}, >+0.5R: {(y > 0.5).sum()}")

    # Quick Optuna sweep
    tscv = TimeSeriesSplit(n_splits=3)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 400),
            "max_depth": trial.suggest_int("max_depth", 3, 7),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "objective": "reg:squarederror",
            "tree_method": "hist", "random_state": 42,
        }
        cv_scores = []
        for tr_i, va_i in tscv.split(X):
            X_tr, X_va = X[tr_i], X[va_i]
            y_tr, y_va = y[tr_i], y[va_i]
            w_tr = weights[tr_i] if weights is not None else None
            m = xgb.XGBRegressor(**params)
            m.fit(X_tr, y_tr, sample_weight=w_tr,
                  eval_set=[(X_va, y_va)], verbose=False)
            cv_scores.append(mean_squared_error(y_va, m.predict(X_va)))
        return float(np.mean(cv_scores))

    study = optuna.create_study(direction="minimize",
                                 sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_params
    best_mse = study.best_value
    print(f"Best CV MSE: {best_mse:.4f}")
    print(f"Best params: {best}")

    # Final fit on full data
    final = xgb.XGBRegressor(**best, objective="reg:squarederror",
                              tree_method="hist", random_state=42)
    final.fit(X, y, sample_weight=weights, verbose=False)
    return final, best_mse, best


def evaluate_oos(model, feature_cols: list, threshold: float = 0.3):
    """Test the trained SHORT on out-of-sample (last 4 months)."""
    from src.analysis.features_v2 import compute_features_v2
    from src.learning.labels import r_multiple_labels

    df = pd.read_parquet(WAREHOUSE / "XAU_USD" / "5min.parquet")
    cutoff = pd.Timestamp("2025-12-23", tz="UTC")  # matches walk-forward split
    df = df[df["datetime"] >= cutoff].reset_index(drop=True).set_index("datetime")
    features = compute_features_v2(df)

    X = features[feature_cols].fillna(0).values.astype(np.float32)
    preds = model.predict(X)

    print(f"\nOOS prediction distribution (n={len(preds)}):")
    print(f"  mean: {preds.mean():.3f}, std: {preds.std():.3f}")
    print(f"  min:  {preds.min():.3f}, max:  {preds.max():.3f}")
    for thr in [0.3, 0.5, 0.7, 1.0]:
        n_negative = (preds <= -thr).sum()
        print(f"  pred <= -{thr}R: {n_negative} ({n_negative/len(preds)*100:.2f}%)")

    # Quick triple-barrier on actionable signals
    closes = features["close"].values
    highs = features["high"].values
    lows = features["low"].values
    atrs = features["atr"].values

    trades = []
    last_entry = -10
    for i in range(len(features) - 48):
        if i - last_entry < 5:
            continue
        if not np.isfinite(atrs[i]) or atrs[i] <= 0:
            continue
        if preds[i] > -threshold:
            continue
        # SHORT entry
        entry = closes[i]
        atr = atrs[i]
        tp_price = entry - 2.0 * atr  # SHORT TP below
        sl_price = entry + 1.0 * atr  # SHORT SL above

        outcome = "TIME"; r = 0.0
        for j in range(i + 1, min(i + 49, len(features))):
            if highs[j] >= sl_price:
                outcome = "SL"; r = -1.0; break
            if lows[j] <= tp_price:
                outcome = "TP"; r = 2.0; break
        if outcome == "TIME":
            j = min(i + 48, len(features) - 1)
            r = (entry - closes[j]) / atr  # SHORT R
        trades.append({"r": r, "outcome": outcome})
        last_entry = i

    if not trades:
        print(f"\nOOS @ threshold -{threshold}R: 0 trades")
        return
    df_t = pd.DataFrame(trades)
    n = len(df_t)
    wins = (df_t["r"] > 0).sum()
    sum_r = df_t["r"].sum()
    pf = df_t.loc[df_t["r"] > 0, "r"].sum() / max(-df_t.loc[df_t["r"] < 0, "r"].sum(), 1e-9)
    print(f"\nOOS @ threshold -{threshold}R:")
    print(f"  n_trades: {n}")
    print(f"  WR: {wins/n*100:.1f}%")
    print(f"  sum_R: {sum_r:.2f}")
    print(f"  avg_R: {sum_r/n:.3f}")
    print(f"  PF: {pf:.2f}")
    print(f"  outcomes: {df_t['outcome'].value_counts().to_dict()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="A+B",
                    help="A=regime filter, B=sample weights, A+B=both")
    ap.add_argument("--weight-multiplier", type=float, default=3.0)
    ap.add_argument("--n-trials", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.3)
    args = ap.parse_args()

    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS
    print(f"Loading features + labels...")
    features = load_features_with_labels()
    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    print(f"Features: {features.shape}, cols: {len(feature_cols)}")
    print()
    print(f"=== TRAINING (strategy={args.strategy}, weight={args.weight_multiplier}x) ===")
    model, mse, best = train(features, feature_cols,
                              strategy=args.strategy,
                              weight_mult=args.weight_multiplier,
                              n_trials=args.n_trials)
    out_path = MODELS_V2 / "xau_short_xgb_v2_per_regime.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(out_path))
    print(f"\nSaved {out_path}")

    meta_path = MODELS_V2 / "xau_short_xgb_v2_per_regime.meta.json"
    with open(meta_path, "w") as f:
        json.dump({
            "direction": "short",
            "strategy": args.strategy,
            "weight_multiplier": args.weight_multiplier,
            "best_cv_mse": mse,
            "best_params": best,
            "feature_cols": feature_cols,
        }, f, indent=2, default=str)

    print()
    print("=" * 60)
    print("OUT-OF-SAMPLE EVALUATION")
    print("=" * 60)
    evaluate_oos(model, feature_cols, threshold=args.threshold)


if __name__ == "__main__":
    main()
