"""src/ml/transformer_model.py - Deep pre-LN Transformer voter ("deeptrans").

A deeper, more regularized transformer than the existing `attention_model`
(TFT-lite). Used as a 7th voter in the ensemble behind a feature flag so
production behavior is unchanged until explicitly enabled.

Distinctions from `attention_model`
-----------------------------------
- 4-6 pre-LN transformer blocks (attention + position-wise FFN + residual)
  vs. attention's 2 bare multi-head attention layers.
- Sinusoidal positional encoding (attention model has none).
- 3-class softmax head (LONG / HOLD / SHORT) vs. binary sigmoid, giving
  the ensemble a true "no opinion" output it can respect.
- Heavier dropout on each block for the overfit gap.

Feature flag
------------
Set `QUANT_ENABLE_TRANSFORMER=1` to activate. When unset, `predict_deeptrans`
returns None without loading any artifact, and the ensemble marks the
voter as unavailable (same path as a missing model file).

Outputs
-------
`predict_deeptrans(df) -> Optional[float]` in [0, 1], where:

    value = P(LONG) + 0.5 * P(HOLD)

so a pure-HOLD prediction lands on the ensemble's 0.5 neutral point, and
the voter naturally abstains on uncertain windows. The ensemble computes
its own confidence as `abs(value - 0.5) * 2`, which is monotonic in the
class margin.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from src.core.logger import logger


FLAG_ENV = "QUANT_ENABLE_TRANSFORMER"

MODEL_NAME = "deeptrans"
MODEL_FILENAME = "deeptrans.keras"
SCALER_FILENAME = "deeptrans_scaler.pkl"
ONNX_FILENAME = "deeptrans.onnx"

# Model defaults — can be overridden per-call.
DEFAULT_SEQ_LEN = 60
DEFAULT_N_BLOCKS = 4
DEFAULT_N_HEADS = 8
DEFAULT_D_MODEL = 64
DEFAULT_FFN_DIM = 128
DEFAULT_DROPOUT = 0.15

# Target labels for 3-class: LONG, HOLD, SHORT.
LABEL_LONG = 0
LABEL_HOLD = 1
LABEL_SHORT = 2


def is_enabled() -> bool:
    """True iff the feature flag is set to 1 in the environment."""
    return os.environ.get(FLAG_ENV) == "1"


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

def _sinusoidal_positional_encoding(seq_len: int, d_model: int) -> np.ndarray:
    """Classic Transformer positional encoding. Float32 so it's cheap to add."""
    pos = np.arange(seq_len)[:, None]
    i = np.arange(d_model)[None, :]
    angle = pos / np.power(10000.0, (2 * (i // 2)) / d_model)
    pe = np.zeros((seq_len, d_model), dtype=np.float32)
    pe[:, 0::2] = np.sin(angle[:, 0::2])
    pe[:, 1::2] = np.cos(angle[:, 1::2])
    return pe


def build_deep_transformer(seq_len: int,
                           n_features: int,
                           n_blocks: int = DEFAULT_N_BLOCKS,
                           n_heads: int = DEFAULT_N_HEADS,
                           d_model: int = DEFAULT_D_MODEL,
                           ffn_dim: int = DEFAULT_FFN_DIM,
                           dropout: float = DEFAULT_DROPOUT):
    """Pre-LN transformer encoder stack -> global average pool -> 3-class head.

    Pre-LN (LayerNorm BEFORE the sublayer) is the modern default: trains
    reliably without elaborate warmup schedules. Residual connections wrap
    both attention and FFN sublayers within each block.
    """
    import tensorflow as tf
    from tensorflow.keras.layers import (
        Input, Dense, Dropout, LayerNormalization,
        MultiHeadAttention, GlobalAveragePooling1D, Add,
    )
    from tensorflow.keras.models import Model

    inp = Input(shape=(seq_len, n_features), name="input")

    # Project raw features up to d_model, then add positional encoding.
    x = Dense(d_model, activation=None, name="input_proj")(inp)
    pe = _sinusoidal_positional_encoding(seq_len, d_model)
    x = Add(name="pos_add")([x, tf.constant(pe[None, :, :], dtype=tf.float32)])

    for b in range(n_blocks):
        # --- Attention sublayer (pre-LN) ---
        n1 = LayerNormalization(name=f"b{b}_ln1")(x)
        attn = MultiHeadAttention(
            num_heads=n_heads, key_dim=max(4, d_model // n_heads),
            dropout=dropout, name=f"b{b}_attn",
        )(n1, n1)
        x = Add(name=f"b{b}_add1")([x, attn])

        # --- FFN sublayer (pre-LN) ---
        n2 = LayerNormalization(name=f"b{b}_ln2")(x)
        ffn = Dense(ffn_dim, activation="gelu", name=f"b{b}_ffn1")(n2)
        ffn = Dropout(dropout, name=f"b{b}_drop")(ffn)
        ffn = Dense(d_model, activation=None, name=f"b{b}_ffn2")(ffn)
        x = Add(name=f"b{b}_add2")([x, ffn])

    x = LayerNormalization(name="final_ln")(x)
    pooled = GlobalAveragePooling1D(name="pool")(x)
    head = Dense(64, activation="relu", name="head1")(pooled)
    head = Dropout(dropout, name="head_drop")(head)
    logits = Dense(3, activation="softmax", dtype="float32", name="probs")(head)

    return Model(inputs=inp, outputs=logits, name=MODEL_NAME)


# ---------------------------------------------------------------------------
# Labeling — convert future return to {LONG, HOLD, SHORT}
# ---------------------------------------------------------------------------

def _label_windows(close: np.ndarray,
                   horizon: int = 5,
                   threshold_pct: float = 0.2) -> np.ndarray:
    """Assign a class to each bar based on the forward return over `horizon`
    bars: LONG if > +threshold_pct, SHORT if < -threshold_pct, else HOLD.

    threshold_pct in percent (0.2 = 20bps). The trailing `horizon` bars get
    label -1 (invalid — caller must drop them).
    """
    n = len(close)
    labels = np.full(n, -1, dtype=np.int64)
    for i in range(n - horizon):
        fwd = (close[i + horizon] - close[i]) / close[i] * 100.0
        if fwd > threshold_pct:
            labels[i] = LABEL_LONG
        elif fwd < -threshold_pct:
            labels[i] = LABEL_SHORT
        else:
            labels[i] = LABEL_HOLD
    return labels


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train_deep_transformer(df,
                           model_dir: str = "models",
                           seq_len: int = DEFAULT_SEQ_LEN,
                           n_blocks: int = DEFAULT_N_BLOCKS,
                           horizon: int = 5,
                           threshold_pct: float = 0.2,
                           epochs: int = 40,
                           batch_size: int = 32) -> Tuple[Optional[object], float]:
    """Train the deep transformer on OHLCV. Returns (model, val_accuracy).

    The function is intentionally self-contained: it does not consult the
    ensemble feature flag. Operators train the model offline; the flag
    only gates INFERENCE.
    """
    from src.analysis.compute import compute_features, FEATURE_COLS
    from sklearn.preprocessing import MinMaxScaler
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam

    if len(df) < seq_len + horizon + 50:
        logger.warning(f"[{MODEL_NAME}] insufficient data: {len(df)} rows")
        return None, 0.0

    feats = compute_features(df).copy()
    feats.dropna(inplace=True)
    if len(feats) < seq_len + horizon + 10:
        logger.warning(f"[{MODEL_NAME}] insufficient after feature compute")
        return None, 0.0

    data = feats[FEATURE_COLS].values.astype(np.float32)
    n_features = data.shape[1]

    # Labels: forward return over horizon bars on the raw close.
    close = feats["close"].values if "close" in feats.columns else data[:, 0]
    labels = _label_windows(close, horizon=horizon, threshold_pct=threshold_pct)

    # Valid range: sequences whose END bar still has a non-invalid label,
    # i.e. label available for the END index.
    n_samples = len(data) - seq_len
    if n_samples <= 0:
        return None, 0.0

    # P1.2 fix (audit docs/strategy/2026-04-29_audit_1_data_leaks.md):
    # Defer scaler.fit until AFTER the time-ordered train/val split so val
    # statistics do not leak into the training transform. The final scaler
    # saved for inference IS fit on the full training data (no leak there;
    # inference uses a fair-ish snapshot).
    n_features_count = data.shape[1]

    # Vectorised rolling windows on RAW unscaled data.
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X_raw = data[idx]
    # Label of the LAST bar of each window. Drop samples where label == -1.
    y = labels[seq_len - 1: seq_len - 1 + n_samples]
    valid = y != -1
    X_raw = X_raw[valid]
    y = y[valid]

    if len(X_raw) < 40:
        logger.warning(f"[{MODEL_NAME}] too few valid samples ({len(X_raw)})")
        return None, 0.0

    # Class balance: HOLD usually dominates — compute class weights.
    counts = np.bincount(y, minlength=3).astype(np.float64)
    counts[counts == 0] = 1.0  # avoid div-by-zero
    inv_freq = counts.sum() / (3 * counts)
    class_weight = {i: float(inv_freq[i]) for i in range(3)}

    # 80/20 time-ordered split (no shuffle) — performed on RAW windows.
    split = int(0.8 * len(X_raw))
    X_tr_raw, X_val_raw = X_raw[:split], X_raw[split:]
    y_tr, y_val = y[:split], y[split:]

    # Fit scaler on TRAIN portion only; transform val with train stats.
    train_scaler = MinMaxScaler()
    train_scaler.fit(X_tr_raw.reshape(-1, n_features_count))
    X_tr = train_scaler.transform(
        X_tr_raw.reshape(-1, n_features_count)
    ).reshape(X_tr_raw.shape).astype(np.float32)
    X_val = train_scaler.transform(
        X_val_raw.reshape(-1, n_features_count)
    ).reshape(X_val_raw.shape).astype(np.float32)

    # Refit a SEPARATE scaler on the full training data for inference use.
    scaler = MinMaxScaler()
    scaler.fit(data)

    model = build_deep_transformer(seq_len=seq_len, n_features=n_features,
                                   n_blocks=n_blocks)
    model.compile(optimizer=Adam(learning_rate=3e-4),
                  loss="sparse_categorical_crossentropy",
                  metrics=["accuracy"])

    early = EarlyStopping(monitor="val_loss", patience=8,
                          restore_best_weights=True)
    history = model.fit(
        X_tr, y_tr, epochs=epochs, batch_size=batch_size,
        validation_data=(X_val, y_val),
        callbacks=[early], class_weight=class_weight, verbose=0,
    )
    val_acc = float(max(history.history.get("val_accuracy", [0.0])))

    Path(model_dir).mkdir(parents=True, exist_ok=True)
    # Atomic writes.
    model_path = Path(model_dir) / MODEL_FILENAME
    tmp = model_path.with_suffix(".tmp.keras")
    model.save(tmp)
    os.replace(tmp, model_path)

    scaler_path = Path(model_dir) / SCALER_FILENAME
    tmp = scaler_path.with_suffix(".tmp.pkl")
    with open(tmp, "wb") as f:
        pickle.dump({"scaler": scaler, "seq_len": seq_len,
                     "feature_cols": list(FEATURE_COLS),
                     "horizon": horizon,
                     "threshold_pct": threshold_pct}, f)
    os.replace(tmp, scaler_path)

    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param(f"{MODEL_NAME}_val_accuracy", val_acc)
    except Exception:
        pass

    logger.info(f"[{MODEL_NAME}] trained on {len(X_tr)} samples "
                f"val_acc={val_acc:.3f} (HOLD-weighted loss)")
    return model, val_acc


# ---------------------------------------------------------------------------
# Predict
# ---------------------------------------------------------------------------

_runtime_cache: dict = {"keras": None, "scaler": None, "seq_len": None,
                        "feature_cols": None}


def _load_artifacts(model_dir: str) -> bool:
    """Lazy-load the Keras model + scaler. Returns True on success."""
    model_path = Path(model_dir) / MODEL_FILENAME
    scaler_path = Path(model_dir) / SCALER_FILENAME
    if not model_path.exists() or not scaler_path.exists():
        return False
    if _runtime_cache["keras"] is not None:
        return True
    try:
        from tensorflow.keras.models import load_model
        with open(scaler_path, "rb") as f:
            blob = pickle.load(f)
        _runtime_cache["keras"] = load_model(str(model_path), compile=False)
        _runtime_cache["scaler"] = blob["scaler"]
        _runtime_cache["seq_len"] = int(blob["seq_len"])
        _runtime_cache["feature_cols"] = list(blob["feature_cols"])
        return True
    except Exception as e:
        logger.warning(f"[{MODEL_NAME}] load failed: {e}")
        return False


def _probs_to_ensemble_value(probs: np.ndarray) -> Tuple[float, float]:
    """Map 3-class softmax to the ensemble's (value, confidence) pair.

    value     = P(LONG) + 0.5 * P(HOLD)   -> [0, 1], 0.5 == neutral
    confidence = |P(LONG) - P(SHORT)|      -> margin between the directional
                                             probs; HOLD abstention lowers it
    """
    p_long = float(probs[LABEL_LONG])
    p_hold = float(probs[LABEL_HOLD])
    p_short = float(probs[LABEL_SHORT])
    value = p_long + 0.5 * p_hold
    confidence = abs(p_long - p_short)
    return value, confidence


def predict_deeptrans(df, model_dir: str = "models") -> Optional[float]:
    """Ensemble-facing predictor. Returns None if disabled or unavailable."""
    if not is_enabled():
        return None
    if not _load_artifacts(model_dir):
        return None

    from src.analysis.compute import compute_features

    seq_len = _runtime_cache["seq_len"]
    feature_cols = _runtime_cache["feature_cols"]
    scaler = _runtime_cache["scaler"]
    model = _runtime_cache["keras"]

    try:
        feats = compute_features(df)
        if len(feats) < seq_len:
            return None
        data = feats[feature_cols].values[-seq_len:].astype(np.float32)
    except Exception as e:
        logger.debug(f"[{MODEL_NAME}] feature compute failed: {e}")
        return None

    try:
        scaled = scaler.transform(data).astype(np.float32)
    except Exception as e:
        logger.debug(f"[{MODEL_NAME}] scaler transform failed: {e}")
        return None

    X = scaled.reshape(1, seq_len, -1)
    try:
        probs = model(X, training=False).numpy()[0]
    except Exception as e:
        logger.debug(f"[{MODEL_NAME}] inference failed: {e}")
        return None

    value, _ = _probs_to_ensemble_value(probs)
    return value


def predict_deeptrans_detailed(df, model_dir: str = "models") -> Optional[dict]:
    """Full prediction payload for diagnostics. Respects the feature flag.

    Returned keys: value, confidence, p_long, p_hold, p_short.
    """
    if not is_enabled():
        return None
    if not _load_artifacts(model_dir):
        return None

    from src.analysis.compute import compute_features

    seq_len = _runtime_cache["seq_len"]
    feature_cols = _runtime_cache["feature_cols"]
    scaler = _runtime_cache["scaler"]
    model = _runtime_cache["keras"]

    feats = compute_features(df)
    if len(feats) < seq_len:
        return None
    data = feats[feature_cols].values[-seq_len:].astype(np.float32)
    scaled = scaler.transform(data).astype(np.float32)
    probs = model(scaled.reshape(1, seq_len, -1), training=False).numpy()[0]
    value, confidence = _probs_to_ensemble_value(probs)
    return {
        "value": value, "confidence": confidence,
        "p_long": float(probs[LABEL_LONG]),
        "p_hold": float(probs[LABEL_HOLD]),
        "p_short": float(probs[LABEL_SHORT]),
    }


def reset_cache() -> None:
    """Drop cached artifacts. Used by tests that simulate reloads."""
    _runtime_cache["keras"] = None
    _runtime_cache["scaler"] = None
    _runtime_cache["seq_len"] = None
    _runtime_cache["feature_cols"] = None
