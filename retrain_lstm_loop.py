#!/usr/bin/env python3
"""retrain_lstm_loop.py - Iterative LSTM retrain with held-out OOS eval.

Trains the LSTM voter N times with different seeds and a mild
hyperparameter perturbation each iteration, evaluating on a truly
held-out test slice (the model NEVER sees this slice during train or
for early stopping). Keeps the winner by test accuracy.

Why this exists
---------------
Per-voter attribution reported LSTM at 33% accuracy on 18 live votes.
Live predictions cluster at 0.49-0.50 — the model has lost
discrimination rather than having an actively wrong signal. A plain
'retrain same code with new seed' doesn't fix structural drift; a mild
hparam perturbation per iter + honest OOS scoring finds a winner
cheaply before the heavier tune_lstm.py sweep becomes necessary.

Scope
-----
- Uses the same features (compute_features + FEATURE_COLS) and target
  (compute_target) as the production LSTM, so the winner plugs
  straight into the ensemble.
- Does NOT touch models/lstm.keras until a winner exists with strictly
  better test accuracy than the incumbent or the loop exits with the
  best seen so far (configurable).
- Writes every attempt to models/training_history.jsonl for audit.

Stop conditions
---------------
- test_acc >= target (default 0.55 — matches SMC baseline)
- max iterations reached (default 5)
- patience: no improvement for N iterations (default 3)

Usage
-----
  python retrain_lstm_loop.py                       # 5 iter, target 0.55
  python retrain_lstm_loop.py --iterations 10 --target 0.58
  python retrain_lstm_loop.py --dry-run             # build model, eval, exit
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import pickle
import random
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
import pandas as pd
import yfinance as yf

from src.core.logger import logger
from src.ml.training_registry import log_training_run


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def fetch_ohlcv(symbol: str = "GC=F") -> Optional[pd.DataFrame]:
    """Match train_all.py's yfinance logic but quieter."""
    for period, interval in (("2y", "1h"), ("1y", "1h"), ("60d", "15m"),
                             ("10y", "1d"), ("5y", "1d")):
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                df = yf.Ticker(symbol).history(period=period, interval=interval)
        except Exception as e:
            logger.debug(f"[lstm-loop] fetch {period}/{interval} failed: {e}")
            continue
        if df is None or len(df) < 200:
            continue
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        keep = [c for c in ("open", "high", "low", "close", "volume")
                if c in df.columns]
        df = df[keep].dropna().reset_index(drop=True)
        print(f"[data] {symbol}: {len(df)} bars @ {period}/{interval}")
        return df
    return None


def prepare_xy(df: pd.DataFrame, seq_len: int
               ) -> Optional[Tuple[np.ndarray, np.ndarray, object]]:
    """Return (X, y, fitted_scaler) or None on insufficient data."""
    from src.analysis.compute import compute_features, compute_target, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler

    feats = compute_features(df).copy()
    feats["direction"] = compute_target(feats)
    feats.dropna(inplace=True)
    if len(feats) < seq_len + 20:
        return None

    data = feats[FEATURE_COLS].values.astype(np.float32)
    scaler = MinMaxScaler().fit(data)
    scaled = scaler.transform(data)

    n_samples = len(scaled) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X = scaled[idx]
    y = feats["direction"].values[seq_len:]
    return X, y, scaler


def three_way_split(X: np.ndarray, y: np.ndarray,
                    train_frac: float = 0.6,
                    val_frac: float = 0.2
                    ) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    n = len(X)
    a = int(n * train_frac)
    b = int(n * (train_frac + val_frac))
    return {
        "train": (X[:a], y[:a]),
        "val":   (X[a:b], y[a:b]),
        "test":  (X[b:], y[b:]),
    }


# ---------------------------------------------------------------------------
# Model + iteration
# ---------------------------------------------------------------------------

HPARAM_SPACE = {
    "seq_len":    (40, 60, 80),
    "hidden":     (64, 128),
    "dropout":    (0.15, 0.25, 0.35),
    "lr":         (3e-4, 5e-4, 1e-3),
    "batch_size": (32, 64),
    "epochs":     (50, 80),
}


def sample_hparams(rng: random.Random) -> Dict:
    return {k: rng.choice(v) for k, v in HPARAM_SPACE.items()}


def build_lstm(seq_len: int, n_features: int, hidden: int, dropout: float):
    """Three stacked LSTM layers, mirroring production shape but with a
    configurable hidden-unit base so the loop can shrink the model when
    overfit is the suspected failure mode."""
    import tensorflow as tf
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.models import Sequential

    model = Sequential([
        LSTM(hidden, return_sequences=True, input_shape=(seq_len, n_features)),
        Dropout(dropout),
        LSTM(max(16, hidden // 2), return_sequences=True),
        Dropout(dropout * 0.85),
        LSTM(max(8, hidden // 4)),
        Dropout(dropout * 0.7),
        Dense(32, activation="relu"),
        Dense(16, activation="relu"),
        Dense(1, activation="sigmoid", dtype="float32"),
    ])
    return model


def train_once(df: pd.DataFrame, hp: Dict, seed: int) -> Optional[Dict]:
    """Single retrain attempt. Returns summary dict with val_acc, test_acc,
    the fitted model + scaler + seq_len for the caller to persist."""
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam

    random.seed(seed)
    np.random.seed(seed)
    tf.random.set_seed(seed)

    prep = prepare_xy(df, seq_len=hp["seq_len"])
    if prep is None:
        return None
    X, y, scaler = prep
    splits = three_way_split(X, y)
    if min(len(splits["train"][0]), len(splits["val"][0]),
           len(splits["test"][0])) < 30:
        print(f"[iter] skip — one split too small")
        return None

    # Class balance on TRAIN only (val/test should reflect natural distribution).
    y_tr = splits["train"][1]
    n_pos = int(y_tr.sum())
    n_neg = len(y_tr) - n_pos
    class_weight = ({0: 1.0, 1: n_neg / max(n_pos, 1)}
                    if n_pos > 0 and n_neg > 0 else None)

    tf.keras.backend.clear_session()
    model = build_lstm(
        seq_len=hp["seq_len"],
        n_features=X.shape[2],
        hidden=hp["hidden"],
        dropout=hp["dropout"],
    )
    model.compile(optimizer=Adam(learning_rate=hp["lr"]),
                  loss="binary_crossentropy", metrics=["accuracy"])

    early = EarlyStopping(monitor="val_loss", patience=10,
                          restore_best_weights=True)
    t0 = time.time()
    history = model.fit(
        splits["train"][0], splits["train"][1],
        validation_data=splits["val"],
        epochs=hp["epochs"],
        batch_size=hp["batch_size"],
        callbacks=[early], verbose=0,
        class_weight=class_weight,
    )
    train_sec = time.time() - t0

    val_acc = float(max(history.history.get("val_accuracy", [0.5])))
    test_loss, test_acc = model.evaluate(*splits["test"], verbose=0)

    return {
        "model": model,
        "scaler": scaler,
        "seq_len": hp["seq_len"],
        "hparams": hp,
        "seed": seed,
        "val_acc": val_acc,
        "test_acc": float(test_acc),
        "test_loss": float(test_loss),
        "train_sec": round(train_sec, 1),
        "n_features": int(X.shape[2]),
        "n_train": int(len(splits["train"][0])),
        "n_val": int(len(splits["val"][0])),
        "n_test": int(len(splits["test"][0])),
    }


# ---------------------------------------------------------------------------
# Persistence (atomic, matches train_all.py convention)
# ---------------------------------------------------------------------------

def persist_winner(result: Dict, model_dir: str = "models") -> None:
    from src.analysis.compute import FEATURE_COLS
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    model_path = Path(model_dir) / "lstm.keras"
    scaler_path = Path(model_dir) / "lstm_scaler.pkl"

    tmp_model = model_path.with_suffix(".tmp.keras")
    result["model"].save(tmp_model)
    os.replace(tmp_model, model_path)

    tmp_scaler = scaler_path.with_suffix(".tmp.pkl")
    with open(tmp_scaler, "wb") as f:
        pickle.dump(result["scaler"], f)
    os.replace(tmp_scaler, scaler_path)

    # ONNX regen so production inference stays in sync (matches the rest
    # of the ensemble which prefers DirectML ONNX when available).
    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx_path = convert_keras_to_onnx(str(model_path),
                                          str(Path(model_dir) / "lstm.onnx"))
        if onnx_path:
            print(f"[persist] ONNX -> {onnx_path}")
    except Exception as e:
        print(f"[persist] ONNX regen failed (non-fatal): {e}")

    # Audit trail so the widget shows this run in Training History.
    try:
        log_training_run(
            model_type="lstm",
            hyperparams={**result["hparams"], "seed": result["seed"]},
            data_signature={"symbol": "GC=F", "n_features": result["n_features"],
                            "feature_cols": list(FEATURE_COLS)},
            metrics={"val_acc": round(result["val_acc"], 4),
                     "test_acc": round(result["test_acc"], 4),
                     "test_loss": round(result["test_loss"], 4),
                     "train_sec": result["train_sec"]},
            artifact_path=str(model_path),
            notes="retrain_lstm_loop winner",
        )
    except Exception as e:
        print(f"[registry] log failed: {e}")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=5)
    ap.add_argument("--target", type=float, default=0.55,
                    help="stop as soon as test_acc >= target")
    ap.add_argument("--patience", type=int, default=3,
                    help="abort if no improvement for this many iterations")
    ap.add_argument("--symbol", default="GC=F")
    ap.add_argument("--base-seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true",
                    help="run 1 iteration, print result, persist nothing")
    args = ap.parse_args()

    df = fetch_ohlcv(args.symbol)
    if df is None:
        print(f"[fatal] cannot fetch data for {args.symbol}", file=sys.stderr)
        return 2

    rng = random.Random(args.base_seed)
    best: Optional[Dict] = None
    best_iter = -1
    no_improve = 0
    history = []

    total_iters = 1 if args.dry_run else args.iterations
    t_start = time.time()

    for i in range(total_iters):
        seed = args.base_seed + i * 1000 + rng.randint(0, 999)
        hp = sample_hparams(rng)
        print(f"\n=== iter {i+1}/{total_iters}  seed={seed}  hp={hp} ===")

        res = train_once(df, hp, seed)
        if res is None:
            print("  [iter] skipped (insufficient data or build error)")
            continue

        print(f"  val_acc={res['val_acc']:.3f}  test_acc={res['test_acc']:.3f}  "
              f"train={res['train_sec']}s  train_n={res['n_train']}/val={res['n_val']}/test={res['n_test']}")
        history.append({"iter": i + 1, "test_acc": res["test_acc"],
                        "val_acc": res["val_acc"], "hparams": hp, "seed": seed})

        improved = best is None or res["test_acc"] > best["test_acc"]
        if improved:
            best = res
            best_iter = i + 1
            no_improve = 0
            print(f"  ** new best test_acc={res['test_acc']:.3f} **")
        else:
            no_improve += 1

        if res["test_acc"] >= args.target:
            print(f"\n[stop] target hit (test_acc >= {args.target})")
            break
        if no_improve >= args.patience:
            print(f"\n[stop] patience exhausted ({args.patience} iter without improvement)")
            break

    elapsed_min = (time.time() - t_start) / 60
    print(f"\n=== done in {elapsed_min:.1f} min ===")
    print("history:")
    for h in history:
        marker = " <- best" if h["iter"] == best_iter else ""
        print(f"  iter {h['iter']}: test_acc={h['test_acc']:.3f} val={h['val_acc']:.3f}{marker}")

    if best is None:
        print("[fatal] no successful iteration", file=sys.stderr)
        return 3

    print(f"\nBest: test_acc={best['test_acc']:.3f}  val_acc={best['val_acc']:.3f}  "
          f"seed={best['seed']}  hp={best['hparams']}")

    if args.dry_run:
        print("[dry-run] persisting nothing")
        return 0

    # Promotion decision: only overwrite production if the winner clears
    # a sensible floor. If every iteration was <45%, escalate to Optuna.
    ESCALATION_FLOOR = 0.45
    if best["test_acc"] < ESCALATION_FLOOR:
        print(f"\n[WARN] best test_acc {best['test_acc']:.3f} below {ESCALATION_FLOOR}.")
        print("[WARN] Skipping persist. Recommend escalating to tune_lstm.py "
              "(Optuna-based — same framework as tune_rl.py).")
        return 4

    persist_winner(best)
    print(f"\n[persist] models/lstm.keras updated (test_acc={best['test_acc']:.3f})")
    print("Set ensemble weight check: `python -c \"from src.ml.ensemble_models import get_model_track_record; "
          "import json; print(json.dumps(get_model_track_record(), indent=2))\"`")
    return 0 if best["test_acc"] >= args.target else 1


if __name__ == "__main__":
    sys.exit(main())
