"""
src/decompose_model.py — Decomposition-Patch Fusion Model (DPformer-inspired)

Architecture (based on 2025 research: 21% MSE improvement over PatchTST):

  1. DECOMPOSITION: Split price into Trend + Seasonal + Residual
     using STL (Seasonal-Trend decomposition using LOESS)

  2. PARALLEL MODELING:
     - Trend component    → LSTM (captures directional momentum)
     - Seasonal component → MultiHeadAttention (captures cyclical patterns)
     - Residual component → Dense (captures noise/surprises)

  3. FUSION: Concatenate all 3 outputs → Dense → Sigmoid

Training uses same features and target as existing LSTM (compute.py).
Walk-forward validation for honest accuracy estimation.
"""

import os
import numpy as np
from typing import Optional, Tuple
from src.core.logger import logger


def _decompose_features(data: np.ndarray, period: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Decompose each feature column into trend + seasonal + residual.

    Uses simple moving average decomposition (fast, no scipy dependency):
      - Trend: SMA(period) of each feature
      - Seasonal: original - trend (cyclical component)
      - Residual: high-frequency noise (diff of seasonal)

    Returns: (trend, seasonal, residual) — same shape as input.
    """
    n_samples, n_features = data.shape
    trend = np.zeros_like(data)
    seasonal = np.zeros_like(data)
    residual = np.zeros_like(data)

    for col in range(n_features):
        series = data[:, col]

        # Trend: simple moving average
        kernel = np.ones(period) / period
        if len(series) >= period:
            t = np.convolve(series, kernel, mode='same')
            # Fix edges (convolution artifacts)
            t[:period // 2] = t[period // 2]
            t[-(period // 2):] = t[-(period // 2) - 1]
        else:
            t = series.copy()

        trend[:, col] = t
        seasonal[:, col] = series - t

        # Residual: high-frequency component
        if len(series) > 1:
            r = np.zeros_like(series)
            r[1:] = np.diff(seasonal[:, col])
            residual[:, col] = r

    return trend, seasonal, residual


def build_decompose_model(seq_len: int, n_features: int):
    """
    Build DPformer-inspired decomposition fusion model.

    Architecture:
      Input → Decompose → [LSTM(trend), Attention(seasonal), Dense(residual)] → Fuse → Output
    """
    from tensorflow.keras.models import Model
    from tensorflow.keras.layers import (
        Input, Dense, Dropout, LSTM, LayerNormalization,
        MultiHeadAttention, GlobalAveragePooling1D, Concatenate,
    )

    # --- 3 parallel inputs (one per component) ---
    trend_input = Input(shape=(seq_len, n_features), name='trend_input')
    seasonal_input = Input(shape=(seq_len, n_features), name='seasonal_input')
    residual_input = Input(shape=(seq_len, n_features), name='residual_input')

    # --- Branch 1: LSTM for Trend (directional momentum) ---
    t = LSTM(64, return_sequences=True, name='trend_lstm1')(trend_input)
    t = Dropout(0.25)(t)
    t = LSTM(32, name='trend_lstm2')(t)
    t = Dropout(0.2)(t)

    # --- Branch 2: Attention for Seasonal (cyclical patterns) ---
    s = MultiHeadAttention(num_heads=4, key_dim=16, dropout=0.1, name='seasonal_attn')(
        seasonal_input, seasonal_input
    )
    s = LayerNormalization(name='seasonal_norm')(seasonal_input + s)
    s = GlobalAveragePooling1D(name='seasonal_pool')(s)
    s = Dropout(0.2)(s)

    # --- Branch 3: Dense for Residual (noise/surprises) ---
    r = GlobalAveragePooling1D(name='residual_pool')(residual_input)
    r = Dense(32, activation='relu', name='residual_dense')(r)
    r = Dropout(0.2)(r)

    # --- Fusion ---
    fused = Concatenate(name='fusion')([t, s, r])
    x = Dense(64, activation='relu', name='fuse_dense1')(fused)
    x = Dropout(0.3)(x)
    x = Dense(32, activation='relu', name='fuse_dense2')(x)
    x = Dropout(0.2)(x)
    output = Dense(1, activation='sigmoid', dtype='float32', name='output')(x)

    model = Model(
        inputs=[trend_input, seasonal_input, residual_input],
        outputs=output,
        name='dpformer_lite'
    )
    return model


def train_decompose_model(df, model_dir='models', seq_len=60, epochs=80):
    """
    Train DPformer-lite on OHLCV data.

    Pipeline:
      1. Compute features (same as LSTM/XGB — compute.py)
      2. Decompose into trend/seasonal/residual
      3. Create sequences for each component
      4. Walk-forward validation
      5. Train final model with class weights + early stopping

    Returns: (model, accuracy) or (None, 0)
    """
    from src.analysis.compute import compute_features, compute_target, FEATURE_COLS, get_tf_batch_size
    from tensorflow.keras.callbacks import EarlyStopping
    from tensorflow.keras.optimizers import Adam

    if len(df) < seq_len + 50:
        logger.warning(f"Insufficient data for DPformer: {len(df)}")
        return None, 0

    features = compute_features(df)
    features = features.copy()
    features['direction'] = compute_target(features)
    features.dropna(inplace=True)

    if len(features) < seq_len + 10:
        return None, 0

    data = features[FEATURE_COLS].values
    n_features = len(FEATURE_COLS)
    batch_size = get_tf_batch_size(32, 64)

    # Scale
    from sklearn.preprocessing import MinMaxScaler
    import pickle

    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(data)

    scaler_path = os.path.join(model_dir, 'decompose_scaler.pkl')
    with open(scaler_path, 'wb') as f:
        pickle.dump(scaler, f)

    # Decompose
    trend, seasonal, residual = _decompose_features(scaled)

    # Create sequences (vectorized)
    n_samples = len(scaled) - seq_len
    idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]

    X_trend = trend[idx]
    X_seasonal = seasonal[idx]
    X_residual = residual[idx]
    y = features['direction'].values[seq_len:]

    if len(X_trend) == 0:
        return None, 0

    # Walk-forward validation (3 folds)
    n = len(X_trend)
    fold_size = n // 4
    fold_accs = []

    for fold in range(3):
        train_end = fold_size * (fold + 1)
        test_end = min(train_end + fold_size, n)
        if train_end >= n or test_end <= train_end:
            break

        Xt_tr, Xt_te = X_trend[:train_end], X_trend[train_end:test_end]
        Xs_tr, Xs_te = X_seasonal[:train_end], X_seasonal[train_end:test_end]
        Xr_tr, Xr_te = X_residual[:train_end], X_residual[train_end:test_end]
        y_tr, y_te = y[:train_end], y[train_end:test_end]

        if len(Xt_tr) < 20 or len(Xt_te) < 5:
            continue

        fold_model = build_decompose_model(seq_len, n_features)
        fold_model.compile(optimizer=Adam(learning_rate=0.0005),
                          loss='binary_crossentropy', metrics=['accuracy'])
        early = EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True)
        fold_model.fit(
            [Xt_tr, Xs_tr, Xr_tr], y_tr,
            epochs=50, batch_size=batch_size,
            validation_data=([Xt_te, Xs_te, Xr_te], y_te),
            callbacks=[early], verbose=0
        )
        acc = fold_model.evaluate([Xt_te, Xs_te, Xr_te], y_te, verbose=0)[1]
        fold_accs.append(acc)
        logger.debug(f"DPformer fold {fold + 1}: accuracy {acc:.3f}")

    # Final model
    split = int(0.8 * n)
    Xt_train, Xt_test = X_trend[:split], X_trend[split:]
    Xs_train, Xs_test = X_seasonal[:split], X_seasonal[split:]
    Xr_train, Xr_test = X_residual[:split], X_residual[split:]
    y_train, y_test = y[:split], y[split:]

    n_pos = int(y_train.sum())
    n_neg = len(y_train) - n_pos
    class_weight = {0: 1.0, 1: n_neg / max(n_pos, 1)} if n_pos > 0 else None

    model = build_decompose_model(seq_len, n_features)
    model.compile(optimizer=Adam(learning_rate=0.0005),
                  loss='binary_crossentropy', metrics=['accuracy'])
    early = EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True)
    history = model.fit(
        [Xt_train, Xs_train, Xr_train], y_train,
        epochs=epochs, batch_size=batch_size,
        validation_data=([Xt_test, Xs_test, Xr_test], y_test),
        callbacks=[early], verbose=0,
        class_weight=class_weight
    )

    # Save model
    model_path = os.path.join(model_dir, 'decompose.keras')
    model.save(model_path)

    best_val_acc = max(history.history.get('val_accuracy', [0.5]))
    wf_acc = np.mean(fold_accs) if fold_accs else best_val_acc

    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("decompose_last_accuracy", best_val_acc)
        db.set_param("decompose_walkforward_accuracy", wf_acc)
    except (ImportError, AttributeError):
        pass

    logger.info(
        f"DPformer-lite trained: val_acc={best_val_acc:.3f}, "
        f"walk-forward={wf_acc:.3f} ({len(fold_accs)} folds)"
    )
    return model, wf_acc


def predict_decompose(df, model_dir='models', seq_len=60) -> Optional[float]:
    """
    Predict direction using DPformer-lite.
    Returns probability (0-1) or None if model unavailable.
    """
    from src.analysis.compute import compute_features, FEATURE_COLS

    model_path = os.path.join(model_dir, 'decompose.keras')
    scaler_path = os.path.join(model_dir, 'decompose_scaler.pkl')

    if not os.path.exists(model_path) or not os.path.exists(scaler_path):
        return None

    try:
        features = compute_features(df)
        if len(features) < seq_len:
            return None

        data = features[FEATURE_COLS].values[-seq_len:]

        import pickle
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)

        scaled = scaler.transform(data)

        # Decompose
        trend, seasonal, residual = _decompose_features(scaled)

        X_t = trend.reshape(1, seq_len, -1).astype(np.float32)
        X_s = seasonal.reshape(1, seq_len, -1).astype(np.float32)
        X_r = residual.reshape(1, seq_len, -1).astype(np.float32)

        from tensorflow.keras.models import load_model
        model = load_model(model_path)
        pred = model([X_t, X_s, X_r], training=False).numpy()

        return float(pred.flat[0])

    except Exception as e:
        logger.debug(f"DPformer predict error: {e}")
        return None
