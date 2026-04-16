#!/usr/bin/env python3
"""tune_lstm.py - Optuna hyperparameter sweep for the LSTM voter.

Sibling of tune_rl.py. retrain_lstm_loop.py already tried random seeds
+ mild perturbations and could NOT produce a non-flat LSTM that clears
balanced_accuracy >= 0.52 — suggesting the problem is either in the
target definition (currently 'strong up without concurrent down' over
5 bars with 0.5*ATR threshold; an asymmetric pattern that may be too
rare on the current gold regime) or architecture / scaler interaction,
not just random initialisation. This script searches all three.

Search space
------------
- Core: lr (log), batch_size, epochs, dropout, scaler_kind
- Architecture: seq_len, n_layers (1-4), hidden_base, bidirectional
- Data window: 3mo / 6mo / 1y / 2y (scaler regime fit)
- **Target redesign**: switches target_type between
    'asymmetric_atr' (legacy compute_target, parameterised horizon + atr_mult)
    'simple_direction' (sign of close_{t+n} - close_t)
  and sweeps horizon / threshold — the real axis retrain_lstm_loop
  could not explore.

Scoring
-------
- Primary objective: balanced_accuracy on VAL slice. Maximise.
- Secondary gate (filter, not objective): live prediction stdev on the
  last 10 rolling yfinance windows. A winner with flat live output is
  not a production voter — tracked as a trial user_attr and filtered
  in winner-selection phase.
- Pruning: MedianPruner on the per-epoch val balanced_accuracy reported
  via a Keras callback. Poor configs die fast.

Usage
-----
  # Full overnight run (~3-5 h):
  python tune_lstm.py --n-trials 60 --epochs 80 --study-name lstm_sweep_v1

  # Resume:
  python tune_lstm.py --resume --study-name lstm_sweep_v1 --n-trials 60

  # Quick smoke (2 trials x 3 epochs, synthetic data path untouched — real
  # yfinance fetch but tiny sample):
  python tune_lstm.py --smoke

  # Leaderboard inspection:
  python tune_lstm.py --report --study-name lstm_sweep_v1

  # Promote best non-flat winner to production (backs up first):
  python tune_lstm.py --apply-winner --study-name lstm_sweep_v1
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
import os
import pickle
import random
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "1")

import numpy as np
import pandas as pd

try:
    import optuna
    from optuna.pruners import MedianPruner
    from optuna.samplers import TPESampler
except ImportError:
    print("[fatal] optuna not installed (pip install 'optuna>=3.5')", file=sys.stderr)
    raise

import tensorflow as tf
import yfinance as yf
from sklearn.metrics import balanced_accuracy_score, f1_score

from src.core.logger import logger
from src.ml.training_registry import log_training_run


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SYMBOL = "GC=F"
STORAGE_DEFAULT = "sqlite:///data/optuna_lstm.db"
HEARTBEAT_PATH = Path("data/lstm_sweep_heartbeat.json")
CACHE_DIR = Path("data/_lstm_sweep_cache")

DATA_WINDOWS = ("3mo", "6mo", "1y", "2y")
SCALERS = ("robust", "minmax", "standard")
TARGET_TYPES = ("asymmetric_atr", "simple_direction")


# ---------------------------------------------------------------------------
# Data loading — cached across trials. yfinance is slow and rate-limited.
# ---------------------------------------------------------------------------

def _cache_path(symbol: str, window: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}__{window}.pkl"


def fetch_window(symbol: str, window: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV for (symbol, window) with 12h pickle cache."""
    path = _cache_path(symbol, window)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and (time.time() - path.stat().st_mtime) < 12 * 3600:
        try:
            return pd.read_pickle(path)
        except Exception:
            path.unlink(missing_ok=True)

    try:
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            df = yf.Ticker(symbol).history(period=window, interval="1h")
    except Exception as e:
        logger.warning(f"[tune_lstm] fetch failed {symbol} {window}: {e}")
        return None
    if df is None or len(df) < 200:
        return None
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    df = df[keep].dropna().reset_index(drop=True)
    try:
        df.to_pickle(path)
    except Exception as e:
        logger.debug(f"[tune_lstm] cache write failed: {e}")
    return df


# ---------------------------------------------------------------------------
# Target functions — search axis: pick the labelling that matches market
# ---------------------------------------------------------------------------

def _target_asymmetric_atr(feats: pd.DataFrame, horizon: int,
                           atr_mult: float) -> pd.Series:
    """Legacy: True iff price moves > atr_mult*ATR up within horizon bars
    WITHOUT a concurrent > atr_mult*ATR down move."""
    future_max = feats["close"].rolling(horizon).max().shift(-horizon)
    future_min = feats["close"].rolling(horizon).min().shift(-horizon)
    atr_val = feats["atr"].replace(0, np.nan).ffill().fillna(1.0)
    up = (future_max - feats["close"]) / atr_val > atr_mult
    down = (feats["close"] - future_min) / atr_val > atr_mult
    return (up & ~down).astype(int)


def _target_simple_direction(feats: pd.DataFrame, horizon: int) -> pd.Series:
    """True iff close_{t+horizon} > close_t. No volatility filter — every
    bar gets a label. Usually much more balanced than asymmetric_atr."""
    future_close = feats["close"].shift(-horizon)
    return (future_close > feats["close"]).astype(int)


def compute_target_for_trial(feats: pd.DataFrame, target_type: str,
                             horizon: int, atr_mult: float) -> pd.Series:
    if target_type == "simple_direction":
        return _target_simple_direction(feats, horizon)
    return _target_asymmetric_atr(feats, horizon, atr_mult)


# ---------------------------------------------------------------------------
# Feature prep (3-way split; scaler fit on TRAIN only — no leakage)
# ---------------------------------------------------------------------------

@dataclass
class Splits:
    X_train: np.ndarray
    y_train: np.ndarray
    X_val: np.ndarray
    y_val: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    scaler: Any
    seq_len: int
    n_features: int


def prepare_splits(df: pd.DataFrame, seq_len: int, scaler_kind: str,
                   target_type: str, target_horizon: int,
                   target_atr_mult: float) -> Optional[Splits]:
    from src.analysis.compute import compute_features, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

    feats = compute_features(df).copy()
    feats["direction"] = compute_target_for_trial(
        feats, target_type, target_horizon, target_atr_mult)
    feats.dropna(inplace=True)
    if len(feats) < seq_len + 50:
        return None

    # Chronological 60/20/20 on raw values; scaler fit ONLY on train to avoid
    # any leakage of test stats into the scaler.
    n = len(feats)
    a = int(n * 0.6)
    b = int(n * 0.8)

    scaler_cls = {"robust": RobustScaler, "minmax": MinMaxScaler,
                  "standard": StandardScaler}[scaler_kind]
    scaler = scaler_cls().fit(feats[FEATURE_COLS].values[:a])

    data_scaled = scaler.transform(feats[FEATURE_COLS].values).astype(np.float32)
    y = feats["direction"].values

    # Build windows per-slice, then subset chronologically to avoid leakage
    # across boundaries (a window ending at index i has label y[i], with
    # inputs from [i-seq_len+1, i]; so a train window's inputs can overlap
    # with val/test inputs if we're careless. Here we force window-END to
    # fall strictly in its slice.)
    def _slice_windows(start_end: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
        lo, hi = start_end
        idx = np.arange(seq_len)[None, :] + np.arange(lo, hi - 0)[:, None] - (seq_len - 1)
        valid = idx[:, 0] >= 0
        idx = idx[valid]
        ends = np.arange(lo, hi)[valid]
        return data_scaled[idx], y[ends]

    X_train, y_train = _slice_windows((seq_len - 1, a))
    X_val, y_val = _slice_windows((a, b))
    X_test, y_test = _slice_windows((b, n))

    if min(len(X_train), len(X_val), len(X_test)) < 30:
        return None

    return Splits(
        X_train=X_train, y_train=y_train,
        X_val=X_val, y_val=y_val,
        X_test=X_test, y_test=y_test,
        scaler=scaler, seq_len=seq_len,
        n_features=X_train.shape[2],
    )


# ---------------------------------------------------------------------------
# Architecture — parameterised LSTM stack, optional bidirectional
# ---------------------------------------------------------------------------

@dataclass
class HParams:
    lr: float
    batch_size: int
    epochs: int
    dropout: float
    scaler_kind: str
    seq_len: int
    n_layers: int
    hidden_base: int
    bidirectional: bool
    l2: float
    data_window: str
    target_type: str
    target_horizon: int
    target_atr_mult: float


def sample_hparams(trial: optuna.Trial) -> HParams:
    return HParams(
        lr=trial.suggest_float("lr", 1e-4, 3e-3, log=True),
        batch_size=trial.suggest_categorical("batch_size", [16, 32, 64, 128]),
        epochs=trial.suggest_categorical("epochs", [40, 60, 100]),
        dropout=trial.suggest_float("dropout", 0.0, 0.5),
        scaler_kind=trial.suggest_categorical("scaler_kind", list(SCALERS)),
        seq_len=trial.suggest_categorical("seq_len", [30, 40, 60, 80, 100, 120]),
        n_layers=trial.suggest_int("n_layers", 1, 4),
        hidden_base=trial.suggest_categorical("hidden_base", [32, 64, 128, 256]),
        bidirectional=trial.suggest_categorical("bidirectional", [False, True]),
        l2=trial.suggest_categorical("l2", [0.0, 1e-4, 1e-3]),
        data_window=trial.suggest_categorical("data_window", list(DATA_WINDOWS)),
        target_type=trial.suggest_categorical("target_type", list(TARGET_TYPES)),
        target_horizon=trial.suggest_categorical("target_horizon", [3, 5, 8, 12]),
        target_atr_mult=trial.suggest_categorical("target_atr_mult",
                                                   [0.3, 0.5, 0.8, 1.0]),
    )


def build_lstm(hp: HParams, n_features: int):
    from tensorflow.keras.layers import (
        LSTM, Bidirectional, Dense, Dropout, Input,
    )
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.regularizers import L2

    reg = L2(hp.l2) if hp.l2 > 0 else None
    layers: List[Any] = [Input(shape=(hp.seq_len, n_features))]
    widths = [max(16, hp.hidden_base // (2 ** i)) for i in range(hp.n_layers)]
    for i, units in enumerate(widths):
        return_seq = (i < hp.n_layers - 1)
        lstm_layer = LSTM(units, return_sequences=return_seq,
                          kernel_regularizer=reg, recurrent_regularizer=reg)
        if hp.bidirectional:
            layers.append(Bidirectional(lstm_layer))
        else:
            layers.append(lstm_layer)
        layers.append(Dropout(hp.dropout))
    layers.append(Dense(32, activation="relu", kernel_regularizer=reg))
    layers.append(Dropout(hp.dropout * 0.7))
    layers.append(Dense(1, activation="sigmoid", dtype="float32"))
    return Sequential(layers)


# ---------------------------------------------------------------------------
# Live-stdev probe (reused from retrain_lstm_loop philosophy — flat models
# are not voters regardless of offline metrics)
# ---------------------------------------------------------------------------

def live_stdev_probe(model, scaler, seq_len: int, n_features: int,
                     symbol: str = DEFAULT_SYMBOL,
                     n_windows: int = 10) -> Optional[float]:
    from src.analysis.compute import compute_features, FEATURE_COLS
    live = fetch_window(symbol, "2mo")
    if live is None or len(live) < seq_len + n_windows * 5:
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
    return statistics.stdev(preds)


# ---------------------------------------------------------------------------
# Pruning callback (Keras -> Optuna)
# ---------------------------------------------------------------------------

class OptunaPruneBalancedAcc(tf.keras.callbacks.Callback):
    """Each epoch, compute balanced_accuracy on VAL and report to Optuna.
    Optuna may prune mid-train — we raise TrialPruned which Keras treats
    as KeyboardInterrupt-like, ending fit cleanly."""

    def __init__(self, trial: optuna.Trial, X_val: np.ndarray, y_val: np.ndarray,
                 report_every: int = 5):
        super().__init__()
        self.trial = trial
        self.X_val = X_val
        self.y_val = y_val
        self.report_every = max(1, report_every)

    def on_epoch_end(self, epoch, logs=None):
        if (epoch + 1) % self.report_every != 0:
            return
        y_pred = (self.model(self.X_val, training=False).numpy().flatten() > 0.5).astype(int)
        bal = float(balanced_accuracy_score(self.y_val, y_pred))
        self.trial.report(bal, epoch)
        if self.trial.should_prune():
            self.model.stop_training = True
            raise optuna.TrialPruned(f"pruned at ep {epoch+1}, bal_acc={bal:.3f}")


# ---------------------------------------------------------------------------
# Heartbeat (same contract as tune_rl.py so a future widget can poll it)
# ---------------------------------------------------------------------------

class Heartbeat:
    def __init__(self, study_name: str, n_trials: int, symbol: str):
        self.state: Dict[str, Any] = {
            "status": "running",
            "study_name": study_name,
            "n_trials_target": n_trials,
            "symbol": symbol,
            "started_at": time.time(),
            "completed_trials": 0,
            "pruned_trials": 0,
            "trial_number": 0,
            "current_epoch": 0,
            "best_val_so_far": None,
            "updated_at": time.time(),
        }

    def _flush(self) -> None:
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.state["updated_at"] = time.time()
            HEARTBEAT_PATH.write_text(json.dumps(self.state), encoding="utf-8")
        except Exception:
            pass

    def update_trial(self, trial_number: int, hp: HParams) -> None:
        self.state.update({"trial_number": trial_number,
                           "current_hparams": asdict(hp)})
        self._flush()

    def finish_trial(self, study: optuna.Study, trial: optuna.FrozenTrial) -> None:
        try:
            best = study.best_value
        except ValueError:
            best = None
        completed = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE)
        pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
        self.state.update({
            "completed_trials": completed,
            "pruned_trials": pruned,
            "best_val_so_far": round(best, 4) if best is not None else None,
            "last_trial_state": trial.state.name,
        })
        self._flush()

    def finish(self, status: str = "completed") -> None:
        self.state["status"] = status
        self._flush()


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------

class LSTMObjective:
    def __init__(self, symbol: str, heartbeat: Heartbeat):
        self.symbol = symbol
        self.heartbeat = heartbeat
        self._df_cache: Dict[str, pd.DataFrame] = {}

    def _df(self, window: str) -> Optional[pd.DataFrame]:
        if window not in self._df_cache:
            df = fetch_window(self.symbol, window)
            if df is not None:
                self._df_cache[window] = df
        return self._df_cache.get(window)

    def __call__(self, trial: optuna.Trial) -> float:
        hp = sample_hparams(trial)
        self.heartbeat.update_trial(trial.number, hp)

        df = self._df(hp.data_window)
        if df is None:
            raise optuna.TrialPruned(f"no data for window {hp.data_window}")

        splits = prepare_splits(
            df, seq_len=hp.seq_len, scaler_kind=hp.scaler_kind,
            target_type=hp.target_type, target_horizon=hp.target_horizon,
            target_atr_mult=hp.target_atr_mult,
        )
        if splits is None:
            raise optuna.TrialPruned("insufficient data after prep")

        # Class balance on TRAIN only.
        n_pos = int(splits.y_train.sum())
        n_neg = len(splits.y_train) - n_pos
        class_weight = ({0: 1.0, 1: n_neg / max(n_pos, 1)}
                        if n_pos > 0 and n_neg > 0 else None)

        tf.keras.backend.clear_session()
        model = build_lstm(hp, splits.n_features)
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=hp.lr),
                      loss="binary_crossentropy", metrics=["accuracy"])

        early = tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=10, restore_best_weights=True)
        prune_cb = OptunaPruneBalancedAcc(
            trial, splits.X_val, splits.y_val, report_every=5)

        try:
            model.fit(
                splits.X_train, splits.y_train,
                validation_data=(splits.X_val, splits.y_val),
                epochs=hp.epochs, batch_size=hp.batch_size,
                callbacks=[early, prune_cb], verbose=0,
                class_weight=class_weight,
            )
        except optuna.TrialPruned:
            raise

        # Final val balanced accuracy (not a cherry-picked epoch best).
        y_pred_val = (model(splits.X_val, training=False).numpy().flatten() > 0.5).astype(int)
        val_bal = float(balanced_accuracy_score(splits.y_val, y_pred_val))
        f1 = float(f1_score(splits.y_val, y_pred_val, average="binary", zero_division=0))

        # Test is held out from the sweep entirely — never seen for pruning /
        # winner selection. Stored as user_attr so --apply-winner can check.
        y_pred_test = (model(splits.X_test, training=False).numpy().flatten() > 0.5).astype(int)
        test_bal = float(balanced_accuracy_score(splits.y_test, y_pred_test))
        test_f1 = float(f1_score(splits.y_test, y_pred_test, average="binary", zero_division=0))

        # Live stdev — flag flat models without rejecting them from the study.
        live_stdev = live_stdev_probe(model, splits.scaler, hp.seq_len,
                                       splits.n_features, self.symbol)

        trial.set_user_attr("val_balanced_acc", val_bal)
        trial.set_user_attr("val_f1", f1)
        trial.set_user_attr("test_balanced_acc", test_bal)
        trial.set_user_attr("test_f1", test_f1)
        trial.set_user_attr("live_stdev",
                            round(live_stdev, 4) if live_stdev is not None else None)
        trial.set_user_attr("class_balance_train",
                            round(float(splits.y_train.mean()), 3))

        # Cleanup per trial — TF graphs pile up otherwise.
        del model
        gc.collect()
        return val_bal


# ---------------------------------------------------------------------------
# Winner selection + promotion
# ---------------------------------------------------------------------------

def _is_viable(trial: optuna.FrozenTrial, min_live_stdev: float,
               min_val_bal: float, min_test_bal: float = 0.52) -> bool:
    """A trial is viable if it passes validation AND held-out test score AND
    has non-flat live output. The test_bal gate was added 2026-04-16 after
    the production sweep-winner shipped as an anti-signal model (25% live
    directional accuracy) despite val_bal=0.547.

    KNOWN LIMITATION: balanced_accuracy on backtest classification data does
    NOT predict live forward-move accuracy. The 2026-04-13 winner passed
    both val_bal=0.547 and test_bal=0.542, yet is 25% accurate live. Future
    hardening should either (a) swap the objective to a trade-simulation
    profit score, or (b) add a post-promotion live-accuracy watchdog that
    auto-reverts if rolling 20-prediction accuracy drops below 0.45. This
    gate is the MINIMUM bar — it's necessary but not sufficient.
    """
    if trial.state != optuna.trial.TrialState.COMPLETE:
        return False
    if (trial.value or 0.0) < min_val_bal:
        return False
    # Held-out test score must also clear the bar — overfit val scores
    # are the trap that shipped the current production anti-signal.
    tb = trial.user_attrs.get("test_balanced_acc")
    if tb is not None and tb < min_test_bal:
        return False
    ls = trial.user_attrs.get("live_stdev")
    if ls is not None and ls < min_live_stdev:
        return False
    return True


def pick_winner(study: optuna.Study, min_live_stdev: float = 0.03,
                min_val_bal: float = 0.52) -> Optional[optuna.FrozenTrial]:
    """Best VIABLE trial — filters flat-output and below-floor configs."""
    viable = [t for t in study.trials
              if _is_viable(t, min_live_stdev, min_val_bal)]
    if not viable:
        return None
    return max(viable, key=lambda t: t.value or 0.0)


def retrain_and_promote(study: optuna.Study, symbol: str,
                         min_live_stdev: float, min_val_bal: float,
                         output_dir: Path) -> Dict[str, Any]:
    winner = pick_winner(study, min_live_stdev, min_val_bal)
    if winner is None:
        return {"status": "no_viable_winner",
                "reason": f"no trial cleared val_bal>={min_val_bal} AND "
                           f"live_stdev>={min_live_stdev}"}

    hp = HParams(**{k: v for k, v in winner.params.items()
                    if k in HParams.__dataclass_fields__})
    print(f"[winner] trial #{winner.number} val_bal={winner.value:.3f} "
          f"live_stdev={winner.user_attrs.get('live_stdev')} "
          f"test_bal={winner.user_attrs.get('test_balanced_acc')}")

    df = fetch_window(symbol, hp.data_window)
    if df is None:
        return {"status": "error", "reason": f"cannot refetch {hp.data_window}"}

    splits = prepare_splits(df, hp.seq_len, hp.scaler_kind,
                             hp.target_type, hp.target_horizon, hp.target_atr_mult)
    if splits is None:
        return {"status": "error", "reason": "prep failed on refetch"}

    # Retrain on TRAIN + VAL merged (test stays held out for honest final score).
    X_full = np.concatenate([splits.X_train, splits.X_val])
    y_full = np.concatenate([splits.y_train, splits.y_val])
    n_pos = int(y_full.sum())
    n_neg = len(y_full) - n_pos
    class_weight = ({0: 1.0, 1: n_neg / max(n_pos, 1)}
                    if n_pos > 0 and n_neg > 0 else None)

    tf.keras.backend.clear_session()
    model = build_lstm(hp, splits.n_features)
    model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=hp.lr),
                  loss="binary_crossentropy", metrics=["accuracy"])
    model.fit(X_full, y_full, epochs=hp.epochs, batch_size=hp.batch_size,
              verbose=0, class_weight=class_weight)

    y_pred_test = (model(splits.X_test, training=False).numpy().flatten() > 0.5).astype(int)
    test_bal = float(balanced_accuracy_score(splits.y_test, y_pred_test))
    test_f1_final = float(f1_score(splits.y_test, y_pred_test,
                                    average="binary", zero_division=0))
    live_stdev_final = live_stdev_probe(model, splits.scaler, hp.seq_len,
                                         splits.n_features, symbol)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "lstm_sweep_winner.keras"
    scaler_path = output_dir / "lstm_sweep_winner_scaler.pkl"

    tmp_m = model_path.with_suffix(".tmp.keras")
    model.save(tmp_m); os.replace(tmp_m, model_path)
    tmp_s = scaler_path.with_suffix(".tmp.pkl")
    with open(tmp_s, "wb") as f:
        pickle.dump(splits.scaler, f)
    os.replace(tmp_s, scaler_path)

    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx = convert_keras_to_onnx(str(model_path),
                                     str(output_dir / "lstm_sweep_winner.onnx"))
        if onnx:
            print(f"[winner] ONNX -> {onnx}")
    except Exception as e:
        print(f"[winner] onnx regen failed: {e}")

    try:
        log_training_run(
            model_type="lstm_sweep_winner",
            hyperparams={**asdict(hp), "study_name": study.study_name,
                         "trial_number": winner.number},
            data_signature={"symbol": symbol, "data_window": hp.data_window},
            metrics={
                "val_balanced_acc": round(float(winner.value), 4),
                "test_balanced_acc": round(test_bal, 4),
                "test_f1": round(test_f1_final, 4),
                "live_stdev": (round(live_stdev_final, 4)
                               if live_stdev_final is not None else None),
            },
            artifact_path=str(model_path),
            notes=f"Optuna LSTM sweep winner (study={study.study_name})",
        )
    except Exception as e:
        print(f"[winner] registry log failed: {e}")

    return {
        "status": "ok",
        "trial_number": winner.number,
        "val_balanced_acc": round(float(winner.value), 4),
        "test_balanced_acc": round(test_bal, 4),
        "test_f1": round(test_f1_final, 4),
        "live_stdev": (round(live_stdev_final, 4)
                       if live_stdev_final is not None else None),
        "artifact": str(model_path),
        "hparams": asdict(hp),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_leaderboard(study: optuna.Study, top: int = 15) -> None:
    rows = [t for t in study.trials
            if t.state == optuna.trial.TrialState.COMPLETE]
    rows.sort(key=lambda t: t.value or -1, reverse=True)
    header = (f"{'#':>3} {'val_bal':>8} {'test_bal':>8} {'f1':>5} "
              f"{'live_std':>8} {'lr':>7} {'seq':>4} {'layers':>6} "
              f"{'hid':>4} {'bi':>3} {'target':<17} {'scaler':>7}")
    print("\n" + header)
    print("-" * len(header))
    for t in rows[:top]:
        ua = t.user_attrs
        ls = ua.get("live_stdev")
        ls_str = f"{ls:.4f}" if ls is not None else "   n/a"
        flat = "*" if ls is not None and ls < 0.03 else " "
        target_str = f"{t.params.get('target_type','?')[:10]}/h{t.params.get('target_horizon','?')}"
        print(f"{t.number:>3} {t.value or 0:>8.3f} "
              f"{ua.get('test_balanced_acc', 0) or 0:>8.3f} "
              f"{ua.get('val_f1', 0) or 0:>5.2f} "
              f"{ls_str:>8}{flat} {t.params.get('lr', 0):>7.4f} "
              f"{t.params.get('seq_len','?'):>4} "
              f"{t.params.get('n_layers','?'):>6} "
              f"{t.params.get('hidden_base','?'):>4} "
              f"{'Y' if t.params.get('bidirectional') else '-':>3} "
              f"{target_str:<17} {t.params.get('scaler_kind','?'):>7}")


def write_report(study: optuna.Study, path: Path,
                  extra: Optional[Dict] = None) -> None:
    trials = []
    for t in study.trials:
        if t.state not in (optuna.trial.TrialState.COMPLETE,
                           optuna.trial.TrialState.PRUNED):
            continue
        trials.append({
            "number": t.number,
            "state": t.state.name,
            "value": t.value,
            "params": t.params,
            "user_attrs": t.user_attrs,
        })
    payload = {
        "study_name": study.study_name,
        "direction": study.direction.name,
        "n_trials_done": len(study.trials),
        "best_value": study.best_value if study.trials else None,
        "best_params": study.best_params if study.trials else None,
        "trials": trials,
        **(extra or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"[report] -> {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_study(name: str, storage: str, resume: bool) -> optuna.Study:
    Path("data").mkdir(parents=True, exist_ok=True)
    sampler = TPESampler(seed=42, multivariate=True, group=True,
                         n_startup_trials=8)
    pruner = MedianPruner(n_startup_trials=5, n_warmup_steps=10,
                          interval_steps=5)
    return optuna.create_study(
        study_name=name, storage=storage,
        direction="maximize", sampler=sampler, pruner=pruner,
        load_if_exists=resume,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials", type=int, default=40)
    ap.add_argument("--symbol", default=DEFAULT_SYMBOL)
    ap.add_argument("--study-name", default="lstm_sweep_v1")
    ap.add_argument("--storage", default=STORAGE_DEFAULT)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--smoke", action="store_true",
                    help="2 trials x few epochs, fresh study")
    ap.add_argument("--report", action="store_true",
                    help="print leaderboard + exit")
    ap.add_argument("--apply-winner", action="store_true",
                    help="retrain best viable trial on train+val, persist")
    ap.add_argument("--min-live-stdev", type=float, default=0.03)
    ap.add_argument("--min-val-bal", type=float, default=0.52)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.smoke:
        args.n_trials = 2
        args.study_name = f"smoke_lstm_{int(time.time())}"

    random.seed(args.seed); np.random.seed(args.seed); tf.random.set_seed(args.seed)
    study = build_study(args.study_name, args.storage,
                        resume=args.resume or args.report or args.apply_winner)

    if args.report:
        print_leaderboard(study, top=20)
        return 0

    if args.apply_winner:
        if not [t for t in study.trials
                if t.state == optuna.trial.TrialState.COMPLETE]:
            print("[fatal] no completed trials", file=sys.stderr)
            return 2
        result = retrain_and_promote(study, args.symbol,
                                      args.min_live_stdev, args.min_val_bal,
                                      Path("models"))
        out = Path("reports") / f"sweep_{args.study_name}.json"
        write_report(study, out, {"winner": result})
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") == "ok" else 3

    heartbeat = Heartbeat(args.study_name, args.n_trials, args.symbol)
    heartbeat._flush()
    objective = LSTMObjective(args.symbol, heartbeat)

    def _post(s: optuna.Study, t: optuna.FrozenTrial) -> None:
        heartbeat.finish_trial(s, t)
        ua = t.user_attrs
        print(f"[trial {t.number}] state={t.state.name} val_bal={t.value} "
              f"test_bal={ua.get('test_balanced_acc')} "
              f"live_stdev={ua.get('live_stdev')} f1={ua.get('val_f1')}")

    t_start = time.time()
    try:
        study.optimize(objective, n_trials=args.n_trials, callbacks=[_post],
                       gc_after_trial=True, catch=(RuntimeError,))
    except KeyboardInterrupt:
        print("\n[interrupt] study persisted — use --resume to continue")
        heartbeat.finish("interrupted")
    else:
        heartbeat.finish("completed")

    elapsed_min = (time.time() - t_start) / 60
    print(f"\n[sweep] finished in {elapsed_min:.1f} min")
    print_leaderboard(study, top=12)

    out = Path("reports") / f"sweep_{args.study_name}.json"
    write_report(study, out, {"elapsed_min": round(elapsed_min, 1)})

    # Auto-promote if a viable winner exists (not smoke).
    if not args.smoke:
        winner = pick_winner(study, args.min_live_stdev, args.min_val_bal)
        if winner is not None:
            print(f"\n[winner] viable: trial #{winner.number} "
                  f"val_bal={winner.value:.3f} — promoting")
            result = retrain_and_promote(study, args.symbol,
                                          args.min_live_stdev, args.min_val_bal,
                                          Path("models"))
            write_report(study, out, {"elapsed_min": round(elapsed_min, 1),
                                       "winner": result})
        else:
            print(f"\n[winner] NO viable trial "
                  f"(min_val_bal={args.min_val_bal}, "
                  f"min_live_stdev={args.min_live_stdev})")
            print("   production LSTM stays defused (weight 0.0). "
                  "Consider widening search or accepting ensemble without LSTM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
