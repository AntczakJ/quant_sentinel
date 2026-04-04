"""
ensemble_models.py — Integracja wszystkich modeli ML (LSTM, XGBoost, DQN) w jeden ensemble pipeline.

Odpowiada za:
  - Ładowanie modeli (LSTM, XGBoost, DQN)
  - Generowanie predykcji z każdego modelu
  - Fuzję predykcji z wagami
  - Caching modeli w pamięci
  - Obsługę błędów (fallback do wartości domyślnych)
"""

import os
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from src.logger import logger

# ============================================================================
# LAZY LOADING - modele ładują się tylko przy pierwszym użyciu
# ============================================================================

_models_cache = {
    "lstm": None,
    "xgb": None,
    "dqn": None,
    "scaler": None
}

_models_loaded = {
    "lstm": False,
    "xgb": False,
    "dqn": False
}


def _load_lstm():
    """Lazy load LSTM model."""
    if _models_loaded["lstm"]:
        return _models_cache["lstm"]

    try:
        from tensorflow.keras.models import load_model
        model_path = "models/lstm.keras"
        if os.path.exists(model_path):
            model = load_model(model_path)
            _models_cache["lstm"] = model
            _models_loaded["lstm"] = True
            logger.info("✅ LSTM model loaded")
            return model
    except Exception as e:
        logger.warning(f"⚠️ Failed to load LSTM: {e}")

    return None


def _load_xgb():
    """Lazy load XGBoost model."""
    if _models_loaded["xgb"]:
        return _models_cache["xgb"]

    try:
        import pickle
        model_path = "models/xgb.pkl"
        if os.path.exists(model_path):
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            _models_cache["xgb"] = model
            _models_loaded["xgb"] = True
            logger.info("✅ XGBoost model loaded")
            return model
    except Exception as e:
        logger.warning(f"⚠️ Failed to load XGBoost: {e}")

    return None


def _load_dqn(state_size=22, action_size=3):
    """Lazy load DQN Agent."""
    if _models_loaded["dqn"]:
        return _models_cache["dqn"]

    try:
        from src.rl_agent import DQNAgent
        agent = DQNAgent(state_size=state_size, action_size=action_size)
        model_path = "models/rl_agent.keras"

        if os.path.exists(model_path):
            agent.load(model_path)
            _models_cache["dqn"] = agent
            _models_loaded["dqn"] = True
            logger.info("✅ DQN Agent loaded")
            return agent
    except Exception as e:
        logger.warning(f"⚠️ Failed to load DQN: {e}")

    return None


def _get_scaler():
    """Get or create MinMaxScaler for LSTM."""
    if _models_cache["scaler"] is not None:
        return _models_cache["scaler"]

    try:
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        _models_cache["scaler"] = scaler
        return scaler
    except Exception as e:
        logger.warning(f"⚠️ Failed to create scaler: {e}")

    return None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _fallback_ensemble_result() -> Dict:
    """Zwraca fallback result gdy nie ma danych."""
    return {
        "predictions": {},
        "weights": {},
        "final_score": 0.5,
        "final_direction": "NEUTRAL",
        "confidence": 0.0,
        "ensemble_signal": "CZEKAJ",
        "error": "Insufficient data"
    }


# ============================================================================
# PREDYKCJE Z POSZCZEGÓLNYCH MODELI
# ============================================================================

def predict_lstm_direction(df: pd.DataFrame, seq_len: int = 60) -> Optional[float]:
    """
    Predykcja LSTM: prawdopodobieństwo wzrostu (0-1).

    Returns:
        float: Prawdopodobieństwo wzrostu (0.0-1.0), lub None jeśli błąd
    """
    try:
        import pandas_ta as ta

        lstm_model = _load_lstm()
        if lstm_model is None:
            return None

        if len(df) < seq_len + 1:
            logger.debug(f"Za mało danych dla LSTM: {len(df)} < {seq_len+1}")
            return None

        # Przygotuj cechy
        df_copy = df.copy()
        df_copy['rsi'] = ta.rsi(df_copy['close'], 14)
        df_copy['macd'] = ta.macd(df_copy['close'])['MACD_12_26_9']
        df_copy['atr'] = ta.atr(df_copy['high'], df_copy['low'], df_copy['close'], 14)
        df_copy['volatility'] = df_copy['close'].pct_change().rolling(20).std()
        df_copy['ret_1'] = df_copy['close'].pct_change()
        df_copy['ret_5'] = df_copy['close'].pct_change(5)
        df_copy['is_green'] = (df_copy['close'] > df_copy['open']).astype(int)
        df_copy['above_ema20'] = (df_copy['close'] > ta.ema(df_copy['close'], 20)).astype(int)

        df_copy = df_copy.dropna()

        if len(df_copy) < seq_len:
            logger.debug("Za mało danych po przygotowaniu cech")
            return None

        cols = ['rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5', 'is_green', 'above_ema20']
        data = df_copy[cols].values[-seq_len:]

        # Normalizuj
        scaler = _get_scaler()
        if scaler is not None:
            data = scaler.fit_transform(data)

        X = data.reshape(1, seq_len, -1)

        # Predykcja
        pred = lstm_model.predict(X, verbose=0)

        if isinstance(pred, np.ndarray):
            if pred.ndim == 2:
                return float(pred[0, 0])
            elif pred.ndim == 1:
                return float(pred[0])

        return None

    except Exception as e:
        logger.debug(f"LSTM prediction error: {e}")
        return None


def predict_xgb_direction(df: pd.DataFrame) -> Optional[float]:
    """
    Predykcja XGBoost: prawdopodobieństwo wzrostu (0-1).

    Returns:
        float: Prawdopodobieństwo wzrostu (0.0-1.0), lub None jeśli błąd
    """
    try:
        import pandas_ta as ta

        xgb_model = _load_xgb()
        if xgb_model is None:
            return None

        if len(df) < 100:
            logger.debug(f"Za mało danych dla XGBoost: {len(df)} < 100")
            return None

        # Przygotuj cechy
        df_copy = df.copy()
        df_copy['rsi'] = ta.rsi(df_copy['close'], 14)
        df_copy['macd'] = ta.macd(df_copy['close'])['MACD_12_26_9']
        df_copy['atr'] = ta.atr(df_copy['high'], df_copy['low'], df_copy['close'], 14)
        df_copy['volatility'] = df_copy['close'].pct_change().rolling(20).std()
        df_copy['ret_1'] = df_copy['close'].pct_change()
        df_copy['ret_5'] = df_copy['close'].pct_change(5)
        df_copy['is_green'] = (df_copy['close'] > df_copy['open']).astype(int)
        df_copy['above_ema20'] = (df_copy['close'] > ta.ema(df_copy['close'], 20)).astype(int)

        df_copy = df_copy.dropna()

        if df_copy.empty:
            return None

        X = df_copy.drop(columns=['open', 'high', 'low', 'close', 'volume'], errors='ignore')
        X = X.tail(1)

        if X.empty:
            return None

        # Predykcja
        pred = xgb_model.predict_proba(X)
        return float(pred[0, 1])  # Prawdopodobieństwo klasy 1 (wzrost)

    except Exception as e:
        logger.debug(f"XGBoost prediction error: {e}")
        return None


def predict_dqn_action(close_prices: np.ndarray, balance: float = 1.0, position: int = 0) -> Optional[int]:
    """
    Predykcja DQN: akcja (0=hold, 1=buy, 2=sell).

    Args:
        close_prices: Ostatnie ~20 cen zamknięcia
        balance: Znormalizowany balans (balance/initial_balance)
        position: Aktualna pozycja (-1=short, 0=none, 1=long)

    Returns:
        int: Akcja (0, 1, lub 2), lub None jeśli błąd
    """
    try:
        dqn_agent = _load_dqn()
        if dqn_agent is None:
            return None

        # Buduj state
        state = dqn_agent.build_state(close_prices, balance, position)

        # Predykcja
        action = dqn_agent.act(state)
        return int(action)

    except Exception as e:
        logger.debug(f"DQN prediction error: {e}")
        return None


# ============================================================================
# ENSEMBLE - FUZJA WSZYSTKICH MODELI
# ============================================================================

def get_ensemble_prediction(
    df: pd.DataFrame = None,
    smc_trend: str = "bull",
    current_price: float = 0,
    balance: float = 10000,
    initial_balance: float = 10000,
    position: int = 0,
    weights: Optional[Dict[str, float]] = None,
    symbol: str = "XAU/USD",
    timeframe: str = "15m",
    use_twelve_data: bool = True
) -> Dict:
    """
    Łączy predykcje ze wszystkich modeli ML + SMC w jeden sygnał.

    Args:
        df: DataFrame z danymi OHLCV (opcjonalnie - jeśli None, pobiera z TwelveData)
        smc_trend: Trend z SMC Engine ("bull" lub "bear")
        current_price: Aktualna cena
        balance: Aktualna równowaga portfela
        initial_balance: Początkowa równowaga
        position: Aktualna pozycja (-1, 0, 1)
        weights: Wagi dla każdego modelu (domyślnie równe)
        symbol: Symbol do analizy (np. "XAU/USD")
        timeframe: Timeframe (np. "15m")
        use_twelve_data: Jeśli True i df is None, pobiera dane z Twelve Data

    Returns:
        Dict z prognozami i ostatecznym sygnałem
    """

    # ========== Jeśli brak danych, pobierz z Twelve Data ==========
    if df is None or df.empty:
        if use_twelve_data:
            try:
                from src.data_sources import get_provider
                provider = get_provider()
                logger.debug(f"📡 Fetching live data from Twelve Data: {symbol} {timeframe}")
                df = provider.get_candles(symbol, timeframe, 200)

                if df is None or df.empty:
                    logger.warning(f"⚠️ Could not fetch data for {symbol} from Twelve Data")
                    return _fallback_ensemble_result()
            except Exception as e:
                logger.warning(f"⚠️ Error fetching Twelve Data: {e}")
                return _fallback_ensemble_result()
        else:
            logger.warning("⚠️ No DataFrame provided and use_twelve_data=False")
            return _fallback_ensemble_result()

    # Domyślne wagi (można je dostroić)
    if weights is None:
        weights = {
            "smc": 0.35,      # SMC - bazowy
            "lstm": 0.25,     # Prognoza LSTM
            "xgb": 0.20,      # Prognoza XGBoost
            "dqn": 0.20       # Rekomendacja DQN
        }

    results = {
        "predictions": {},
        "weights": weights,
        "final_score": 0.5,
        "final_direction": "NEUTRAL",
        "confidence": 0.0,
        "ensemble_signal": "CZEKAJ"
    }

    # --- 1. SMC Signal ---
    smc_signal = 1.0 if smc_trend == "bull" else 0.0
    results["predictions"]["smc"] = {
        "value": smc_signal,
        "direction": "LONG" if smc_trend == "bull" else "SHORT",
        "confidence": 0.8  # SMC jest zawsze pewny
    }

    # --- 2. LSTM Prediction ---
    lstm_pred = predict_lstm_direction(df)
    if lstm_pred is not None:
        results["predictions"]["lstm"] = {
            "value": lstm_pred,
            "direction": "LONG" if lstm_pred > 0.5 else "SHORT",
            "confidence": abs(lstm_pred - 0.5) * 2  # 0.5 = 0% pewności, 1.0/0.0 = 100%
        }
    else:
        results["predictions"]["lstm"] = {
            "value": 0.5,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": "unavailable"
        }

    # --- 3. XGBoost Prediction ---
    xgb_pred = predict_xgb_direction(df)
    if xgb_pred is not None:
        results["predictions"]["xgb"] = {
            "value": xgb_pred,
            "direction": "LONG" if xgb_pred > 0.5 else "SHORT",
            "confidence": abs(xgb_pred - 0.5) * 2
        }
    else:
        results["predictions"]["xgb"] = {
            "value": 0.5,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": "unavailable"
        }

    # --- 4. DQN Action ---
    norm_balance = balance / initial_balance if initial_balance > 0 else 1.0
    close_prices = df['close'].tail(20).values

    dqn_action = predict_dqn_action(close_prices, norm_balance, position)
    if dqn_action is not None:
        # Konwertuj akcję DQN na signal (0-1)
        dqn_signal = {
            0: 0.5,   # hold = neutral
            1: 0.8,   # buy = bullish
            2: 0.2    # sell = bearish
        }.get(dqn_action, 0.5)

        dqn_direction = {
            0: "HOLD",
            1: "BUY",
            2: "SELL"
        }.get(dqn_action, "NEUTRAL")

        results["predictions"]["dqn"] = {
            "value": dqn_signal,
            "action": dqn_action,
            "direction": dqn_direction,
            "confidence": 0.7
        }
    else:
        results["predictions"]["dqn"] = {
            "value": 0.5,
            "action": None,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": "unavailable"
        }

    # ========== FUZJA PREDYKCJI ==========
    total_weight = 0
    weighted_sum = 0
    confidence_sum = 0
    available_models = 0

    for model_name, weight in weights.items():
        if model_name in results["predictions"]:
            pred = results["predictions"][model_name]
            if "status" not in pred:  # Model dostępny
                weighted_sum += pred["value"] * weight
                confidence_sum += pred.get("confidence", 0.5) * weight
                total_weight += weight
                available_models += 1

    # Znormalizuj wagi
    if total_weight > 0:
        results["final_score"] = weighted_sum / total_weight
        results["confidence"] = confidence_sum / total_weight
    else:
        results["final_score"] = 0.5
        results["confidence"] = 0.0

    # ========== OSTATECZNY SYGNAŁ ==========
    if available_models == 0:
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "NEUTRAL"
    elif results["confidence"] < 0.4:
        # Niska pewność
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "UNCERTAIN"
    elif results["final_score"] > 0.65:
        results["ensemble_signal"] = "LONG"
        results["final_direction"] = "LONG"
    elif results["final_score"] < 0.35:
        results["ensemble_signal"] = "SHORT"
        results["final_direction"] = "SHORT"
    else:
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "NEUTRAL"

    results["models_available"] = available_models

    logger.info(
        f"🤖 Ensemble: {available_models} modele | "
        f"Score: {results['final_score']:.3f} | "
        f"Confidence: {results['confidence']:.1%} | "
        f"Signal: {results['ensemble_signal']}"
    )

    return results

