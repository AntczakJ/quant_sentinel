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

# Rozszerzony zestaw kolumn cech (musi być spójny między train i predict)
FEATURE_COLS = [
    'rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5',
    'is_green', 'above_ema20',
    # Nowe cechy
    'williams_r', 'cci', 'ema_distance',
    'ichimoku_signal', 'engulfing_score', 'pin_bar_score',
    'ret_10', 'body_ratio', 'upper_shadow_ratio', 'lower_shadow_ratio',
]

class MLPredictor:
    def __init__(self, model_dir='models'):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        self.xgb = None
        self.lstm = None
        self.scaler = MinMaxScaler()

    def _features(self, df):
        """Rozszerzony zestaw cech technicznych + price action."""
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
        df['ema_distance'] = (df['close'] - ema20) / ema20  # znormalizowana odległość od EMA

        # --- Nowe wskaźniki momentum ---
        # Williams %R
        high_14 = df['high'].rolling(14).max()
        low_14 = df['low'].rolling(14).min()
        df['williams_r'] = -100 * (high_14 - df['close']) / (high_14 - low_14 + 1e-10)

        # CCI
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        sma_tp = typical_price.rolling(20).mean()
        mad_tp = typical_price.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean())
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

        # Engulfing: +1 bullish, -1 bearish, 0 none
        engulfing = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            prev_o, prev_c = df['open'].iloc[i-1], df['close'].iloc[i-1]
            curr_o, curr_c = df['open'].iloc[i], df['close'].iloc[i]
            if prev_c < prev_o and curr_c > curr_o and curr_o < prev_c and curr_c > prev_o:
                engulfing.iloc[i] = 1  # bullish engulfing
            elif prev_c > prev_o and curr_c < curr_o and curr_o > prev_c and curr_c < prev_o:
                engulfing.iloc[i] = -1  # bearish engulfing
        df['engulfing_score'] = engulfing

        # Pin bar: +1 bullish, -1 bearish, 0 none
        pin = pd.Series(0, index=df.index)
        for i in range(len(df)):
            b = body.iloc[i]
            hl = high_low.iloc[i]
            if b / hl > 0.3:
                continue
            lower_s = df[['close', 'open']].min(axis=1).iloc[i] - df['low'].iloc[i]
            upper_s = df['high'].iloc[i] - df[['close', 'open']].max(axis=1).iloc[i]
            if lower_s > 2 * upper_s and lower_s > b:
                pin.iloc[i] = 1
            elif upper_s > 2 * lower_s and upper_s > b:
                pin.iloc[i] = -1
        df['pin_bar_score'] = pin

        df.dropna(inplace=True)
        return df

    def train_xgb(self, df):
        """Trenowanie XGBoost z walk-forward validation."""
        features = self._features(df)
        features['direction'] = (features['close'].shift(-1) > features['close']).astype(int)
        features.dropna(inplace=True)
        if len(features) < 50:
            logger.warning("Za mało danych do trenowania XGBoost (min 50)")
            return None

        X = features[FEATURE_COLS]
        y = features['direction']

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
                n_estimators=150, max_depth=5, learning_rate=0.08,
                subsample=0.8, colsample_bytree=0.8, random_state=42
            )
            model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=0)
            acc = model.score(X_test, y_test)
            fold_accuracies.append(acc)
            logger.debug(f"XGBoost fold {fold+1}: accuracy {acc:.3f}")

        # Final model on all data
        self.xgb = XGBClassifier(
            n_estimators=150, max_depth=5, learning_rate=0.08,
            subsample=0.8, colsample_bytree=0.8, random_state=42
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

    def train_lstm(self, df, seq_len=60):
        if len(df) < seq_len + 2:
            logger.warning(f"Za mało danych do LSTM: potrzeba {seq_len+2}, mam {len(df)}")
            return None
        features = self._features(df)
        features['direction'] = (features['close'].shift(-1) > features['close']).astype(int)
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

        X, y = [], []
        for i in range(seq_len, len(scaled)):
            X.append(scaled[i-seq_len:i])
            y.append(features['direction'].iloc[i])
        X = np.array(X)
        y = np.array(y)
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
                LSTM(64, return_sequences=True, input_shape=(seq_len, X.shape[2])),
                Dropout(0.3),
                LSTM(32),
                Dropout(0.2),
                Dense(16, activation='relu'),
                Dense(1, activation='sigmoid')
            ])
            fold_model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
            early_fold = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
            fold_model.fit(X_tr, y_tr, epochs=30, batch_size=32,
                          validation_data=(X_te, y_te), callbacks=[early_fold], verbose=0)
            fold_acc = fold_model.evaluate(X_te, y_te, verbose=0)[1]
            fold_accuracies.append(fold_acc)
            logger.debug(f"LSTM fold {fold+1}: accuracy {fold_acc:.3f}")

        # Final model on all data
        split = int(0.8 * len(X))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        model = Sequential([
            LSTM(64, return_sequences=True, input_shape=(seq_len, X.shape[2])),
            Dropout(0.3),
            LSTM(32),
            Dropout(0.2),
            Dense(16, activation='relu'),
            Dense(1, activation='sigmoid')
        ])
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        early = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        history = model.fit(X_train, y_train, epochs=50, batch_size=32,
                           validation_data=(X_test, y_test),
                           callbacks=[early], verbose=0)
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
