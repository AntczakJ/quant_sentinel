#!/usr/bin/env python3
"""
train_v2.py — Per-direction model training pipeline (Phase 4 of master plan).

Trains 4 separate models:
  - xau_long_xgb_v2:    XGBoost regressor predicting LONG R-multiple
  - xau_short_xgb_v2:   XGBoost regressor predicting SHORT R-multiple
  - xau_long_lstm_v2:   LSTM regressor predicting LONG R-multiple
  - xau_short_lstm_v2:  LSTM regressor predicting SHORT R-multiple

Key differences from train_all.py:
  1. Reads from data warehouse (parquet) — fast, deterministic, NO API
  2. Uses features_v2 (cross-asset + multi-TF — ~67 features)
  3. R-multiple regression target (not binary classification)
  4. Per-direction models (separate LONG and SHORT)
  5. Optuna hyperparameter sweep with TimeSeriesSplit (proper CV)
  6. Saved to models/v2/ — does NOT touch production v1 models

Usage:
    python scripts/train_v2.py                     # full pipeline
    python scripts/train_v2.py --quick             # 20 trials, fast iteration
    python scripts/train_v2.py --xgb-only          # skip LSTM
    python scripts/train_v2.py --tf 5min           # which TF to use
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Ensure repo root is on path (run from any cwd)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

# Determinism
os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("TF_CUDNN_DETERMINISTIC", "1")
import random as _r; _r.seed(42)
np.random.seed(42)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
logger = logging.getLogger("train_v2")

WAREHOUSE = Path("data/historical")
MODELS_V2_DIR = Path("models/v2")


def load_xau_with_features(tf: str = "5min", years: int = 3) -> pd.DataFrame:
    """Load XAU from warehouse, compute features_v2, drop warmup NaN."""
    from src.analysis.features_v2 import compute_features_v2

    parquet_path = WAREHOUSE / "XAU_USD" / f"{tf}.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Warehouse miss: {parquet_path}. Run "
            "scripts/data_collection/build_data_warehouse.py first."
        )
    df = pd.read_parquet(parquet_path)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=years * 365)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)
    logger.info(f"Loaded {len(df)} rows of XAU {tf}")

    if df.index.name != "datetime":
        df = df.set_index("datetime")

    features = compute_features_v2(df)
    # Drop warmup rows that have NaN in feature columns
    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS
    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    n_before = len(features)
    features = features.dropna(subset=feature_cols).reset_index()
    logger.info(f"After dropna: {len(features)} rows ({n_before - len(features)} dropped warmup)")
    return features


def add_labels(features: pd.DataFrame, sl_atr: float = 1.0,
               tp_atr: float = 2.0, max_horizon: int = 48) -> pd.DataFrame:
    """Add R-multiple labels for both LONG and SHORT."""
    from src.learning.labels import r_multiple_labels

    if "atr" not in features.columns:
        raise ValueError("features must have 'atr' column for label computation")

    long_lbl = r_multiple_labels(
        features, direction="long",
        sl_atr=sl_atr, max_horizon_bars=max_horizon,
    )
    short_lbl = r_multiple_labels(
        features, direction="short",
        sl_atr=sl_atr, max_horizon_bars=max_horizon,
    )
    features["target_r_long"] = long_lbl["r_realized"].values
    features["target_r_short"] = short_lbl["r_realized"].values
    return features


def train_xgb_per_direction(
    features: pd.DataFrame,
    direction: str,
    n_trials: int = 50,
    out_dir: Path = MODELS_V2_DIR,
) -> dict:
    """Train XGBoost regressor for one direction with Optuna + TimeSeriesSplit."""
    import xgboost as xgb
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_squared_error
    try:
        import optuna
    except ImportError:
        logger.warning("optuna not installed, falling back to default hyperparams")
        optuna = None

    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS

    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    X = features[feature_cols].values
    y = features[f"target_r_{direction}"].values

    # Drop rows with NaN in target
    mask = ~np.isnan(y)
    X = X[mask]
    y = y[mask]

    if len(X) < 1000:
        logger.warning(f"Only {len(X)} samples for {direction} XGB — may be unreliable")

    logger.info(f"XGB {direction}: {len(X)} samples, {len(feature_cols)} features")

    tscv = TimeSeriesSplit(n_splits=5)

    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "objective": "reg:squarederror",
            "tree_method": "hist",
            "random_state": 42,
        }
        cv_scores = []
        for train_idx, val_idx in tscv.split(X):
            X_tr, X_val = X[train_idx], X[val_idx]
            y_tr, y_val = y[train_idx], y[val_idx]
            model = xgb.XGBRegressor(**params)
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
            pred = model.predict(X_val)
            cv_scores.append(mean_squared_error(y_val, pred))
        return float(np.mean(cv_scores))

    if optuna:
        study = optuna.create_study(direction="minimize",
                                     sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        best_params = study.best_params
        best_mse = study.best_value
        logger.info(f"XGB {direction} best CV MSE: {best_mse:.4f}")
    else:
        best_params = {
            "n_estimators": 200, "max_depth": 5, "learning_rate": 0.1,
            "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 3,
        }
        best_mse = None

    # Final training on full dataset with best params
    final_model = xgb.XGBRegressor(
        **best_params,
        objective="reg:squarederror", tree_method="hist", random_state=42,
    )
    final_model.fit(X, y, verbose=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"xau_{direction}_xgb_v2.json"
    final_model.save_model(str(model_path))
    logger.info(f"Saved {model_path}")

    # Save metadata
    meta = {
        "direction": direction,
        "feature_cols": feature_cols,
        "n_samples": int(len(X)),
        "best_params": best_params,
        "best_cv_mse": best_mse,
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    meta_path = out_dir / f"xau_{direction}_xgb_v2.meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta


def train_lstm_per_direction(
    features: pd.DataFrame,
    direction: str,
    seq_length: int = 32,
    epochs: int = 50,
    out_dir: Path = MODELS_V2_DIR,
) -> dict:
    """Train LSTM regressor for one direction."""
    import tensorflow as tf
    from tensorflow.keras import Sequential, layers, callbacks

    tf.random.set_seed(42)
    tf.keras.utils.set_random_seed(42)

    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS
    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    X = features[feature_cols].values.astype(np.float32)
    y = features[f"target_r_{direction}"].values.astype(np.float32)

    mask = ~np.isnan(y)
    X = X[mask]
    y = y[mask]

    if len(X) < seq_length + 100:
        logger.warning(f"Insufficient samples ({len(X)}) for LSTM {direction}")
        return {"error": "insufficient_samples"}

    # Build sequences
    Xs, ys = [], []
    for i in range(seq_length, len(X)):
        Xs.append(X[i - seq_length:i])
        ys.append(y[i])
    Xs = np.array(Xs, dtype=np.float32)
    ys = np.array(ys, dtype=np.float32)
    logger.info(f"LSTM {direction}: {len(Xs)} sequences, shape={Xs.shape}")

    # Time-aware train/val split (last 20% as val)
    split = int(len(Xs) * 0.8)
    X_tr, X_val = Xs[:split], Xs[split:]
    y_tr, y_val = ys[:split], ys[split:]

    # Standardize per-feature using train stats only
    mean = X_tr.mean(axis=(0, 1), keepdims=True)
    std = X_tr.std(axis=(0, 1), keepdims=True)
    std = np.where(std < 1e-6, 1.0, std)
    X_tr = (X_tr - mean) / std
    X_val = (X_val - mean) / std

    model = Sequential([
        layers.Input(shape=(seq_length, len(feature_cols))),
        layers.LSTM(64, return_sequences=True),
        layers.Dropout(0.2),
        layers.LSTM(32, return_sequences=False),
        layers.Dropout(0.2),
        layers.Dense(16, activation="relu"),
        layers.Dense(1),  # regression
    ])
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])

    es = callbacks.EarlyStopping(patience=5, restore_best_weights=True)
    history = model.fit(
        X_tr, y_tr, validation_data=(X_val, y_val),
        epochs=epochs, batch_size=64, verbose=0, callbacks=[es],
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / f"xau_{direction}_lstm_v2.keras"
    model.save(str(model_path))
    logger.info(f"Saved {model_path}")

    # Save scaler
    scaler_path = out_dir / f"xau_{direction}_lstm_v2.scaler.npz"
    np.savez(scaler_path, mean=mean, std=std)

    val_pred = model.predict(X_val, verbose=0).flatten()
    val_mse = float(np.mean((val_pred - y_val) ** 2))
    val_mae = float(np.mean(np.abs(val_pred - y_val)))
    logger.info(f"LSTM {direction} val MSE: {val_mse:.4f}, MAE: {val_mae:.4f}")

    meta = {
        "direction": direction,
        "feature_cols": feature_cols,
        "seq_length": seq_length,
        "n_sequences": len(Xs),
        "val_mse": val_mse,
        "val_mae": val_mae,
        "epochs_trained": len(history.history["loss"]),
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    meta_path = out_dir / f"xau_{direction}_lstm_v2.meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="5min")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--quick", action="store_true",
                    help="20 trials + 10 epochs (fast iteration)")
    ap.add_argument("--xgb-only", action="store_true")
    ap.add_argument("--lstm-only", action="store_true")
    ap.add_argument("--directions", default="long,short")
    args = ap.parse_args()

    n_trials = 20 if args.quick else 50
    epochs = 10 if args.quick else 50

    t_start = time.time()
    logger.info("=" * 60)
    logger.info(f"train_v2 START — tf={args.tf} years={args.years} quick={args.quick}")
    logger.info("=" * 60)

    features = load_xau_with_features(tf=args.tf, years=args.years)
    features = add_labels(features)
    logger.info(f"Features+labels ready: {features.shape}")

    directions = [d.strip() for d in args.directions.split(",")]
    summary = {"trained": [], "skipped": []}

    for direction in directions:
        logger.info(f"\n--- DIRECTION: {direction.upper()} ---")
        if not args.lstm_only:
            try:
                meta = train_xgb_per_direction(features, direction, n_trials)
                summary["trained"].append(("xgb", direction, meta.get("best_cv_mse")))
            except Exception as e:
                logger.exception(f"XGB {direction} failed: {e}")
                summary["skipped"].append(("xgb", direction, str(e)))
        if not args.xgb_only:
            try:
                meta = train_lstm_per_direction(features, direction, epochs=epochs)
                summary["trained"].append(("lstm", direction, meta.get("val_mse")))
            except Exception as e:
                logger.exception(f"LSTM {direction} failed: {e}")
                summary["skipped"].append(("lstm", direction, str(e)))

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info(f"train_v2 DONE — {elapsed:.1f}s ({elapsed/60:.1f} min)")
    logger.info("=" * 60)
    logger.info(f"Trained: {len(summary['trained'])}")
    for kind, dir_, score in summary["trained"]:
        logger.info(f"  {kind} {dir_}: score={score}")
    if summary["skipped"]:
        logger.info(f"Skipped: {len(summary['skipped'])}")
        for kind, dir_, err in summary["skipped"]:
            logger.info(f"  {kind} {dir_}: {err}")

    summary_path = MODELS_V2_DIR / "_train_summary.json"
    MODELS_V2_DIR.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        json.dump({
            "elapsed_sec": elapsed,
            "args": vars(args),
            "trained": summary["trained"],
            "skipped": summary["skipped"],
        }, f, indent=2, default=str)
    logger.info(f"Summary written: {summary_path}")


if __name__ == "__main__":
    main()
