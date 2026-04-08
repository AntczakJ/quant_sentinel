"""
ml_models.py — modele LSTM i XGBoost do prognozowania kierunku.

Ulepszenia:
- Rozszerzony zestaw cech (Williams %R, CCI, Ichimoku, candlestick patterns)
- Walk-forward validation zamiast prostego train_test_split
- Persystencja metryk do bazy danych
"""

import pandas as pd
import numpy as np
import os
import pickle
import pandas_ta as ta
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
from src.logger import logger

# ── GPU / TF configuration ────────────────────────────────────────────
def _setup_tf_gpu():
    """Enable GPU memory growth + mixed precision on GPU; return True if GPU present."""
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
            # Mixed precision: float16 compute with float32 accumulation — ~2x faster on modern GPUs
            try:
                tf.keras.mixed_precision.set_global_policy('mixed_float16')
                logger.info(f"TensorFlow GPU: {[g.name for g in gpus]} (mixed_float16 enabled)")
            except Exception as mp_err:
                logger.debug(f"Mixed precision skipped: {mp_err}")
                logger.info(f"TensorFlow GPU: {[g.name for g in gpus]}")
            return True
        return False
    except Exception as e:
        logger.debug(f"TF GPU setup skipped: {e}")
        return False

_TF_GPU = _setup_tf_gpu()

# ── XGBoost GPU detection ─────────────────────────────────────────────
def _detect_xgb_params():
    """Return XGBoost params with GPU if available, else fast CPU histogram."""
    base = {'tree_method': 'hist', 'n_jobs': -1}
    try:
        import xgboost as xgb
        _t = XGBClassifier(device='cuda', tree_method='hist',
                           n_estimators=1, verbosity=0)
        _t.fit([[1]*5]*4, [0, 1, 0, 1])
        logger.info("XGBoost GPU (CUDA) acceleration enabled")
        return {**base, 'device': 'cuda'}
    except Exception:
        pass
    try:
        _t = XGBClassifier(tree_method='gpu_hist', n_estimators=1, verbosity=0)
        _t.fit([[1]*5]*4, [0, 1, 0, 1])
        logger.info("XGBoost GPU (gpu_hist) acceleration enabled")
        return {**base, 'tree_method': 'gpu_hist'}
    except Exception:
        pass
    logger.info("XGBoost CPU (hist) mode — no GPU found")
    return base

_XGB_PARAMS = _detect_xgb_params()

# Rozszerzony zestaw kolumn cech (musi być spójny między train i predict)
FEATURE_COLS = [
    'rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5',
    'is_green', 'above_ema20',
    # Momentum
    'williams_r', 'cci', 'ema_distance',
    'ichimoku_signal', 'engulfing_score', 'pin_bar_score',
    'ret_10', 'body_ratio', 'upper_shadow_ratio', 'lower_shadow_ratio',
    # Nowe: price action patterns + volume
    'higher_high', 'lower_low', 'double_top', 'double_bottom',
    'atr_ratio',  # ATR relative to price — normalizacja zmienności
]

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
        """Rozszerzony zestaw cech technicznych + price action.
        Cached: powtórne wywołanie na tym samym df zwraca wynik natychmiast."""
        cache_key = (id(df), len(df))
        if self._feature_cache_id == cache_key and self._feature_cache is not None:
            return self._feature_cache.copy()

        df = df.copy()

        # --- Podstawowe wskaźniki ---
        df['rsi'] = ta.rsi(df['close'], 14)
        macd = ta.macd(df['close'])
        df['macd'] = macd['MACD_12_26_9']
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], 14)
        df['volatility'] = df['close'].pct_change().rolling(20).std()
        df['ret_1'] = df['close'].pct_change()
        df['ret_5'] = df['close'].pct_change(5)
        df['ret_10'] = df['close'].pct_change(10)
        df['is_green'] = (df['close'] > df['open']).astype(int)
        ema20 = ta.ema(df['close'], 20)
        df['above_ema20'] = (df['close'] > ema20).astype(int)
        df['ema_distance'] = (df['close'] - ema20) / ema20

        # --- Nowe wskaźniki momentum ---
        # Williams %R
        high_14 = df['high'].rolling(14).max()
        low_14 = df['low'].rolling(14).min()
        df['williams_r'] = -100 * (high_14 - df['close']) / (high_14 - low_14 + 1e-10)

        # CCI — vectorized MAD (avoids slow .apply(lambda))
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        sma_tp = typical_price.rolling(20).mean()
        # Vectorized MAD: mean(|x - mean(x)|) ≈ 0.8 * std for normal-ish data
        # But for exact CCI we compute via rolling std * sqrt(2/pi) ≈ 0.7979
        mad_tp = typical_price.rolling(20).std() * 0.7979
        df['cci'] = (typical_price - sma_tp) / (0.015 * mad_tp + 1e-10)

        # --- Ichimoku signal (powyżej/poniżej chmury) ---
        try:
            tenkan = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
            kijun = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
            span_a = ((tenkan + kijun) / 2).shift(26)
            span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(26)
            cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
            df['ichimoku_signal'] = (df['close'] > cloud_top).astype(int)
        except:
            df['ichimoku_signal'] = 0

        # --- Candlestick pattern features ---
        body = abs(df['close'] - df['open'])
        high_low = df['high'] - df['low'] + 1e-10
        df['body_ratio'] = body / high_low
        df['upper_shadow_ratio'] = (df['high'] - df[['close', 'open']].max(axis=1)) / high_low
        df['lower_shadow_ratio'] = (df[['close', 'open']].min(axis=1) - df['low']) / high_low

        # Engulfing: vectorized (+1 bullish, -1 bearish, 0 none)
        prev_o = df['open'].shift(1)
        prev_c = df['close'].shift(1)
        bullish_eng = (
            (prev_c < prev_o) & (df['close'] > df['open']) &
            (df['open'] < prev_c) & (df['close'] > prev_o)
        )
        bearish_eng = (
            (prev_c > prev_o) & (df['close'] < df['open']) &
            (df['open'] > prev_c) & (df['close'] < prev_o)
        )
        df['engulfing_score'] = bullish_eng.astype(int) - bearish_eng.astype(int)

        # Pin bar: vectorized (+1 bullish, -1 bearish, 0 none)
        lower_s = df[['close', 'open']].min(axis=1) - df['low']
        upper_s = df['high'] - df[['close', 'open']].max(axis=1)
        small_body = (body / high_low) <= 0.3
        bullish_pin = small_body & (lower_s > 2 * upper_s) & (lower_s > body)
        bearish_pin = small_body & (upper_s > 2 * lower_s) & (upper_s > body)
        df['pin_bar_score'] = bullish_pin.astype(int) - bearish_pin.astype(int)

        # --- Price action patterns (z feature_engineering.py) ---
        lookback = 5
        df['higher_high'] = (df['high'].rolling(lookback).max().shift(1) < df['high']).astype(int)
        df['lower_low'] = (df['low'].rolling(lookback).min().shift(1) > df['low']).astype(int)

        # Double Top/Bottom
        rolling_high = df['high'].rolling(lookback)
        high_mean = rolling_high.mean()
        high_std = rolling_high.std()
        high_threshold = high_mean + high_std * 0.5
        above_thresh = (df['high'] > high_threshold).astype(int)
        df['double_top'] = (above_thresh.rolling(lookback).sum().shift(1) >= 2).astype(int)

        rolling_low = df['low'].rolling(lookback)
        low_mean = rolling_low.mean()
        low_std = rolling_low.std()
        low_threshold = low_mean - low_std * 0.5
        below_thresh = (df['low'] < low_threshold).astype(int)
        df['double_bottom'] = (below_thresh.rolling(lookback).sum().shift(1) >= 2).astype(int)

        # ATR ratio — normalizacja zmienności względem ceny
        df['atr_ratio'] = df['atr'] / (df['close'] + 1e-10)

        df.dropna(inplace=True)

        # Cache the result
        self._feature_cache_id = cache_key
        self._feature_cache = df
        return df.copy()

    def train_xgb(self, df, precomputed_features=None):
        """Trenowanie XGBoost z walk-forward validation.
        Accepts precomputed_features to avoid recomputing indicators.

        Target: czy cena wzrośnie o >0.5 ATR w ciągu następnych 5 świec
        (zamiast prostego next-candle direction, które jest szumem).
        """
        features = precomputed_features if precomputed_features is not None else self._features(df)

        # --- ULEPSZONY TARGET: istotny ruch zamiast next-candle noise ---
        # Sprawdzamy czy cena wzrasta o >0.5 ATR w ciągu następnych 5 świec
        lookahead = 5
        atr_threshold = 0.5
        future_max = features['close'].rolling(lookahead).max().shift(-lookahead)
        future_min = features['close'].rolling(lookahead).min().shift(-lookahead)
        atr_val = features['atr'].replace(0, np.nan).ffill().fillna(1.0)

        # LONG target: cena wzrosła o > 0.5*ATR i nie spadła o > 0.5*ATR (czysty ruch w górę)
        up_move = (future_max - features['close']) / atr_val > atr_threshold
        down_move = (features['close'] - future_min) / atr_val > atr_threshold
        # 1 = wyraźny ruch w górę, 0 = wyraźny ruch w dół lub brak ruchu
        features['direction'] = (up_move & ~down_move).astype(int)

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
            from src.database import NewsDB
            db = NewsDB()
            db.set_param("xgb_last_accuracy", avg_acc)
            db.set_param("xgb_feature_count", len(FEATURE_COLS))
        except:
            pass

        return avg_acc

    def predict_xgb(self, df):
        if self.xgb is None:
            try:
                with open(os.path.join(self.model_dir, 'xgb.pkl'), 'rb') as f:
                    self.xgb = pickle.load(f)
            except:
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
        batch_size = 128 if _TF_GPU else 32  # larger batches saturate GPU better
        if len(df) < seq_len + 2:
            logger.warning(f"Za mało danych do LSTM: potrzeba {seq_len+2}, mam {len(df)}")
            return None
        features = precomputed_features if precomputed_features is not None else self._features(df)
        features = features.copy()

        # --- ULEPSZONY TARGET: identyczny jak XGBoost ---
        lookahead = 5
        atr_threshold = 0.5
        future_max = features['close'].rolling(lookahead).max().shift(-lookahead)
        future_min = features['close'].rolling(lookahead).min().shift(-lookahead)
        atr_val = features['atr'].replace(0, np.nan).ffill().fillna(1.0)
        up_move = (future_max - features['close']) / atr_val > atr_threshold
        down_move = (features['close'] - future_min) / atr_val > atr_threshold
        features['direction'] = (up_move & ~down_move).astype(int)

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
            from src.database import NewsDB
            db = NewsDB()
            db.set_param("lstm_last_accuracy", best_val_acc)
            db.set_param("lstm_walkforward_accuracy", wf_acc)
        except:
            pass

        logger.info(f"LSTM trained, val_accuracy: {best_val_acc:.3f}, walk-forward: {wf_acc:.3f} ({len(fold_accuracies)} folds)")
        return model

    def predict_lstm(self, df, seq_len=60):
        # Jeśli model nie jest w pamięci, spróbuj załadować z dysku
        if self.lstm is None:
            try:
                self.lstm = load_model(os.path.join(self.model_dir, 'lstm.keras'))
            except Exception as e:
                logger.error(f"Nie udało się załadować modelu LSTM: {e}")
                return 0.5

        if len(df) < seq_len + 1:
            logger.warning(f"Za mało danych dla LSTM: potrzeba {seq_len+1}, mam {len(df)}")
            return 0.5

        # Przygotuj dane
        try:
            features = self._features(df.tail(seq_len + 30))  # extra rows for indicator warmup
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
            pred = self.lstm.predict(X, verbose=0)
            logger.debug(f"LSTM prediction raw: {pred}, type: {type(pred)}")
            if pred is None:
                logger.error("LSTM predict zwrócił None")
                return 0.5
            # Jeśli to lista/tuple, weź pierwszy element
            if isinstance(pred, (list, tuple)):
                if len(pred) == 0:
                    logger.error("LSTM predict zwrócił pustą listę")
                    return 0.5
                pred = pred[0]
            # Teraz pred powinien być numpy array
            if isinstance(pred, np.ndarray):
                if pred.size == 0:
                    logger.error("LSTM predict zwrócił pustą tablicę")
                    return 0.5
                # Jeśli to tablica 2D, weź pierwszy wiersz, pierwszą kolumnę
                if pred.ndim == 2:
                    return float(pred[0, 0])
                elif pred.ndim == 1:
                    return float(pred[0])
                else:
                    logger.error(f"Nieoczekiwany wymiar tablicy: {pred.shape}")
                    return 0.5
            else:
                logger.error(f"Niespodziewany typ wyniku predykcji: {type(pred)}")
                return 0.5
        except Exception as e:
            logger.error(f"Błąd predykcji LSTM: {e}", exc_info=True)
            return 0.5

ml = MLPredictor()
