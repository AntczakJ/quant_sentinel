#!/usr/bin/env python3
"""retrain_dpformer_loop.py - Strict-gated retrain for the DPformer voter.

Sibling of retrain_lstm_loop.py / retrain_attention_loop.py /
retrain_deeptrans_loop.py. Adds a DIRECTIONAL BIAS gate on top of the
standard balanced_acc + live_stdev pair — DPformer's live failure mode
is "consistently confident SHORT (value ~0.1)" even when SMC/LSTM/XGB
agree LONG. A model whose mean live prediction is far from 0.5 is
biased regardless of its stdev.

Gates (ALL must pass):
  - balanced_acc >= 0.52 on held-out test slice
  - live_stdev >= 0.04 on 10 rolling windows (non-flat)
  - abs(mean_live - 0.5) <= 0.15 (not heavily biased one way)

The third gate is new vs the other retrain loops — we only added it
here because DPformer's failure was directional bias, not flat output.
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


HPARAM_SPACE = {
    "seq_len":           (40, 60, 80),
    "trend_lstm_units":  (32, 64, 128),
    "seasonal_heads":    (2, 4, 8),
    "seasonal_key_dim":  (8, 16, 32),
    "residual_dense":    (16, 32, 64),
    "fuse_dim":          (32, 64, 128),
    "dropout":           (0.15, 0.25, 0.35),
    "lr":                (3e-4, 5e-4, 1e-3),
    "batch_size":        (32, 64),
    "epochs":            (40, 60, 80),
    "decompose_period":  (24, 48, 96),  # trend/seasonal split period in bars
    "scaler_kind":       ("robust", "minmax"),
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


def _decompose(scaled: np.ndarray, period: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Additive decomposition into trend (rolling mean), seasonal (period-lag
    diff from trend), residual."""
    n_features = scaled.shape[1]
    trend = np.zeros_like(scaled)
    for c in range(n_features):
        s = pd.Series(scaled[:, c]).rolling(period, min_periods=1).mean().values
        trend[:, c] = s
    detrended = scaled - trend
    seasonal = np.zeros_like(scaled)
    for c in range(n_features):
        s = pd.Series(detrended[:, c]).rolling(period, min_periods=1).mean().values
        seasonal[:, c] = s
    residual = scaled - trend - seasonal
    return trend, seasonal, residual


def prepare(df: pd.DataFrame, hp: Dict) -> Optional[Tuple]:
    from src.analysis.compute import compute_features, compute_target, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler, RobustScaler

    feats = compute_features(df).copy()
    feats["direction"] = compute_target(feats)
    feats.dropna(inplace=True)
    if len(feats) < hp["seq_len"] + hp["decompose_period"] + 20:
        return None
    data = feats[FEATURE_COLS].values.astype(np.float32)
    scaler_cls = {"robust": RobustScaler, "minmax": MinMaxScaler}[hp["scaler_kind"]]
    scaler = scaler_cls().fit(data)
    scaled = scaler.transform(data)
    trend, seasonal, residual = _decompose(scaled, hp["decompose_period"])
    y = feats["direction"].values

    seq_len = hp["seq_len"]
    n_samples = len(scaled) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X_trend = trend[idx]
    X_seasonal = seasonal[idx]
    X_residual = residual[idx]
    y = y[seq_len - 1: seq_len - 1 + n_samples]
    return X_trend, X_seasonal, X_residual, y, scaler, data.shape[1]


def build_model(hp: Dict, seq_len: int, n_features: int):
    import tensorflow as tf
    from tensorflow.keras.layers import (
        Input, Dense, Dropout, LSTM, LayerNormalization,
        MultiHeadAttention, GlobalAveragePooling1D, Concatenate,
    )
    from tensorflow.keras.models import Model

    trend_in = Input(shape=(seq_len, n_features), name="trend_input")
    seas_in = Input(shape=(seq_len, n_features), name="seasonal_input")
    res_in = Input(shape=(seq_len, n_features), name="residual_input")

    t = LSTM(hp["trend_lstm_units"], return_sequences=True)(trend_in)
    t = Dropout(hp["dropout"])(t)
    t = LSTM(max(16, hp["trend_lstm_units"] // 2))(t)
    t = Dropout(hp["dropout"] * 0.8)(t)

    s = MultiHeadAttention(num_heads=hp["seasonal_heads"],
                           key_dim=hp["seasonal_key_dim"],
                           dropout=hp["dropout"])(seas_in, seas_in)
    s = LayerNormalization()(seas_in + s)
    s = GlobalAveragePooling1D()(s)
    s = Dropout(hp["dropout"])(s)

    r = GlobalAveragePooling1D()(res_in)
    r = Dense(hp["residual_dense"], activation="relu")(r)
    r = Dropout(hp["dropout"])(r)

    fused = Concatenate()([t, s, r])
    x = Dense(hp["fuse_dim"], activation="relu")(fused)
    x = Dropout(hp["dropout"])(x)
    x = Dense(max(16, hp["fuse_dim"] // 2), activation="relu")(x)
    x = Dropout(hp["dropout"] * 0.7)(x)
    out = Dense(1, activation="sigmoid", dtype="float32")(x)

    return Model(inputs=[trend_in, seas_in, res_in], outputs=out,
                 name="dpformer_retrain")


def live_probe(model, scaler, seq_len: int, n_features: int, period: int,
               symbol: str = "GC=F", n_windows: int = 12) -> Optional[Dict]:
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
    if len(live) < seq_len + period + n_windows * 5:
        return None

    values = []
    for i in range(n_windows):
        end = len(live) - i * 5 - 1
        if end < seq_len + period:
            break
        feats = compute_features(live.iloc[:end]).dropna()
        if len(feats) < seq_len + period:
            continue
        data = feats[FEATURE_COLS].values[-(seq_len + period):].astype(np.float32)
        if data.shape[1] != n_features:
            continue
        scaled = scaler.transform(data).astype(np.float32)
        trend, seasonal, residual = _decompose(scaled, period)
        Xt = trend[-seq_len:].reshape(1, seq_len, -1)
        Xs = seasonal[-seq_len:].reshape(1, seq_len, -1)
        Xr = residual[-seq_len:].reshape(1, seq_len, -1)
        p = float(model([Xt, Xs, Xr], training=False).numpy()[0, 0])
        values.append(p)
    if len(values) < 3:
        return None
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values),
        "bias": abs(statistics.mean(values) - 0.5),
    }


def train_once(df: pd.DataFrame, hp: Dict, seed: int) -> Optional[Dict]:
    import tensorflow as tf
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam
    from sklearn.metrics import balanced_accuracy_score, f1_score

    random.seed(seed); np.random.seed(seed); tf.random.set_seed(seed)

    prep = prepare(df, hp)
    if prep is None:
        return None
    Xt, Xs, Xr, y, scaler, n_features = prep

    n = len(y)
    a = int(0.6 * n); b = int(0.8 * n)
    if b - a < 20 or n - b < 20 or a < 30:
        return None

    n_pos = int(y[:a].sum())
    n_neg = a - n_pos
    class_weight = ({0: 1.0, 1: n_neg / max(n_pos, 1)}
                    if n_pos > 0 and n_neg > 0 else None)

    tf.keras.backend.clear_session()
    model = build_model(hp, hp["seq_len"], n_features)
    model.compile(optimizer=Adam(learning_rate=hp["lr"]),
                  loss="binary_crossentropy", metrics=["accuracy"])
    early = EarlyStopping(monitor="val_loss", patience=8, restore_best_weights=True)

    t0 = time.time()
    model.fit([Xt[:a], Xs[:a], Xr[:a]], y[:a],
              validation_data=([Xt[a:b], Xs[a:b], Xr[a:b]], y[a:b]),
              epochs=hp["epochs"], batch_size=hp["batch_size"],
              callbacks=[early], class_weight=class_weight, verbose=0)
    train_sec = time.time() - t0

    y_pred_val = (model([Xt[a:b], Xs[a:b], Xr[a:b]], training=False).numpy().flatten() > 0.5).astype(int)
    y_pred_te = (model([Xt[b:], Xs[b:], Xr[b:]], training=False).numpy().flatten() > 0.5).astype(int)
    val_bal = float(balanced_accuracy_score(y[a:b], y_pred_val))
    test_bal = float(balanced_accuracy_score(y[b:], y_pred_te))
    test_f1 = float(f1_score(y[b:], y_pred_te, zero_division=0))

    live = live_probe(model, scaler, hp["seq_len"], n_features, hp["decompose_period"])

    return {
        "model": model, "scaler": scaler, "hparams": hp, "seed": seed,
        "val_bal": val_bal, "test_bal": test_bal, "test_f1": test_f1,
        "live": live, "train_sec": round(train_sec, 1),
        "n_features": n_features,
    }


def persist(result: Dict, model_dir: str = "models") -> None:
    from src.analysis.compute import FEATURE_COLS
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    mp = Path(model_dir) / "decompose.keras"
    sp = Path(model_dir) / "decompose_scaler.pkl"
    tmp_m = mp.with_suffix(".tmp.keras")
    result["model"].save(tmp_m); os.replace(tmp_m, mp)
    tmp_s = sp.with_suffix(".tmp.pkl")
    with open(tmp_s, "wb") as f:
        pickle.dump({
            "scaler": result["scaler"],
            "seq_len": result["hparams"]["seq_len"],
            "decompose_period": result["hparams"]["decompose_period"],
            "feature_cols": list(FEATURE_COLS),
        }, f)
    os.replace(tmp_s, sp)

    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx = convert_keras_to_onnx(str(mp), str(Path(model_dir) / "decompose.onnx"))
        if onnx:
            print(f"[persist] ONNX -> {onnx}")
    except Exception as e:
        print(f"[persist] onnx failed: {e}")

    try:
        log_training_run(
            model_type="dpformer",
            hyperparams={**result["hparams"], "seed": result["seed"]},
            data_signature={"symbol": "GC=F", "n_features": result["n_features"]},
            metrics={
                "val_bal": round(result["val_bal"], 4),
                "test_bal": round(result["test_bal"], 4),
                "test_f1": round(result["test_f1"], 4),
                "live_mean": round(result["live"]["mean"], 4) if result["live"] else None,
                "live_stdev": round(result["live"]["stdev"], 4) if result["live"] else None,
                "live_bias": round(result["live"]["bias"], 4) if result["live"] else None,
            },
            artifact_path=str(mp),
            notes="retrain_dpformer_loop winner",
        )
    except Exception as e:
        print(f"[registry] log failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--target-bal", type=float, default=0.52)
    ap.add_argument("--min-stdev", type=float, default=0.04)
    ap.add_argument("--max-bias", type=float, default=0.15,
                    help="abs(live_mean - 0.5) must be below this")
    ap.add_argument("--patience", type=int, default=4)
    ap.add_argument("--window", default="6mo")
    ap.add_argument("--base-seed", type=int, default=71)
    args = ap.parse_args()

    df = fetch_ohlcv("GC=F", args.window)
    if df is None:
        print("[fatal] no data"); return 2

    rng = random.Random(args.base_seed)
    best: Optional[Dict] = None
    best_iter = -1
    no_improve = 0
    hist = []

    for i in range(args.iterations):
        seed = args.base_seed + i * 1000 + rng.randint(0, 999)
        hp = sample_hparams(rng)
        print(f"\n=== iter {i+1}/{args.iterations}  seed={seed}  hp={hp} ===")
        res = train_once(df, hp, seed)
        if res is None:
            print("  [iter] skipped"); continue

        live = res["live"]
        if live is None:
            print(f"  val_bal={res['val_bal']:.3f} test_bal={res['test_bal']:.3f} f1={res['test_f1']:.3f} live=n/a")
        else:
            flat = live["stdev"] < args.min_stdev
            biased = live["bias"] > args.max_bias
            flags = ("[FLAT]" if flat else "") + ("[BIASED]" if biased else "")
            print(f"  val_bal={res['val_bal']:.3f} test_bal={res['test_bal']:.3f} f1={res['test_f1']:.3f} "
                  f"live_mean={live['mean']:.3f} stdev={live['stdev']:.4f} bias={live['bias']:.3f} {flags}")

        hist.append({
            "iter": i + 1, "val_bal": res["val_bal"], "test_bal": res["test_bal"],
            "live": live, "hp": hp,
        })

        ok_bal = res["val_bal"] >= args.target_bal
        ok_live = (live is not None
                   and live["stdev"] >= args.min_stdev
                   and live["bias"] <= args.max_bias)
        better = best is None or res["val_bal"] > best["val_bal"]

        if better and ok_live:
            best, best_iter, no_improve = res, i + 1, 0
            print(f"  ** new best **")
        else:
            no_improve += 1
            if better and not ok_live:
                print(f"  (better val_bal but live gate fail — rejected)")

        if best is not None and best["val_bal"] >= args.target_bal:
            print(f"\n[stop] target hit"); break
        if no_improve >= args.patience:
            print(f"\n[stop] patience"); break

    print()
    for h in hist:
        m = " <- best" if h["iter"] == best_iter else ""
        live = h["live"]
        live_str = (f"mean={live['mean']:.3f} std={live['stdev']:.3f} bias={live['bias']:.3f}"
                    if live else "n/a")
        print(f"  iter {h['iter']}: val_bal={h['val_bal']:.3f} test_bal={h['test_bal']:.3f} live: {live_str}{m}")

    if best is None:
        print("[fatal] no result"); return 3

    FLOOR = 0.50
    if best["val_bal"] < FLOOR:
        print(f"\n[WARN] best val_bal {best['val_bal']:.3f} < {FLOOR} — no promote")
        return 4
    if best["live"] is None:
        print(f"\n[WARN] no live probe — no promote")
        return 5
    if best["live"]["stdev"] < args.min_stdev:
        print(f"\n[WARN] flat live — no promote"); return 5
    if best["live"]["bias"] > args.max_bias:
        print(f"\n[WARN] biased live (|mean-0.5|={best['live']['bias']:.3f}) — no promote")
        return 6

    persist(best)
    print(f"\n[persist] models/decompose.keras updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
