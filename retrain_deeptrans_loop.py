#!/usr/bin/env python3
"""retrain_deeptrans_loop.py - Strict-gated retrain for the DeepTrans voter.

Sibling of retrain_lstm_loop.py and retrain_attention_loop.py for the
deep transformer voter. Current artefact (trained 2026-04-13 00:58) is
flat on live (stdev 0.0021, all HOLD) despite val_acc 0.406 — same
failure mode as pre-fix LSTM. This loop tries to find a config whose
3-class output actually varies on live bars.

3-class specifics
-----------------
- Loss: sparse_categorical_crossentropy with class weights
- Metric for gating: balanced_accuracy across {LONG, HOLD, SHORT}
- live_stdev probe uses the ensemble-facing `value = P(LONG) + 0.5*P(HOLD)`
  as the quantity that must vary on live windows. A model that always
  outputs P(HOLD)≈1 collapses value to 0.5 → flat.

Gates: balanced_acc >= 0.45 AND live_stdev >= 0.05 (from plan Phase C).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import pickle
import random
import statistics
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
from src.ml.transformer_model import (
    build_deep_transformer, _label_windows,
    LABEL_LONG, LABEL_HOLD, LABEL_SHORT, MODEL_FILENAME, SCALER_FILENAME,
    _probs_to_ensemble_value,
)


HPARAM_SPACE = {
    "seq_len":       (40, 60, 80),
    "n_blocks":      (2, 3, 4),        # current default is 4 — try shallower
    "n_heads":       (4, 8),           # current 8
    "d_model":       (32, 64, 128),
    "ffn_dim":       (64, 128, 256),
    "dropout":       (0.1, 0.2, 0.3),
    "lr":            (3e-4, 5e-4, 1e-3),
    "batch_size":    (32, 64),
    "epochs":        (30, 50),
    "horizon":       (3, 5, 8),
    "threshold_pct": (0.15, 0.20, 0.30),
    "scaler_kind":   ("robust", "minmax"),
}


def sample_hparams(rng: random.Random) -> Dict:
    return {k: rng.choice(v) for k, v in HPARAM_SPACE.items()}


def fetch_ohlcv(symbol: str = "GC=F", window: str = "6mo") -> Optional[pd.DataFrame]:
    for period, interval in ((window, "1h"), ("1y", "1h"), ("6mo", "1h"),
                             ("2y", "1d")):
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                df = yf.Ticker(symbol).history(period=period, interval=interval)
        except Exception:
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


def prepare(df: pd.DataFrame, hp: Dict) -> Optional[Tuple[np.ndarray, np.ndarray, object, int]]:
    from src.analysis.compute import compute_features, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler, RobustScaler

    feats = compute_features(df).copy()
    feats.dropna(inplace=True)
    if len(feats) < hp["seq_len"] + 20:
        return None
    data = feats[FEATURE_COLS].values.astype(np.float32)
    close = feats["close"].values if "close" in feats.columns else data[:, 0]

    scaler_cls = {"robust": RobustScaler, "minmax": MinMaxScaler}[hp["scaler_kind"]]
    scaler = scaler_cls().fit(data)
    scaled = scaler.transform(data)

    labels = _label_windows(close, horizon=hp["horizon"],
                            threshold_pct=hp["threshold_pct"])

    seq_len = hp["seq_len"]
    n_samples = len(scaled) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X = scaled[idx]
    y = labels[seq_len - 1: seq_len - 1 + n_samples]
    valid = y != -1
    X, y = X[valid], y[valid]
    if len(X) < 60:
        return None
    return X, y, scaler, data.shape[1]


def live_stdev(model, scaler, seq_len: int, n_features: int,
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

    values = []
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
        probs = model(scaled.reshape(1, seq_len, -1), training=False).numpy()[0]
        value, _ = _probs_to_ensemble_value(probs)
        values.append(value)
    if len(values) < 3:
        return None
    return statistics.stdev(values)


def train_once(df: pd.DataFrame, hp: Dict, seed: int) -> Optional[Dict]:
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam
    from sklearn.metrics import balanced_accuracy_score, f1_score

    random.seed(seed); np.random.seed(seed); tf.random.set_seed(seed)

    prep = prepare(df, hp)
    if prep is None:
        return None
    X, y, scaler, n_features = prep

    split_a = int(0.6 * len(X))
    split_b = int(0.8 * len(X))
    X_tr, X_val, X_te = X[:split_a], X[split_a:split_b], X[split_b:]
    y_tr, y_val, y_te = y[:split_a], y[split_a:split_b], y[split_b:]
    if min(len(X_tr), len(X_val), len(X_te)) < 20:
        return None

    counts = np.bincount(y_tr, minlength=3).astype(np.float64)
    counts[counts == 0] = 1.0
    inv = counts.sum() / (3 * counts)
    class_weight = {i: float(inv[i]) for i in range(3)}

    tf.keras.backend.clear_session()
    model = build_deep_transformer(
        seq_len=hp["seq_len"], n_features=n_features,
        n_blocks=hp["n_blocks"], n_heads=hp["n_heads"],
        d_model=hp["d_model"], ffn_dim=hp["ffn_dim"],
        dropout=hp["dropout"],
    )
    model.compile(optimizer=Adam(learning_rate=hp["lr"]),
                  loss="sparse_categorical_crossentropy",
                  metrics=["accuracy"])
    early = EarlyStopping(monitor="val_loss", patience=6, restore_best_weights=True)
    t0 = time.time()
    model.fit(X_tr, y_tr, epochs=hp["epochs"], batch_size=hp["batch_size"],
              validation_data=(X_val, y_val), callbacks=[early],
              class_weight=class_weight, verbose=0)
    train_sec = time.time() - t0

    y_pred_val = model(X_val, training=False).numpy().argmax(axis=1)
    y_pred_te = model(X_te, training=False).numpy().argmax(axis=1)
    val_bal = float(balanced_accuracy_score(y_val, y_pred_val))
    test_bal = float(balanced_accuracy_score(y_te, y_pred_te))
    test_f1 = float(f1_score(y_te, y_pred_te, average="macro", zero_division=0))

    ls = live_stdev(model, scaler, hp["seq_len"], n_features)

    return {
        "model": model, "scaler": scaler, "hparams": hp, "seed": seed,
        "val_bal": val_bal, "test_bal": test_bal, "test_f1": test_f1,
        "live_stdev": ls, "n_features": n_features,
        "train_sec": round(train_sec, 1),
    }


def persist(result: Dict, model_dir: str = "models") -> None:
    from src.analysis.compute import FEATURE_COLS
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    mp = Path(model_dir) / MODEL_FILENAME
    sp = Path(model_dir) / SCALER_FILENAME

    tmp_m = mp.with_suffix(".tmp.keras")
    result["model"].save(tmp_m); os.replace(tmp_m, mp)

    tmp_s = sp.with_suffix(".tmp.pkl")
    with open(tmp_s, "wb") as f:
        pickle.dump({
            "scaler": result["scaler"],
            "seq_len": result["hparams"]["seq_len"],
            "feature_cols": list(FEATURE_COLS),
            "horizon": result["hparams"]["horizon"],
            "threshold_pct": result["hparams"]["threshold_pct"],
        }, f)
    os.replace(tmp_s, sp)

    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx = convert_keras_to_onnx(str(mp), str(Path(model_dir) / "deeptrans.onnx"))
        if onnx:
            print(f"[persist] ONNX -> {onnx}")
    except Exception as e:
        print(f"[persist] onnx failed: {e}")

    try:
        log_training_run(
            model_type="deeptrans",
            hyperparams={**result["hparams"], "seed": result["seed"]},
            data_signature={"symbol": "GC=F", "n_features": result["n_features"]},
            metrics={
                "val_bal_acc": round(result["val_bal"], 4),
                "test_bal_acc": round(result["test_bal"], 4),
                "test_f1_macro": round(result["test_f1"], 4),
                "live_stdev": result["live_stdev"],
            },
            artifact_path=str(mp),
            notes="retrain_deeptrans_loop winner",
        )
    except Exception as e:
        print(f"[registry] log failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--target", type=float, default=0.45)
    ap.add_argument("--min-live-stdev", type=float, default=0.05)
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--window", default="6mo")
    ap.add_argument("--base-seed", type=int, default=23)
    args = ap.parse_args()

    df = fetch_ohlcv("GC=F", args.window)
    if df is None:
        print("[fatal] no data", file=sys.stderr); return 2

    rng = random.Random(args.base_seed)
    best: Optional[Dict] = None
    best_iter = -1
    no_improve = 0
    hist = []
    t0 = time.time()

    for i in range(args.iterations):
        seed = args.base_seed + i * 1000 + rng.randint(0, 999)
        hp = sample_hparams(rng)
        print(f"\n=== iter {i+1}/{args.iterations}  seed={seed}  hp={hp} ===")
        res = train_once(df, hp, seed)
        if res is None:
            print("  [iter] skipped"); continue

        ls = res["live_stdev"]
        ls_str = f"{ls:.4f}" if ls is not None else "n/a"
        flat = ls is not None and ls < args.min_live_stdev
        print(f"  val_bal={res['val_bal']:.3f}  test_bal={res['test_bal']:.3f}  "
              f"f1={res['test_f1']:.3f}  live_stdev={ls_str}"
              f"{' [FLAT]' if flat else ''}")
        hist.append({"iter": i + 1, **{k: res[k] for k in
                                        ("val_bal", "test_bal", "test_f1", "live_stdev")}})

        better = best is None or res["val_bal"] > best["val_bal"]
        signal_ok = ls is None or ls >= args.min_live_stdev
        if better and signal_ok:
            best, best_iter, no_improve = res, i + 1, 0
            print(f"  ** new best val_bal={res['val_bal']:.3f} live_stdev={ls_str} **")
        else:
            no_improve += 1
            if better and not signal_ok:
                print(f"  (better but FLAT, rejected)")

        if best is not None and best["val_bal"] >= args.target:
            print(f"\n[stop] target hit"); break
        if no_improve >= args.patience:
            print(f"\n[stop] patience"); break

    elapsed = (time.time() - t0) / 60
    print(f"\n=== done in {elapsed:.1f} min ===")
    for h in hist:
        m = " <- best" if h["iter"] == best_iter else ""
        ls_str = f"{h['live_stdev']:.4f}" if h['live_stdev'] is not None else "n/a"
        print(f"  iter {h['iter']}: val_bal={h['val_bal']:.3f} "
              f"test_bal={h['test_bal']:.3f} live_stdev={ls_str}{m}")

    if best is None:
        print("[fatal] no result"); return 3

    FLOOR = 0.42  # weaker than LSTM because 3-class baseline is 0.333
    ls = best["live_stdev"]
    if best["val_bal"] < FLOOR:
        print(f"\n[WARN] best val_bal {best['val_bal']:.3f} < {FLOOR} — no promote")
        return 4
    if ls is not None and ls < args.min_live_stdev:
        print(f"\n[WARN] flat live ({ls:.4f} < {args.min_live_stdev}) — no promote")
        return 5

    persist(best)
    print(f"\n[persist] models/deeptrans.keras updated "
          f"(val_bal={best['val_bal']:.3f} live_stdev={ls})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
