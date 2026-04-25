#!/usr/bin/env python3
"""
train_lstm_v2_arch.py — Try alternative architectures vs base LSTM.

Base LSTM (from train_v2.py): LSTM(64) → Dropout → LSTM(32) → Dropout →
Dense(16) → Dense(1). Early-stopped at 6 epochs, val MSE 53.84 (LONG).
Underperformed XGB (val MSE 21.61).

This script trains 3 alternatives and reports best on out-of-sample:
  arch=shallow:  LSTM(32) → Dropout → Dense(16) → Dense(1)
  arch=gru:      GRU(64) → Dropout → GRU(32) → Dropout → Dense(16) → Dense(1)
  arch=conv:     Conv1D(64,3) → Conv1D(32,3) → GlobalMaxPool → Dense(16) → Dense(1)

All use:
  - seq_length: 32 (matches base for fair comparison)
  - sample_weight: 3x for high-magnitude target moves
  - Patience: 10 (more lenient than base 5)
  - AdamW with weight_decay
  - Cosine learning rate schedule
  - Both LONG + SHORT trained per arch

Output: models/v2_lstm_alt/<arch>_<dir>.keras + meta + scalers
        Plus comparison report with OOS metrics

Usage:
    python scripts/train_lstm_v2_arch.py
    python scripts/train_lstm_v2_arch.py --arch gru --epochs 30
    python scripts/train_lstm_v2_arch.py --quick  # 10 epochs fast iteration
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Repo
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Determinism
os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
import random as _r; _r.seed(42)

import numpy as np
import pandas as pd

np.random.seed(42)

WAREHOUSE = Path("data/historical")
MODELS_DIR = Path("models/v2_lstm_alt")


def load_features_and_labels(years: int = 3):
    from src.analysis.features_v2 import compute_features_v2
    from src.learning.labels import r_multiple_labels

    df = pd.read_parquet(WAREHOUSE / "XAU_USD" / "5min.parquet")
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=years * 365)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True).set_index("datetime")
    print(f"Loaded {len(df)} bars")
    features = compute_features_v2(df)
    long_lbl = r_multiple_labels(features, "long")
    short_lbl = r_multiple_labels(features, "short")
    features["target_r_long"] = long_lbl["r_realized"].values
    features["target_r_short"] = short_lbl["r_realized"].values
    return features


def build_arch(arch: str, seq_len: int, n_features: int):
    import tensorflow as tf
    from tensorflow.keras import Sequential, layers, Input

    if arch == "shallow":
        return Sequential([
            Input(shape=(seq_len, n_features)),
            layers.LSTM(32, return_sequences=False),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(1),
        ])
    if arch == "gru":
        return Sequential([
            Input(shape=(seq_len, n_features)),
            layers.GRU(64, return_sequences=True),
            layers.Dropout(0.2),
            layers.GRU(32, return_sequences=False),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(1),
        ])
    if arch == "conv":
        return Sequential([
            Input(shape=(seq_len, n_features)),
            layers.Conv1D(64, 3, activation="relu", padding="same"),
            layers.Conv1D(32, 3, activation="relu", padding="same"),
            layers.GlobalMaxPooling1D(),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(1),
        ])
    if arch == "bilstm":
        return Sequential([
            Input(shape=(seq_len, n_features)),
            layers.Bidirectional(layers.LSTM(32, return_sequences=False)),
            layers.Dropout(0.2),
            layers.Dense(16, activation="relu"),
            layers.Dense(1),
        ])
    raise ValueError(f"Unknown arch: {arch}")


def train_arch(features: pd.DataFrame, feature_cols: list,
               direction: str, arch: str, seq_len: int = 32,
               epochs: int = 30, batch_size: int = 64,
               weight_high_r: float = 3.0):
    import tensorflow as tf
    from tensorflow.keras import callbacks, optimizers

    tf.random.set_seed(42)
    tf.keras.utils.set_random_seed(42)

    target_col = f"target_r_{direction}"
    valid = ~features[target_col].isna()
    feats = features[valid]

    X = feats[feature_cols].fillna(0).values.astype(np.float32)
    y = feats[target_col].values.astype(np.float32)

    if len(X) < seq_len + 100:
        return {"error": "insufficient_samples"}

    # Build sequences
    Xs = []
    ys = []
    ws = []
    for i in range(seq_len, len(X)):
        Xs.append(X[i - seq_len:i])
        ys.append(y[i])
        # Weight high-magnitude moves more
        ws.append(weight_high_r if abs(y[i]) > 0.5 else 1.0)
    Xs = np.array(Xs, dtype=np.float32)
    ys = np.array(ys, dtype=np.float32)
    ws = np.array(ws, dtype=np.float32)
    print(f"  Sequences: {Xs.shape}, weighted: {(ws > 1).sum()} ({(ws > 1).sum()/len(ws)*100:.1f}%)")

    # Train/val split (last 15% as val)
    split = int(len(Xs) * 0.85)
    X_tr, X_val = Xs[:split], Xs[split:]
    y_tr, y_val = ys[:split], ys[split:]
    w_tr = ws[:split]

    # Robust standardize: use median + IQR instead of mean/std
    # (financial features have heavy tails)
    mean = np.median(X_tr, axis=(0, 1), keepdims=True)
    q75 = np.quantile(X_tr, 0.75, axis=(0, 1), keepdims=True)
    q25 = np.quantile(X_tr, 0.25, axis=(0, 1), keepdims=True)
    std = (q75 - q25) + 1e-6
    X_tr = (X_tr - mean) / std
    X_val = (X_val - mean) / std

    # Build + compile model
    model = build_arch(arch, seq_len, len(feature_cols))
    initial_lr = 1e-3
    # Cosine decay
    lr_schedule = optimizers.schedules.CosineDecay(initial_lr, decay_steps=epochs * len(X_tr) // batch_size)
    opt = optimizers.AdamW(learning_rate=lr_schedule, weight_decay=1e-4)
    model.compile(optimizer=opt, loss="mse", metrics=["mae"])

    es = callbacks.EarlyStopping(patience=10, restore_best_weights=True, monitor="val_mae")

    t0 = time.time()
    history = model.fit(
        X_tr, y_tr, sample_weight=w_tr,
        validation_data=(X_val, y_val),
        epochs=epochs, batch_size=batch_size,
        verbose=0, callbacks=[es],
    )
    elapsed = time.time() - t0

    val_pred = model.predict(X_val, verbose=0).flatten()
    val_mse = float(np.mean((val_pred - y_val) ** 2))
    val_mae = float(np.mean(np.abs(val_pred - y_val)))

    # Save
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{arch}_{direction}.keras"
    model.save(str(model_path))
    np.savez(str(MODELS_DIR / f"{arch}_{direction}.scaler.npz"), mean=mean, std=std)

    meta = {
        "arch": arch, "direction": direction,
        "seq_length": seq_len,
        "n_sequences": len(Xs),
        "val_mse": val_mse, "val_mae": val_mae,
        "epochs_trained": len(history.history["loss"]),
        "epochs_max": epochs,
        "weight_high_r": weight_high_r,
        "elapsed_sec": elapsed,
    }
    meta_path = MODELS_DIR / f"{arch}_{direction}.meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    print(f"  -> val_mse={val_mse:.3f}, val_mae={val_mae:.3f}, "
          f"epochs={meta['epochs_trained']}/{epochs}, time={elapsed:.0f}s")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archs", default="shallow,gru,conv",
                    help="comma-separated architectures to try")
    ap.add_argument("--directions", default="long,short")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--quick", action="store_true",
                    help="10 epochs fast iteration")
    args = ap.parse_args()

    if args.quick:
        args.epochs = 10

    archs = [a.strip() for a in args.archs.split(",")]
    directions = [d.strip() for d in args.directions.split(",")]

    print(f"Architectures: {archs}, directions: {directions}, epochs: {args.epochs}")
    print()

    print("Loading features + labels...")
    features = load_features_and_labels(years=3)
    from src.analysis.features_v2 import ALL_V2_FEATURE_COLS
    feature_cols = [c for c in ALL_V2_FEATURE_COLS if c in features.columns]
    print(f"Features: {features.shape}, cols: {len(feature_cols)}")
    print()

    summary = []
    for arch in archs:
        for direction in directions:
            print(f"=== {arch} {direction.upper()} ===")
            try:
                meta = train_arch(features, feature_cols, direction, arch,
                                  epochs=args.epochs)
                summary.append((arch, direction, meta))
            except Exception as e:
                print(f"  EXCEPTION: {e}")
                summary.append((arch, direction, {"error": str(e)}))
            print()

    # Final comparison table
    print("=" * 70)
    print("ARCHITECTURE COMPARISON (val_mse, lower=better)")
    print("=" * 70)
    print(f"{'arch':>10s} {'direction':>10s} {'val_mse':>10s} {'val_mae':>10s} {'epochs':>8s} {'time':>6s}")
    for arch, direction, meta in summary:
        if "error" in meta:
            print(f"{arch:>10s} {direction:>10s} ERROR: {meta['error']}")
        else:
            print(f"{arch:>10s} {direction:>10s} {meta['val_mse']:>10.3f} "
                  f"{meta['val_mae']:>10.3f} {meta['epochs_trained']:>8d} "
                  f"{meta['elapsed_sec']:>6.0f}s")

    # Reference: original train_v2 LSTM was val_mse 53.84 (LONG), 17.22 (SHORT)
    # Reference: XGB was val_mse 21.61 (LONG), 11.11 (SHORT)
    print()
    print("Baseline reference (train_v2):")
    print(f"  LSTM LONG:  53.84  (early stop @ 6 epochs)")
    print(f"  LSTM SHORT: 17.22")
    print(f"  XGB LONG:   21.61  (Optuna 50 trials)")
    print(f"  XGB SHORT:  11.11  (Optuna 50 trials)")

    # Write summary
    out_path = MODELS_DIR / "_arch_comparison.json"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump([{"arch": a, "direction": d, "meta": m} for a, d, m in summary],
                  f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
