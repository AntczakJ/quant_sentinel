"""
attention_model.py — Lightweight Temporal Fusion Transformer (TFT-lite).

Uzupelnia LSTM o mechanizm attention — lepsze wychwytywanie dlugoterminowych
zaleznosci w danych cenowych XAU/USD.

Architektura:
  Input(seq_len, features) -> MultiHeadAttention -> LayerNorm -> Dense -> Sigmoid

Przewaga nad LSTM:
  - Attention waży kazdy bar w sekwencji dynamicznie (LSTM zapomina po ~30 barach)
  - Zloto ma cykle 4-8h — attention naturalnie je wychwytuje
  - Szybszy trening (brak rekurencji)
"""

import numpy as np
import os
from src.core.logger import logger


def build_attention_model(seq_len: int, n_features: int):
    """Build TFT-lite model: MultiHeadAttention + Dense layers."""
    from tensorflow.keras.models import Model
    from tensorflow.keras.layers import (
        Input, Dense, Dropout, LayerNormalization,
        MultiHeadAttention, GlobalAveragePooling1D, Concatenate
    )

    inp = Input(shape=(seq_len, n_features), name='input')

    # Multi-head self-attention (4 heads)
    attn_out = MultiHeadAttention(
        num_heads=4, key_dim=16, dropout=0.1, name='self_attention'
    )(inp, inp)

    # Residual connection + LayerNorm
    x = LayerNormalization(name='norm1')(inp + attn_out)

    # Second attention layer for deeper pattern capture
    attn2 = MultiHeadAttention(
        num_heads=2, key_dim=8, dropout=0.1, name='attention2'
    )(x, x)
    x = LayerNormalization(name='norm2')(x + attn2)

    # Aggregate: use both last-step output and global average
    last_step = x[:, -1, :]  # most recent bar
    avg_pool = GlobalAveragePooling1D(name='avg_pool')(x)
    merged = Concatenate(name='merge')([last_step, avg_pool])

    # Classification head
    x = Dense(64, activation='relu', name='dense1')(merged)
    x = Dropout(0.3)(x)
    x = Dense(32, activation='relu', name='dense2')(x)
    x = Dropout(0.2)(x)
    output = Dense(1, activation='sigmoid', dtype='float32', name='output')(x)

    model = Model(inputs=inp, outputs=output, name='tft_lite')
    return model


def train_attention_model(df, model_dir=None, seq_len=60, usdjpy_df=None):
    """Train TFT-lite model on OHLCV data.

    Uses same features and target as LSTM (from compute.py).
    Returns (model, accuracy) or (None, 0).

    2026-05-02 audit: model_dir defaults to env QUANT_TRAIN_OUTPUT_DIR or
    'models'. Set the env var before training to a non-production path
    (e.g., models/short_2026-05-02/) to prevent accidental overwrite of
    live weights. Inference path still hardcodes 'models' — the override
    is training-only.
    """
    if model_dir is None:
        model_dir = os.environ.get('QUANT_TRAIN_OUTPUT_DIR', 'models')
    from src.analysis.compute import compute_features, compute_target, FEATURE_COLS, get_tf_batch_size
    # Accept usdjpy_df so training picks up macro features if provided by caller
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam

    if len(df) < seq_len + 50:
        logger.warning(f"Za malo danych do trenowania Attention: {len(df)}")
        return None, 0

    features = compute_features(df, usdjpy_df=usdjpy_df)
    features = features.copy()
    features['direction'] = compute_target(features)
    features.dropna(inplace=True)

    if len(features) < seq_len + 10:
        return None, 0

    data = features[FEATURE_COLS].values
    n_features = len(FEATURE_COLS)
    batch_size = get_tf_batch_size(32, 64)

    # P1.2 fix (audit docs/strategy/2026-04-29_audit_1_data_leaks.md):
    # Build sliding-window indices on RAW unscaled data — scaling now done
    # per-fold inside the walk-forward loop to prevent val-fold statistics
    # from leaking into the train scaler fit.
    from sklearn.preprocessing import MinMaxScaler
    import pickle

    n_samples = len(data) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]
    X_raw = data[idx]  # UNSCALED — scaled per fold below
    y = features['direction'].values[seq_len:]

    if len(X_raw) == 0:
        return None, 0

    # Walk-forward validation (3 folds — faster than 5) — scaler per fold
    n = len(X_raw)
    fold_size = n // 4
    fold_accs = []

    for fold in range(3):
        train_end = fold_size * (fold + 1)
        test_end = min(train_end + fold_size, n)
        if train_end >= n or test_end <= train_end:
            break
        X_tr_raw, X_te_raw = X_raw[:train_end], X_raw[train_end:test_end]
        y_tr, y_te = y[:train_end], y[train_end:test_end]
        if len(X_tr_raw) < 20 or len(X_te_raw) < 5:
            continue

        # Fit scaler on TRAIN-fold only; transform val with train stats.
        fold_scaler = MinMaxScaler()
        fold_scaler.fit(X_tr_raw.reshape(-1, n_features))
        X_tr = fold_scaler.transform(
            X_tr_raw.reshape(-1, n_features)
        ).reshape(X_tr_raw.shape)
        X_te = fold_scaler.transform(
            X_te_raw.reshape(-1, n_features)
        ).reshape(X_te_raw.shape)

        fold_model = build_attention_model(seq_len, n_features)
        fold_model.compile(
            optimizer=Adam(learning_rate=0.0005),
            loss='binary_crossentropy', metrics=['accuracy']
        )
        early = EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True)
        fold_model.fit(
            X_tr, y_tr, epochs=50, batch_size=batch_size,
            validation_data=(X_te, y_te), callbacks=[early], verbose=0
        )
        acc = fold_model.evaluate(X_te, y_te, verbose=0)[1]
        fold_accs.append(acc)
        logger.debug(f"Attention fold {fold+1}: accuracy {acc:.3f}")

    # Final model: refit scaler on FULL training data (used for inference).
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(data)
    scaler_path = os.path.join(model_dir, 'attention_scaler.pkl')
    scaler_tmp = scaler_path + '.tmp'
    with open(scaler_tmp, 'wb') as f:
        pickle.dump(scaler, f)
    os.replace(scaler_tmp, scaler_path)

    X = scaled[idx]
    split = int(0.8 * len(X))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    n_pos = int(y_train.sum())
    n_neg = len(y_train) - n_pos
    class_weight = {0: 1.0, 1: n_neg / max(n_pos, 1)} if n_pos > 0 else None

    model = build_attention_model(seq_len, n_features)
    model.compile(
        optimizer=Adam(learning_rate=0.0005),
        loss='binary_crossentropy', metrics=['accuracy']
    )
    early = EarlyStopping(monitor='val_loss', patience=12, restore_best_weights=True)
    history = model.fit(
        X_train, y_train, epochs=80, batch_size=batch_size,
        validation_data=(X_test, y_test), callbacks=[early], verbose=0,
        class_weight=class_weight
    )

    # Save (atomic write)
    model_path = os.path.join(model_dir, 'attention.keras')
    # Keras 3 rejects .tmp suffix on save — keep .keras extension on tmp path
    model_tmp = model_path.replace('.keras', '.tmp.keras')
    model.save(model_tmp)
    os.replace(model_tmp, model_path)

    best_val_acc = max(history.history.get('val_accuracy', [0.5]))
    wf_acc = np.mean(fold_accs) if fold_accs else best_val_acc

    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("attention_last_accuracy", best_val_acc)
        db.set_param("attention_walkforward_accuracy", wf_acc)
    except Exception:
        pass

    logger.info(
        f"Attention (TFT-lite) trained: val_acc={best_val_acc:.3f}, "
        f"walk-forward={wf_acc:.3f} ({len(fold_accs)} folds)"
    )
    return model, wf_acc


def predict_attention(df, model_dir='models', seq_len=60, usdjpy_df=None):
    """Predict direction using TFT-lite model. Returns probability (0-1) or None.

    usdjpy_df: optional live USDJPY for macro features. If None, caller should
    fetch via _fetch_live_usdjpy() in ensemble_models.py (or features default to 0).
    """
    from src.analysis.compute import compute_features, FEATURE_COLS

    model_path = os.path.join(model_dir, 'attention.keras')
    scaler_path = os.path.join(model_dir, 'attention_scaler.pkl')

    if not os.path.exists(model_path) or not os.path.exists(scaler_path):
        return None

    try:
        # Try ONNX GPU first
        onnx_path = os.path.join(model_dir, 'attention.onnx')
        from src.analysis.compute import detect_gpu, convert_keras_to_onnx, get_onnx_session, onnx_predict
        gpu_info = detect_gpu()

        if gpu_info["onnx_directml"]:
            if not os.path.exists(onnx_path) or \
               os.path.getmtime(onnx_path) < os.path.getmtime(model_path):
                convert_keras_to_onnx(model_path, onnx_path)

            if os.path.exists(onnx_path):
                session = get_onnx_session(onnx_path)
                if session:
                    # Auto-detect seq_len from ONNX
                    inp_shape = session.get_inputs()[0].shape
                    if len(inp_shape) >= 2 and isinstance(inp_shape[1], int):
                        seq_len = inp_shape[1]
    except Exception:
        session = None

    features = compute_features(df, usdjpy_df=usdjpy_df)
    if len(features) < seq_len:
        return None

    data = features[FEATURE_COLS].values[-seq_len:]

    import pickle
    with open(scaler_path, 'rb') as f:
        scaler = pickle.load(f)

    # Defensive: scaler-feature mismatch = train/inference split. Per 2026-05-04 audit.
    scaler_n = getattr(scaler, "n_features_in_", None)
    if scaler_n is not None and scaler_n != data.shape[1]:
        logger.error(
            f"Attention scaler n_features={scaler_n} != input n_features={data.shape[1]} "
            f"— scaler from older training, retrain. Skipping voter."
        )
        return None
    scaled = scaler.transform(data)
    X = scaled.reshape(1, seq_len, -1).astype(np.float32)

    # ONNX GPU inference
    try:
        if session is not None:
            pred = onnx_predict(session, X)
            if pred is not None:
                return float(pred.flat[0])
    except Exception:
        pass

    # Fallback: Keras
    try:
        from tensorflow.keras.models import load_model
        model = load_model(model_path)
        pred = model(X, training=False).numpy()
        if isinstance(pred, np.ndarray):
            return float(pred.flat[0])
    except Exception as e:
        logger.debug(f"Attention predict error: {e}")

    return None
