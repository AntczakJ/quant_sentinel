"""
ml_models.py — modele LSTM i XGBoost do prognozowania kierunku.
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

class MLPredictor:
    def __init__(self, model_dir='models'):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)
        self.xgb = None
        self.lstm = None
        self.scaler = MinMaxScaler()

    def _features(self, df):
        df = df.copy()
        df['rsi'] = ta.rsi(df['close'], 14)
        macd = ta.macd(df['close'])
        df['macd'] = macd['MACD_12_26_9']
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], 14)
        df['volatility'] = df['close'].pct_change().rolling(20).std()
        df['ret_1'] = df['close'].pct_change()
        df['ret_5'] = df['close'].pct_change(5)
        df['is_green'] = (df['close'] > df['open']).astype(int)
        ema20 = ta.ema(df['close'], 20)
        df['above_ema20'] = (df['close'] > ema20).astype(int)
        df.dropna(inplace=True)
        return df

    def train_xgb(self, df):
        features = self._features(df)
        features['direction'] = (features['close'].shift(-1) > features['close']).astype(int)
        features.dropna(inplace=True)
        if len(features) < 20:
            logger.warning("Za mało danych do trenowania XGBoost")
            return None
        X = features.drop(columns=['direction', 'open', 'high', 'low', 'close', 'volume'], errors='ignore')
        y = features['direction']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        self.xgb = XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42)
        self.xgb.fit(X_train, y_train)
        acc = self.xgb.score(X_test, y_test)
        logger.info(f"XGBoost trained, accuracy: {acc:.2f}")
        with open(os.path.join(self.model_dir, 'xgb.pkl'), 'wb') as f:
            pickle.dump(self.xgb, f)
        return acc

    def predict_xgb(self, df):
        if self.xgb is None:
            try:
                with open(os.path.join(self.model_dir, 'xgb.pkl'), 'rb') as f:
                    self.xgb = pickle.load(f)
            except:
                return 0.5
        features = self._features(df.tail(100))
        X = features.drop(columns=['direction', 'open', 'high', 'low', 'close', 'volume'], errors='ignore')
        X = X.tail(1)
        if X.empty:
            return 0.5
        return self.xgb.predict_proba(X)[0, 1]

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
        cols = ['rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5', 'is_green', 'above_ema20']
        data = features[cols].values
        scaled = self.scaler.fit_transform(data)
        X, y = [], []
        for i in range(seq_len, len(scaled)):
            X.append(scaled[i-seq_len:i])
            y.append(features['direction'].iloc[i])
        X = np.array(X)
        y = np.array(y)
        if len(X) == 0:
            logger.warning("Brak sekwencji do trenowania LSTM")
            return None
        split = int(0.8 * len(X))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]
        model = Sequential([
            LSTM(50, return_sequences=True, input_shape=(seq_len, X.shape[2])),
            Dropout(0.2),
            LSTM(50),
            Dropout(0.2),
            Dense(1, activation='sigmoid')
        ])
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
        early = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
        model.fit(X_train, y_train, epochs=50, batch_size=32, validation_data=(X_test, y_test),
                  callbacks=[early], verbose=0)
        self.lstm = model
        # Zapisz model (nowy format .keras)
        self.lstm.save(os.path.join(self.model_dir, 'lstm.keras'))
        logger.info("LSTM trained")
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
            features = self._features(df.tail(seq_len + 1))
        except Exception as e:
            logger.error(f"Błąd w _features: {e}")
            return 0.5

        if len(features) < seq_len:
            logger.warning("Po przygotowaniu cech, za mało wierszy dla LSTM")
            return 0.5

        cols = ['rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5', 'is_green', 'above_ema20']
        data = features[cols].values[-seq_len:]

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