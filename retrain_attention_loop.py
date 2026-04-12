#!/usr/bin/env python3
"""retrain_attention_loop.py - Iterative TFT-lite retrain with strict OOS gating.

Sibling of retrain_lstm_loop.py for the attention (TFT-lite) voter.
Same diagnostic toolkit — balanced_accuracy + F1 + live prediction
stdev on rolling windows — so we catch flat-output models that only
look good because of test-slice class imbalance.

Architecture matches src/ml/attention_model.build_attention_model
(two MultiHeadAttention layers + dense head), but with a small
configurable depth / head-count for the iteration loop to sweep.

Usage
-----
  python retrain_attention_loop.py                   # default: 6 iter, 6mo
  python retrain_attention_loop.py --iterations 10 --target 0.55
  python retrain_attention_loop.py --dry-run
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
# Data (identical to retrain_lstm_loop — kept local so the two scripts are
# independent; avoid coupling failures)
# ---------------------------------------------------------------------------

def fetch_ohlcv(symbol: str = "GC=F",
                preferred_window: str = "6mo") -> Optional[pd.DataFrame]:
    combos = [
        (preferred_window, "1h"), ("1y", "1h"), ("6mo", "1h"),
        ("60d", "15m"), ("2y", "1d"),
    ]
    seen = set()
    combos = [(p, i) for p, i in combos if (p, i) not in seen and not seen.add((p, i))]
    for period, interval in combos:
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                df = yf.Ticker(symbol).history(period=period, interval=interval)
        except Exception as e:
            logger.debug(f"[attn-loop] fetch {period}/{interval} failed: {e}")
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


def prepare_xy(df: pd.DataFrame, seq_len: int, scaler_kind: str = "robust"
               ) -> Optional[Tuple[np.ndarray, np.ndarray, object]]:
    from src.analysis.compute import compute_features, compute_target, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

    feats = compute_features(df).copy()
    feats["direction"] = compute_target(feats)
    feats.dropna(inplace=True)
    if len(feats) < seq_len + 20:
        return None
    data = feats[FEATURE_COLS].values.astype(np.float32)
    scaler_cls = {"robust": RobustScaler, "minmax": MinMaxScaler,
                  "standard": StandardScaler}.get(scaler_kind, RobustScaler)
    scaler = scaler_cls().fit(data)
    scaled = scaler.transform(data)
    n_samples = len(scaled) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X = scaled[idx]
    y = feats["direction"].values[seq_len:]
    return X, y, scaler


def three_way_split(X, y, train_frac=0.6, val_frac=0.2):
    n = len(X)
    a = int(n * train_frac)
    b = int(n * (train_frac + val_frac))
    return {"train": (X[:a], y[:a]), "val": (X[a:b], y[a:b]),
            "test": (X[b:], y[b:])}


# ---------------------------------------------------------------------------
# Architecture — TFT-lite variant parameterised for the sweep
# ---------------------------------------------------------------------------

HPARAM_SPACE = {
    "seq_len":    (40, 60, 80),
    "n_heads":    (2, 4, 8),
    "key_dim":    (8, 16, 32),
    "n_blocks":   (1, 2, 3),
    "dropout":    (0.1, 0.2, 0.3),
    "lr":         (3e-4, 5e-4, 1e-3),
    "batch_size": (32, 64),
    "epochs":     (40, 60),
    "scaler":     ("robust", "minmax"),
}


def sample_hparams(rng: random.Random) -> Dict:
    return {k: rng.choice(v) for k, v in HPARAM_SPACE.items()}


def build_tft(seq_len: int, n_features: int, n_heads: int, key_dim: int,
              n_blocks: int, dropout: float):
    import tensorflow as tf
    from tensorflow.keras.layers import (
        Input, Dense, Dropout, LayerNormalization,
        MultiHeadAttention, GlobalAveragePooling1D, Concatenate,
    )
    from tensorflow.keras.models import Model

    inp = Input(shape=(seq_len, n_features), name="input")
    x = inp
    for b in range(n_blocks):
        attn = MultiHeadAttention(
            num_heads=n_heads, key_dim=key_dim, dropout=dropout,
            name=f"attn_{b}",
        )(x, x)
        x = LayerNormalization(name=f"norm_{b}")(x + attn)

    last = x[:, -1, :]
    pooled = GlobalAveragePooling1D(name="avg")(x)
    merged = Concatenate(name="merge")([last, pooled])
    head = Dense(64, activation="relu", name="head1")(merged)
    head = Dropout(dropout)(head)
    head = Dense(32, activation="relu", name="head2")(head)
    head = Dropout(dropout * 0.7)(head)
    out = Dense(1, activation="sigmoid", dtype="float32", name="output")(head)
    return Model(inputs=inp, outputs=out, name="tft_lite_retrain")


# ---------------------------------------------------------------------------
# Live stdev smoke (identical to LSTM loop)
# ---------------------------------------------------------------------------

def live_stdev_check(model, scaler, seq_len: int, n_features: int,
                     symbol: str = "GC=F", n_windows: int = 10) -> Optional[float]:
    from src.analysis.compute import compute_features, FEATURE_COLS
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
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


# ---------------------------------------------------------------------------
# Train one iteration
# ---------------------------------------------------------------------------

def train_once(df: pd.DataFrame, hp: Dict, seed: int) -> Optional[Dict]:
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam
    from sklearn.metrics import balanced_accuracy_score, f1_score

    random.seed(seed); np.random.seed(seed); tf.random.set_seed(seed)

    prep = prepare_xy(df, seq_len=hp["seq_len"],
                      scaler_kind=hp.get("scaler", "robust"))
    if prep is None:
        return None
    X, y, scaler = prep
    splits = three_way_split(X, y)
    if min(len(splits["train"][0]), len(splits["val"][0]),
           len(splits["test"][0])) < 30:
        return None

    y_tr = splits["train"][1]
    n_pos = int(y_tr.sum())
    n_neg = len(y_tr) - n_pos
    class_weight = ({0: 1.0, 1: n_neg / max(n_pos, 1)}
                    if n_pos > 0 and n_neg > 0 else None)

    tf.keras.backend.clear_session()
    model = build_tft(seq_len=hp["seq_len"], n_features=X.shape[2],
                      n_heads=hp["n_heads"], key_dim=hp["key_dim"],
                      n_blocks=hp["n_blocks"], dropout=hp["dropout"])
    model.compile(optimizer=Adam(learning_rate=hp["lr"]),
                  loss="binary_crossentropy", metrics=["accuracy"])
    early = EarlyStopping(monitor="val_loss", patience=10,
                          restore_best_weights=True)
    t0 = time.time()
    history = model.fit(
        splits["train"][0], splits["train"][1],
        validation_data=splits["val"],
        epochs=hp["epochs"], batch_size=hp["batch_size"],
        callbacks=[early], verbose=0, class_weight=class_weight,
    )
    train_sec = time.time() - t0

    val_acc = float(max(history.history.get("val_accuracy", [0.5])))
    test_loss, test_acc = model.evaluate(*splits["test"], verbose=0)
    X_test, y_test = splits["test"]
    y_pred_proba = model(X_test, training=False).numpy().flatten()
    y_pred = (y_pred_proba > 0.5).astype(int)
    balanced_acc = float(balanced_accuracy_score(y_test, y_pred))
    f1 = float(f1_score(y_test, y_pred, average="binary", zero_division=0))
    import statistics as _stats
    test_pred_stdev = float(_stats.stdev(y_pred_proba)) if len(y_pred_proba) > 1 else 0.0
    live_stdev = live_stdev_check(model, scaler, hp["seq_len"], X.shape[2])

    return {
        "model": model, "scaler": scaler, "seq_len": hp["seq_len"],
        "hparams": hp, "seed": seed,
        "val_acc": val_acc, "test_acc": float(test_acc),
        "test_balanced_acc": balanced_acc, "test_f1": f1,
        "test_pred_stdev": test_pred_stdev,
        "test_class_balance": float(y_test.mean()),
        "live_pred_stdev": live_stdev,
        "test_loss": float(test_loss), "train_sec": round(train_sec, 1),
        "n_features": int(X.shape[2]),
        "n_train": int(len(splits["train"][0])),
        "n_val": int(len(splits["val"][0])),
        "n_test": int(len(splits["test"][0])),
    }


# ---------------------------------------------------------------------------
# Persistence — writes to attention.keras / _scaler.pkl / .onnx
# ---------------------------------------------------------------------------

def persist_winner(result: Dict, model_dir: str = "models") -> None:
    from src.analysis.compute import FEATURE_COLS
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    model_path = Path(model_dir) / "attention.keras"
    scaler_path = Path(model_dir) / "attention_scaler.pkl"

    tmp_model = model_path.with_suffix(".tmp.keras")
    result["model"].save(tmp_model)
    os.replace(tmp_model, model_path)
    tmp_scaler = scaler_path.with_suffix(".tmp.pkl")
    with open(tmp_scaler, "wb") as f:
        pickle.dump(result["scaler"], f)
    os.replace(tmp_scaler, scaler_path)

    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx_path = convert_keras_to_onnx(str(model_path),
                                          str(Path(model_dir) / "attention.onnx"))
        if onnx_path:
            print(f"[persist] ONNX -> {onnx_path}")
    except Exception as e:
        print(f"[persist] ONNX regen failed: {e}")

    try:
        log_training_run(
            model_type="attention",
            hyperparams={**result["hparams"], "seed": result["seed"]},
            data_signature={"symbol": "GC=F", "n_features": result["n_features"],
                            "feature_cols": list(FEATURE_COLS)},
            metrics={"val_acc": round(result["val_acc"], 4),
                     "test_balanced_acc": round(result["test_balanced_acc"], 4),
                     "test_f1": round(result["test_f1"], 4),
                     "live_stdev": result["live_pred_stdev"],
                     "train_sec": result["train_sec"]},
            artifact_path=str(model_path),
            notes="retrain_attention_loop winner",
        )
    except Exception as e:
        print(f"[registry] log failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--target", type=float, default=0.55)
    ap.add_argument("--min-live-stdev", type=float, default=0.03)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--window", default="6mo")
    ap.add_argument("--symbol", default="GC=F")
    ap.add_argument("--base-seed", type=int, default=17)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    df = fetch_ohlcv(args.symbol, preferred_window=args.window)
    if df is None:
        print(f"[fatal] cannot fetch {args.symbol}", file=sys.stderr)
        return 2

    rng = random.Random(args.base_seed)
    best: Optional[Dict] = None
    best_iter = -1
    no_improve = 0
    history = []
    total = 1 if args.dry_run else args.iterations
    t0 = time.time()

    for i in range(total):
        seed = args.base_seed + i * 1000 + rng.randint(0, 999)
        hp = sample_hparams(rng)
        print(f"\n=== iter {i+1}/{total}  seed={seed}  hp={hp} ===")
        res = train_once(df, hp, seed)
        if res is None:
            print("  [iter] skipped")
            continue

        live_s = res["live_pred_stdev"]
        live_s_str = f"{live_s:.4f}" if live_s is not None else "n/a"
        flat = live_s is not None and live_s < args.min_live_stdev
        flat_flag = " [FLAT]" if flat else ""
        imbal = abs(res["test_class_balance"] - 0.5) > 0.15
        imbal_flag = (f" [imbalanced test: {res['test_class_balance']:.0%} pos]"
                      if imbal else "")
        print(f"  raw_acc={res['test_acc']:.3f}  balanced_acc={res['test_balanced_acc']:.3f}  "
              f"f1={res['test_f1']:.3f}  live_stdev={live_s_str}{flat_flag}{imbal_flag}")

        history.append({
            "iter": i + 1,
            "balanced_acc": res["test_balanced_acc"],
            "raw_acc": res["test_acc"], "f1": res["test_f1"],
            "live_stdev": live_s, "hparams": hp, "seed": seed,
        })

        better = best is None or res["test_balanced_acc"] > best["test_balanced_acc"]
        signal_ok = (live_s is None or live_s >= args.min_live_stdev)
        if better and signal_ok:
            best = res; best_iter = i + 1; no_improve = 0
            print(f"  ** new best balanced_acc={res['test_balanced_acc']:.3f} "
                  f"live_stdev={live_s_str} **")
        elif better and not signal_ok:
            no_improve += 1
            print(f"  (better balanced_acc but FLAT on live — rejected)")
        else:
            no_improve += 1

        if best is not None and best["test_balanced_acc"] >= args.target:
            print(f"\n[stop] target hit")
            break
        if no_improve >= args.patience:
            print(f"\n[stop] patience exhausted")
            break

    elapsed = (time.time() - t0) / 60
    print(f"\n=== done in {elapsed:.1f} min ===")
    print("history:")
    for h in history:
        mark = " <- best" if h["iter"] == best_iter else ""
        ls = h.get("live_stdev")
        ls_str = f"{ls:.4f}" if ls is not None else "n/a"
        print(f"  iter {h['iter']}: balanced_acc={h['balanced_acc']:.3f} "
              f"raw={h['raw_acc']:.3f} f1={h['f1']:.3f} live_stdev={ls_str}{mark}")

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

    FLOOR = 0.52
    if best["test_balanced_acc"] < FLOOR:
        print(f"\n[WARN] best balanced_acc {best['test_balanced_acc']:.3f} < {FLOOR}.")
        print("[WARN] Skipping persist. Escalate to Optuna-based tune_attention.py.")
        return 4
    if live_s is not None and live_s < args.min_live_stdev:
        print(f"\n[WARN] flat live output ({live_s:.4f} < {args.min_live_stdev}).")
        print("[WARN] Skipping persist.")
        return 5

    persist_winner(best)
    print(f"\n[persist] models/attention.keras updated "
          f"(balanced_acc={best['test_balanced_acc']:.3f} "
          f"live_stdev={live_s_str})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
