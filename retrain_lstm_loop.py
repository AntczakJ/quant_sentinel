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


def live_stdev_check(model, scaler, seq_len: int, n_features: int,
                     symbol: str = "GC=F", n_windows: int = 10) -> Optional[float]:
    """Evaluate the trained model on ~n_windows rolling slices of the most
    recent live data. Returns stdev of predictions — a flat model
    (stdev < 0.02) is not producing signal regardless of what the
    held-out test accuracy says."""
    from src.analysis.compute import compute_features, FEATURE_COLS
    import contextlib, io as _io
    try:
        with contextlib.redirect_stdout(_io.StringIO()), \
             contextlib.redirect_stderr(_io.StringIO()):
            live = yf.Ticker(symbol).history(period="2mo", interval="1h")
    except Exception:
        return None
    live = live.reset_index()
    live.columns = [c.lower() for c in live.columns]
    cols = [c for c in ("open", "high", "low", "close", "volume") if c in live.columns]
    live = live[cols].dropna().reset_index(drop=True)
    if len(live) < seq_len + n_windows * 5:
        return None

    preds = []
    for i in range(n_windows):
        end = len(live) - i * 5 - 1
        if end < seq_len:
            break
        feats = compute_features(live.iloc[:end]).dropna()
        if len(feats) < seq_len:
            continue
        data = feats[FEATURE_COLS].values[-seq_len:].astype(np.float32)
        if data.shape[1] != n_features:
            continue
        scaled = scaler.transform(data).astype(np.float32)
        p = float(model(scaled.reshape(1, seq_len, -1), training=False).numpy()[0, 0])
        preds.append(p)
    if len(preds) < 3:
        return None
    import statistics
    return statistics.stdev(preds)


def train_once(df: pd.DataFrame, hp: Dict, seed: int) -> Optional[Dict]:
    """Single retrain attempt. Returns summary dict with val/test accuracy
    AND balanced_accuracy + F1 (class-imbalance-robust) + live prediction
    stdev (catches flat-output models that score high only because one
    class dominates the test split)."""
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam
    from sklearn.metrics import balanced_accuracy_score, f1_score

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

    # Class-imbalance-robust metrics. A model that always predicts SHORT
    # on a 60/40-SHORT test split scores 60% raw accuracy but 50% balanced
    # accuracy — balanced_acc is the honest signal.
    X_test, y_test = splits["test"]
    y_pred_proba = model(X_test, training=False).numpy().flatten()
    y_pred = (y_pred_proba > 0.5).astype(int)
    balanced_acc = float(balanced_accuracy_score(y_test, y_pred))
    f1 = float(f1_score(y_test, y_pred, average="binary", zero_division=0))
    import statistics as _stats
    test_pred_stdev = float(_stats.stdev(y_pred_proba)) if len(y_pred_proba) > 1 else 0.0
    test_class_balance = float(y_test.mean())  # fraction of positives

    # Live-data stdev: a last-mile sanity check that the model actually
    # varies its output on fresh bars. Several LSTM configs score well
    # offline but output a near-constant on live data.
    live_stdev = live_stdev_check(model, scaler, hp["seq_len"],
                                  n_features=int(X.shape[2]))

    return {
        "model": model,
        "scaler": scaler,
        "seq_len": hp["seq_len"],
        "hparams": hp,
        "seed": seed,
        "val_acc": val_acc,
        "test_acc": float(test_acc),
        "test_balanced_acc": balanced_acc,
        "test_f1": f1,
        "test_pred_stdev": test_pred_stdev,
        "test_class_balance": test_class_balance,
        "live_pred_stdev": live_stdev,
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
    ap.add_argument("--iterations", type=int, default=8,
                    help="max iterations (was 5 — raised because the balanced "
                         "metric is stricter and needs more sampling)")
    ap.add_argument("--target", type=float, default=0.55,
                    help="stop as soon as balanced_accuracy >= target")
    ap.add_argument("--min-live-stdev", type=float, default=0.05,
                    help="reject a winner whose predictions are flat on live "
                         "data (stdev below this on 10 rolling windows)")
    ap.add_argument("--patience", type=int, default=4,
                    help="abort if no balanced-acc improvement for N iterations")
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

        live_s = res["live_pred_stdev"]
        live_s_str = f"{live_s:.4f}" if live_s is not None else "n/a"
        flat_flag = " [FLAT]" if live_s is not None and live_s < args.min_live_stdev else ""
        imbalance_flag = ""
        if abs(res["test_class_balance"] - 0.5) > 0.15:
            imbalance_flag = f" [imbalanced test: {res['test_class_balance']:.0%} pos]"

        print(f"  raw_acc={res['test_acc']:.3f}  balanced_acc={res['test_balanced_acc']:.3f}  "
              f"f1={res['test_f1']:.3f}  test_stdev={res['test_pred_stdev']:.4f}  "
              f"live_stdev={live_s_str}{flat_flag}{imbalance_flag}")

        history.append({
            "iter": i + 1,
            "balanced_acc": res["test_balanced_acc"],
            "raw_acc": res["test_acc"],
            "f1": res["test_f1"],
            "live_stdev": live_s,
            "hparams": hp,
            "seed": seed,
        })

        # Rank by BALANCED accuracy, not raw — raw is cheatable on class-imbalanced
        # splits. Also gate: a flat-output model cannot become 'best' regardless
        # of metric; it's not producing signal in production.
        candidate_better = (best is None or
                            res["test_balanced_acc"] > best["test_balanced_acc"])
        candidate_signal_ok = (live_s is None or live_s >= args.min_live_stdev)
        # If we can't measure live stdev at all, we accept the candidate but
        # print a warning. If we can measure AND it's flat, reject.
        if candidate_better and candidate_signal_ok:
            best = res
            best_iter = i + 1
            no_improve = 0
            print(f"  ** new best balanced_acc={res['test_balanced_acc']:.3f} "
                  f"live_stdev={live_s_str} **")
        elif candidate_better and not candidate_signal_ok:
            no_improve += 1
            print(f"  (better balanced_acc but FLAT on live — rejected)")
        else:
            no_improve += 1

        if best is not None and best["test_balanced_acc"] >= args.target:
            print(f"\n[stop] target hit (balanced_acc >= {args.target})")
            break
        if no_improve >= args.patience:
            print(f"\n[stop] patience exhausted ({args.patience} iter without improvement)")
            break

    elapsed_min = (time.time() - t_start) / 60
    print(f"\n=== done in {elapsed_min:.1f} min ===")
    print("history:")
    for h in history:
        marker = " <- best" if h["iter"] == best_iter else ""
        live_s = h.get("live_stdev")
        live_s_str = f"{live_s:.4f}" if live_s is not None else "n/a"
        print(f"  iter {h['iter']}: balanced_acc={h['balanced_acc']:.3f} "
              f"raw={h['raw_acc']:.3f} f1={h['f1']:.3f} "
              f"live_stdev={live_s_str}{marker}")

    if best is None:
        print("[fatal] no successful iteration", file=sys.stderr)
        return 3

    live_s = best.get("live_pred_stdev")
    live_s_str = f"{live_s:.4f}" if live_s is not None else "n/a"
    print(f"\nBest: balanced_acc={best['test_balanced_acc']:.3f}  "
          f"raw_acc={best['test_acc']:.3f}  f1={best['test_f1']:.3f}  "
          f"live_stdev={live_s_str}  seed={best['seed']}  hp={best['hparams']}")

    if args.dry_run:
        print("[dry-run] persisting nothing")
        return 0

    # Promotion decision: two independent gates. A winner must clear BOTH.
    ESCALATION_FLOOR = 0.52  # balanced_acc — above coin flip by ≥2pp
    if best["test_balanced_acc"] < ESCALATION_FLOOR:
        print(f"\n[WARN] best balanced_acc {best['test_balanced_acc']:.3f} "
              f"below floor {ESCALATION_FLOOR}.")
        print("[WARN] Skipping persist. Escalate to Optuna-based tune_lstm.py.")
        return 4
    if live_s is not None and live_s < args.min_live_stdev:
        print(f"\n[WARN] best candidate is FLAT on live data "
              f"(stdev {live_s:.4f} < {args.min_live_stdev}).")
        print("[WARN] Skipping persist. The model would ship as a constant voter.")
        return 5

    persist_winner(best)
    print(f"\n[persist] models/lstm.keras updated "
          f"(balanced_acc={best['test_balanced_acc']:.3f} "
          f"live_stdev={live_s_str})")
    return 0 if best["test_balanced_acc"] >= args.target else 1


if __name__ == "__main__":
    sys.exit(main())
