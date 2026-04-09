"""
ml_models.py — modele LSTM i XGBoost do prognozowania kierunku.

Ulepszenia:
- Rozszerzony zestaw cech (Williams %R, CCI, Ichimoku, candlestick patterns)
- Walk-forward validation zamiast prostego train_test_split
- Persystencja metryk do bazy danych
- GPU/CPU acceleration via centralized compute module
"""

import pandas as pd
import numpy as np
import os
import pickle
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from src.core.logger import logger
from src.analysis.compute import (
    detect_gpu, get_xgb_params, get_tf_batch_size,
    compute_features, compute_target, FEATURE_COLS,
)

# ── GPU / TF / XGBoost configuration (centralized) ───────────────────
_GPU_INFO = detect_gpu()
_TF_GPU = _GPU_INFO["tf_gpu"]
_XGB_PARAMS = get_xgb_params()

class MLPredictor:
    def __init__(self, model_dir='models'):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        self.xgb = None
        self.lstm = None
        self.scaler = MinMaxScaler()
        self._feature_cache_id = None   # id(df) of cached features
        self._feature_cache = None      # cached result

    def _features(self, df):
        """Compute ML features. Delegates to centralized compute_features().
        Cached: repeated calls on same df return instantly."""
        return compute_features(df)

    def train_xgb(self, df, precomputed_features=None):
        """Trenowanie XGBoost z walk-forward validation.
        Accepts precomputed_features to avoid recomputing indicators.

        Target: czy cena wzrośnie o >0.5 ATR w ciągu następnych 5 świec
        (zamiast prostego next-candle direction, które jest szumem).
        """
        features = precomputed_features if precomputed_features is not None else self._features(df)

        # --- ULEPSZONY TARGET: istotny ruch zamiast next-candle noise ---
        features['direction'] = compute_target(features)

        features.dropna(inplace=True)
        if len(features) < 50:
            logger.warning("Za mało danych do trenowania XGBoost (min 50)")
            return None

        X = features[FEATURE_COLS]
        y = features['direction']

        # Class weights — kompensacja nierównomiernej dystrybucji
        n_pos = y.sum()
        n_neg = len(y) - n_pos
        scale_pos_weight = n_neg / max(n_pos, 1)

        # Walk-forward validation: 5 foldów
        n = len(X)
        fold_size = n // 6  # 1/6 na test, przesuwamy okno
        fold_accuracies = []

        for fold in range(5):
            train_end = fold_size * (fold + 1)
            test_end = min(train_end + fold_size, n)
            if train_end >= n or test_end <= train_end:
                break

            X_train, X_test = X.iloc[:train_end], X.iloc[train_end:test_end]
            y_train, y_test = y.iloc[:train_end], y.iloc[train_end:test_end]

            if len(X_train) < 20 or len(X_test) < 5:
                continue

            model = XGBClassifier(
                n_estimators=200, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.7, random_state=42,
                min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
                scale_pos_weight=scale_pos_weight,
                **_XGB_PARAMS
            )
            model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=0)
            acc = model.score(X_test, y_test)
            fold_accuracies.append(acc)
            logger.debug(f"XGBoost fold {fold+1}: accuracy {acc:.3f}")

        # Final model on all data
        self.xgb = XGBClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.7, random_state=42,
            min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
            scale_pos_weight=scale_pos_weight,
            **_XGB_PARAMS
        )
        self.xgb.fit(X, y)

        avg_acc = np.mean(fold_accuracies) if fold_accuracies else 0.5
        logger.info(f"XGBoost trained, walk-forward accuracy: {avg_acc:.3f} ({len(fold_accuracies)} folds)")

        with open(os.path.join(self.model_dir, 'xgb.pkl'), 'wb') as f:
            pickle.dump(self.xgb, f)

        # Persist accuracy to DB
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            db.set_param("xgb_last_accuracy", avg_acc)
            db.set_param("xgb_feature_count", len(FEATURE_COLS))
        except (ImportError, AttributeError, Exception) as e:
            logger.debug(f"Could not persist XGBoost metrics to DB: {e}")

        return avg_acc

    def predict_xgb(self, df):
        if self.xgb is None:
            try:
                with open(os.path.join(self.model_dir, 'xgb.pkl'), 'rb') as f:
                    self.xgb = pickle.load(f)
            except (FileNotFoundError, pickle.UnpicklingError, EOFError, ModuleNotFoundError):
                return 0.5
        features = self._features(df.tail(100))
        X = features[FEATURE_COLS].tail(1)
        if X.empty:
            return 0.5
        try:
            return self.xgb.predict_proba(X)[0, 1]
        except Exception as e:
            logger.warning(f"XGBoost predict error (feature mismatch?): {e}")
            return 0.5

    def train_lstm(self, df, seq_len=60, precomputed_features=None):
        """Trenowanie LSTM z walk-forward validation.
        Accepts precomputed_features to avoid recomputing indicators.

        Target: istotny ruch cenowy (>0.5 ATR w 5 świecach) zamiast next-candle noise.
        """
        batch_size = get_tf_batch_size()  # 128 GPU / 32 CPU
        if len(df) < seq_len + 2:
            logger.warning(f"Za mało danych do LSTM: potrzeba {seq_len+2}, mam {len(df)}")
            return None
        features = precomputed_features if precomputed_features is not None else self._features(df)
        features = features.copy()

        # --- ULEPSZONY TARGET: identyczny jak XGBoost (shared computation) ---
        features['direction'] = compute_target(features)

        features.dropna(inplace=True)
        if len(features) < seq_len + 1:
            logger.warning("Za mało danych po przygotowaniu cech")
            return None

        data = features[FEATURE_COLS].values
        scaled = self.scaler.fit_transform(data)

        # Persist fitted scaler for consistent inference
        scaler_path = os.path.join(self.model_dir, 'lstm_scaler.pkl')
        with open(scaler_path, 'wb') as f:
            pickle.dump(self.scaler, f)
        logger.info(f"LSTM scaler saved to {scaler_path}")

        # Vectorized sliding window (replaces Python for-loop)
        n_samples = len(scaled) - seq_len
        n_features = scaled.shape[1]
        idx = np.arange(seq_len)[None, :] + np.arange(n_samples)[:, None]  # (n_samples, seq_len)
        X = scaled[idx]  # fancy indexing → (n_samples, seq_len, n_features)
        y = features['direction'].values[seq_len:]
        if len(X) == 0:
            logger.warning("Brak sekwencji do trenowania LSTM")
            return None

        # Walk-forward validation (5 foldów chronologicznych)
        n = len(X)
        fold_size = n // 6
        fold_accuracies = []

        for fold in range(5):
            train_end = fold_size * (fold + 1)
            test_end = min(train_end + fold_size, n)
            if train_end >= n or test_end <= train_end:
                break
            X_tr, X_te = X[:train_end], X[train_end:test_end]
            y_tr, y_te = y[:train_end], y[train_end:test_end]
            if len(X_tr) < 20 or len(X_te) < 5:
                continue

            fold_model = Sequential([
                LSTM(128, return_sequences=True, input_shape=(seq_len, X.shape[2])),
                Dropout(0.3),
                LSTM(64, return_sequences=True),
                Dropout(0.25),
                LSTM(32),
                Dropout(0.2),
                Dense(32, activation='relu'),
                Dense(16, activation='relu'),
                Dense(1, activation='sigmoid', dtype='float32')
            ])
            from tensorflow.keras.optimizers import Adam as _Adam
            fold_model.compile(optimizer=_Adam(learning_rate=0.0005), loss='binary_crossentropy', metrics=['accuracy'])
            early_fold = EarlyStopping(monitor='val_loss', patience=8, restore_best_weights=True)
            fold_model.fit(X_tr, y_tr, epochs=50, batch_size=batch_size,
                          validation_data=(X_te, y_te), callbacks=[early_fold], verbose=0)
            fold_acc = fold_model.evaluate(X_te, y_te, verbose=0)[1]
            fold_accuracies.append(fold_acc)
            logger.debug(f"LSTM fold {fold+1}: accuracy {fold_acc:.3f}")

        # Final model on all data — ulepszona architektura
        split = int(0.8 * len(X))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        # Class weight dla nierównomiernej dystrybucji
        n_pos = int(y_train.sum())
        n_neg = len(y_train) - n_pos
        class_weight = {0: 1.0, 1: n_neg / max(n_pos, 1)} if n_pos > 0 else None

        model = Sequential([
            LSTM(128, return_sequences=True, input_shape=(seq_len, X.shape[2])),
            Dropout(0.3),
            LSTM(64, return_sequences=True),
            Dropout(0.25),
            LSTM(32),
            Dropout(0.2),
            Dense(32, activation='relu'),
            Dense(16, activation='relu'),
            Dense(1, activation='sigmoid', dtype='float32')
        ])
        from tensorflow.keras.optimizers import Adam as _Adam
        model.compile(optimizer=_Adam(learning_rate=0.0005), loss='binary_crossentropy', metrics=['accuracy'])
        early = EarlyStopping(monitor='val_loss', patience=15, restore_best_weights=True)
        history = model.fit(X_train, y_train, epochs=80, batch_size=batch_size,
                           validation_data=(X_test, y_test),
                           callbacks=[early], verbose=0,
                           class_weight=class_weight)
        self.lstm = model
        self.lstm.save(os.path.join(self.model_dir, 'lstm.keras'))

        # Persist accuracy
        best_val_acc = max(history.history.get('val_accuracy', [0.5]))
        wf_acc = np.mean(fold_accuracies) if fold_accuracies else best_val_acc
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            db.set_param("lstm_last_accuracy", best_val_acc)
            db.set_param("lstm_walkforward_accuracy", wf_acc)
        except (ImportError, AttributeError, Exception) as e:
            logger.debug(f"Could not persist LSTM metrics to DB: {e}")

        logger.info(f"LSTM trained, val_accuracy: {best_val_acc:.3f}, walk-forward: {wf_acc:.3f} ({len(fold_accuracies)} folds)")
        return model

    def predict_lstm(self, df, seq_len=60):
        """Predict using LSTM. Tries ONNX DirectML (GPU) first, falls back to Keras."""
        # Załaduj model z dysku jeśli nie ma w pamięci
        if self.lstm is None:
            try:
                self.lstm = load_model(os.path.join(self.model_dir, 'lstm.keras'))
            except Exception as e:
                logger.error(f"Nie udało się załadować modelu LSTM: {e}")
                return 0.5

        # Try ONNX GPU inference (DirectML)
        onnx_session = self._get_onnx_lstm_session()

        if len(df) < seq_len + 1:
            logger.warning(f"Za mało danych dla LSTM: potrzeba {seq_len+1}, mam {len(df)}")
            return 0.5

        try:
            features = self._features(df.tail(seq_len + 30))
        except Exception as e:
            logger.error(f"Błąd w _features: {e}")
            return 0.5

        if len(features) < seq_len:
            logger.warning("Po przygotowaniu cech, za mało wierszy dla LSTM")
            return 0.5

        data = features[FEATURE_COLS].values[-seq_len:]

        if np.isnan(data).any():
            logger.warning("W danych wejściowych LSTM są NaN")
            return 0.5

        try:
            scaled = self.scaler.transform(data)
        except Exception as e:
            logger.error(f"Błąd skalowania danych LSTM: {e}")
            return 0.5

        X = scaled.reshape(1, seq_len, -1)

        try:
            # ONNX GPU inference (DirectML) — faster on AMD/Intel GPUs
            if onnx_session is not None:
                from src.analysis.compute import onnx_predict
                pred = onnx_predict(onnx_session, X.astype(np.float32))
            else:
                pred = self.lstm.predict(X, verbose=0)

            if pred is None:
                return 0.5
            if isinstance(pred, (list, tuple)):
                if len(pred) == 0:
                    return 0.5
                pred = pred[0]
            if isinstance(pred, np.ndarray):
                if pred.size == 0:
                    return 0.5
                if pred.ndim == 2:
                    return float(pred[0, 0])
                elif pred.ndim == 1:
                    return float(pred[0])
            return 0.5
        except Exception as e:
            logger.error(f"Błąd predykcji LSTM: {e}", exc_info=True)
            return 0.5

    def _get_onnx_lstm_session(self):
        """Get ONNX session for LSTM (GPU via DirectML). Cached."""
        if not hasattr(self, '_onnx_lstm'):
            self._onnx_lstm = None
            try:
                from src.analysis.compute import detect_gpu, convert_keras_to_onnx, get_onnx_session
                gpu_info = detect_gpu()
                if gpu_info["onnx_directml"]:
                    keras_path = os.path.join(self.model_dir, 'lstm.keras')
                    if os.path.exists(keras_path):
                        onnx_path = convert_keras_to_onnx(keras_path)
                        if onnx_path:
                            self._onnx_lstm = get_onnx_session(onnx_path)
            except Exception as e:
                logger.debug(f"ONNX LSTM session skipped: {e}")
        return self._onnx_lstm

ml = MLPredictor()
