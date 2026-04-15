"""
ensemble_models.py — Integracja wszystkich modeli ML (LSTM, XGBoost, DQN) w jeden ensemble pipeline.

Odpowiada za:
  - Ładowanie modeli (LSTM, XGBoost, DQN)
  - Generowanie predykcji z każdego modelu
  - Fuzję predykcji z wagami
  - Caching modeli w pamięci
  - Obsługę błędów (fallback do wartości domyślnych)
  - GPU-accelerated feature computation via compute module
"""

import os
import numpy as np
import pandas as pd
from typing import Any, Dict, Optional, Tuple
from src.core.logger import logger
from src.analysis.compute import compute_features, FEATURE_COLS

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

# Track source-file mtime per model so auto-retrain can invalidate the cache.
# Without this, once _models_loaded[x]=True is set, _load_x() returns the
# cached session/model forever — even after retrain writes fresh .onnx /
# .keras / .pkl to disk. API restart was the only way to pick up new
# weights. Fix: on every call, compare current file mtime against what
# was recorded at load time; if newer, flip _models_loaded[x] back to
# False so the function re-enters the load path.
_models_mtime: Dict[str, float] = {"lstm": 0.0, "xgb": 0.0, "dqn": 0.0, "scaler": 0.0}


def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _invalidate_if_stale(key: str, *paths: str) -> None:
    """If any of the on-disk files is newer than cached mtime, mark the model
    as unloaded so the next _load_* call reloads fresh. No-op when files are
    unchanged — just a few stat() calls, negligible overhead per scan."""
    current = max((_file_mtime(p) for p in paths if p), default=0.0)
    if current > _models_mtime.get(key, 0.0) + 0.5:  # 0.5s tolerance for fs granularity
        if _models_loaded.get(key):
            logger.info(f"Model {key} changed on disk — invalidating cache")
            _models_loaded[key] = False
            _models_cache[key] = None


def _load_lstm():
    """Lazy load LSTM model. Prefers ONNX+DirectML GPU if available."""
    keras_path = "models/lstm.keras"
    onnx_path = "models/lstm.onnx"
    _invalidate_if_stale("lstm", keras_path, onnx_path)
    if _models_loaded["lstm"]:
        return _models_cache["lstm"]
    _models_mtime["lstm"] = max(_file_mtime(keras_path), _file_mtime(onnx_path))

    # Try ONNX Runtime (GPU via DirectML) first
    try:
        from src.analysis.compute import detect_gpu, convert_keras_to_onnx, get_onnx_session
        gpu_info = detect_gpu()
        if gpu_info["onnx_directml"] and os.path.exists(keras_path):
            converted = convert_keras_to_onnx(keras_path, onnx_path)
            if converted:
                session = get_onnx_session(converted)
                if session:
                    _models_cache["lstm"] = ("onnx", session)
                    _models_loaded["lstm"] = True
                    logger.info("LSTM loaded via ONNX Runtime DirectML (GPU)")
                    return _models_cache["lstm"]
    except Exception as e:
        logger.debug(f"ONNX LSTM load skipped: {e}")

    # Fallback: TensorFlow (CPU or TF-GPU if available)
    try:
        from tensorflow.keras.models import load_model
        if os.path.exists(keras_path):
            model = load_model(keras_path)
            _models_cache["lstm"] = ("keras", model)
            _models_loaded["lstm"] = True
            logger.info("LSTM model loaded (Keras/TensorFlow)")
            return _models_cache["lstm"]
    except Exception as e:
        logger.warning(f"Failed to load LSTM: {e}")

    return None


def _load_xgb():
    """Lazy load XGBoost model. Prefers ONNX+DirectML GPU if available."""
    pkl_path = "models/xgb.pkl"
    onnx_path = "models/xgb.onnx"
    _invalidate_if_stale("xgb", pkl_path, onnx_path)
    if _models_loaded["xgb"]:
        return _models_cache["xgb"]
    _models_mtime["xgb"] = max(_file_mtime(pkl_path), _file_mtime(onnx_path))

    # Try ONNX Runtime (GPU via DirectML) first
    try:
        from src.analysis.compute import detect_gpu, convert_xgboost_to_onnx, get_onnx_session
        gpu_info = detect_gpu()
        if gpu_info["onnx_directml"] and os.path.exists(pkl_path):
            # Load pkl to convert, or use existing onnx
            import pickle
            with open(pkl_path, 'rb') as f:
                xgb_model = pickle.load(f)
            n_features = xgb_model.n_features_in_ if hasattr(xgb_model, 'n_features_in_') else len(FEATURE_COLS)
            converted = convert_xgboost_to_onnx(xgb_model, n_features, onnx_path)
            if converted:
                session = get_onnx_session(converted)
                if session:
                    _models_cache["xgb"] = ("onnx", session)
                    _models_loaded["xgb"] = True
                    logger.info("XGBoost loaded via ONNX Runtime DirectML (GPU)")
                    return _models_cache["xgb"]
    except Exception as e:
        logger.debug(f"ONNX XGBoost load skipped: {e}")

    # Fallback: native XGBoost (CPU)
    try:
        import pickle
        if os.path.exists(pkl_path):
            with open(pkl_path, 'rb') as f:
                model = pickle.load(f)
            _models_cache["xgb"] = ("sklearn", model)
            _models_loaded["xgb"] = True
            logger.info("XGBoost model loaded (CPU)")
            return _models_cache["xgb"]
    except Exception as e:
        logger.warning(f"Failed to load XGBoost: {e}")

    return None


def _load_dqn(state_size=22, action_size=3):
    """Lazy load DQN Agent. Prefers ONNX+DirectML GPU if available."""
    keras_path = "models/rl_agent.keras"
    onnx_path = "models/rl_agent.onnx"
    _invalidate_if_stale("dqn", keras_path, onnx_path)
    if _models_loaded["dqn"]:
        return _models_cache["dqn"]
    _models_mtime["dqn"] = max(_file_mtime(keras_path), _file_mtime(onnx_path))

    # Try ONNX Runtime (GPU via DirectML) first
    try:
        from src.analysis.compute import detect_gpu, convert_keras_to_onnx, get_onnx_session
        gpu_info = detect_gpu()
        if gpu_info["onnx_directml"] and os.path.exists(keras_path):
            converted = convert_keras_to_onnx(keras_path, onnx_path)
            if converted:
                session = get_onnx_session(converted)
                if session:
                    _models_cache["dqn"] = ("onnx", session)
                    _models_loaded["dqn"] = True
                    logger.info("DQN loaded via ONNX Runtime DirectML (GPU)")
                    return _models_cache["dqn"]
    except Exception as e:
        logger.debug(f"ONNX DQN load skipped: {e}")

    # Fallback: Keras/TF
    try:
        from src.ml.rl_agent import DQNAgent
        agent = DQNAgent(state_size=state_size, action_size=action_size)
        if os.path.exists(keras_path):
            agent.load(keras_path)
            _models_cache["dqn"] = ("keras", agent)
            _models_loaded["dqn"] = True
            logger.info("DQN Agent loaded (Keras/TensorFlow)")
            return _models_cache["dqn"]
    except Exception as e:
        logger.warning(f"Failed to load DQN: {e}")

    return None


def _get_scaler():
    """Get or load persisted MinMaxScaler for LSTM (fitted during training)."""
    scaler_path = "models/lstm_scaler.pkl"
    # Invalidate if retrain wrote new scaler
    current_mtime = _file_mtime(scaler_path)
    if current_mtime > _models_mtime.get("scaler", 0.0) + 0.5:
        if _models_cache["scaler"] is not None:
            logger.info("Scaler changed on disk — invalidating cache")
            _models_cache["scaler"] = None
    if _models_cache["scaler"] is not None:
        return _models_cache["scaler"], True  # (scaler, is_fitted)
    _models_mtime["scaler"] = current_mtime

    try:
        import pickle
        if os.path.exists(scaler_path):
            with open(scaler_path, 'rb') as f:
                scaler = pickle.load(f)
            _models_cache["scaler"] = scaler
            logger.info("✅ LSTM scaler loaded from disk")
            return scaler, True
    except Exception as e:
        logger.warning(f"⚠️ Failed to load persisted scaler: {e}")

    try:
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        _models_cache["scaler"] = scaler
        return scaler, False  # not fitted — will need fit_transform
    except Exception as e:
        logger.warning(f"⚠️ Failed to create scaler: {e}")

    return None, False


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _fallback_ensemble_result() -> Dict[str, Any]:
    """Zwraca fallback result gdy nie ma danych."""
    return {
        "predictions": {},
        "weights": {},
        "final_score": 0.5,
        "final_direction": "NEUTRAL",
        "confidence": 0.0,
        "ensemble_signal": "CZEKAJ",
        "models_available": 0,
        "error": "Insufficient data"
    }


# ============================================================================
# SHARED FEATURE COMPUTATION (delegates to centralized compute module)
# ============================================================================

def _compute_ensemble_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all prediction features ONCE — delegates to compute.compute_features().
    Single source of truth for feature computation across all models."""
    return compute_features(df)


# ============================================================================
# PREDYKCJE Z POSZCZEGÓLNYCH MODELI
# ============================================================================

def predict_lstm_direction(df: pd.DataFrame, seq_len: int = 60) -> Optional[float]:
    """
    Predykcja LSTM: prawdopodobieństwo wzrostu (0-1).
    Uses ONNX Runtime DirectML (GPU) if available, otherwise Keras/TF.
    Auto-detects seq_len from model if ONNX.
    """
    try:
        lstm_loaded = _load_lstm()
        if lstm_loaded is None:
            return None

        # Auto-detect seq_len from ONNX model input shape
        model_type, model = lstm_loaded
        if model_type == "onnx":
            inp_shape = model.get_inputs()[0].shape  # e.g. [1, 30, 23]
            if len(inp_shape) >= 2 and isinstance(inp_shape[1], int):
                seq_len = inp_shape[1]
        elif model_type == "keras":
            inp_shape = model.input_shape  # e.g. (None, 60, 23)
            if len(inp_shape) >= 2 and inp_shape[1] is not None:
                seq_len = inp_shape[1]

        if len(df) < seq_len + 30:
            logger.debug(f"Za mało danych dla LSTM: {len(df)} < {seq_len+30}")
            return None

        df_copy = _compute_ensemble_features(df)

        if len(df_copy) < seq_len:
            logger.debug("Za mało danych po przygotowaniu cech")
            return None

        data = df_copy[FEATURE_COLS].values[-seq_len:]

        # Normalizuj
        scaler, is_fitted = _get_scaler()
        if scaler is not None:
            if is_fitted:
                data = scaler.transform(data)
            else:
                logger.debug("LSTM scaler nie z treningu — fit_transform (mniej stabilne)")
                data = scaler.fit_transform(data)

        X = data.reshape(1, seq_len, -1)

        # Dispatch: ONNX GPU or Keras CPU
        model_type, model = lstm_loaded
        if model_type == "onnx":
            from src.analysis.compute import onnx_predict
            pred = onnx_predict(model, X.astype(np.float32))
        else:
            pred = model(X, training=False).numpy()

        if pred is None:
            return None
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
    Uses ONNX Runtime DirectML (GPU) if available, otherwise native XGBoost.
    """
    try:
        xgb_loaded = _load_xgb()
        if xgb_loaded is None:
            return None

        if len(df) < 100:
            logger.debug(f"Za mało danych dla XGBoost: {len(df)} < 100")
            return None

        df_copy = _compute_ensemble_features(df)

        if df_copy.empty:
            return None

        X = df_copy[FEATURE_COLS].tail(1)

        if X.empty:
            return None

        model_type, model = xgb_loaded

        try:
            if model_type == "onnx":
                import onnxruntime as ort
                input_name = model.get_inputs()[0].name
                # ONNX XGBoost returns [label, probabilities] — we need probabilities
                results = model.run(None, {input_name: X.values.astype(np.float32)})
                if len(results) >= 2:
                    # results[1] = probabilities dict or array [{0: p0, 1: p1}]
                    probs = results[1]
                    if isinstance(probs, list) and len(probs) > 0:
                        if isinstance(probs[0], dict):
                            if 1 in probs[0]:
                                return float(probs[0][1])
                            logger.warning("XGB ONNX: prob dict missing class-1 key")
                            return None
                        if len(probs[0]) > 1:
                            return float(probs[0][1])
                        logger.warning(f"XGB ONNX: prob array too short ({len(probs[0])})")
                        return None
                    elif isinstance(probs, np.ndarray) and probs.shape[-1] >= 2:
                        return float(probs[0, 1])
                # Malformed output — return None so the ensemble marks this
                # voter 'unavailable' instead of silently injecting neutral
                # 0.5 into the weighted fusion (which used to mask real
                # broken-model failures as "no signal").
                logger.warning(f"XGB ONNX: unexpected output shape, skipping voter")
                return None
            else:
                pred = model.predict_proba(X)
                return float(pred[0, 1])
        except Exception as e:
            logger.debug(f"XGBoost predict error: {e}")
            return None

    except Exception as e:
        logger.debug(f"XGBoost prediction error: {e}")
        return None


def predict_dqn_action(close_prices: np.ndarray, balance: float = 1.0, position: int = 0) -> Optional[dict]:
    """
    Predykcja DQN: akcja (0=hold, 1=buy, 2=sell) + confidence z Q-values.
    Uses ONNX Runtime DirectML (GPU) if available.

    Args:
        close_prices: Ostatnie ~20 cen zamknięcia
        balance: Znormalizowany balans (balance/initial_balance)
        position: Aktualna pozycja (-1=short, 0=none, 1=long)

    Returns:
        dict: {'action': int, 'confidence': float} lub None jeśli błąd
    """
    try:
        dqn_loaded = _load_dqn()
        if dqn_loaded is None:
            return None

        model_type, model = dqn_loaded

        if model_type == "onnx":
            from src.ml.rl_agent import DQNAgent
            temp = DQNAgent.__new__(DQNAgent)
            state = DQNAgent.build_state(temp, close_prices, balance, position)
            from src.analysis.compute import onnx_predict
            q_values = onnx_predict(model, state.reshape(1, -1).astype(np.float32))
            if q_values is not None:
                action = int(np.argmax(q_values[0]))
                # Confidence z softmax Q-values
                q = q_values[0]
                exp_q = np.exp(q - np.max(q))  # numerycznie stabilny softmax
                softmax = exp_q / exp_q.sum()
                confidence = float(softmax[action])
                return {'action': action, 'confidence': confidence}
            return None
        else:
            # Keras agent — uzyskaj Q-values bezpośrednio
            state = model.build_state(close_prices, balance, position)
            q_values = model.model(state.reshape(1, -1), training=False).numpy()
            action = int(np.argmax(q_values[0]))
            q = q_values[0]
            exp_q = np.exp(q - np.max(q))
            softmax = exp_q / exp_q.sum()
            confidence = float(softmax[action])
            return {'action': action, 'confidence': confidence}

    except Exception as e:
        logger.debug(f"DQN prediction error: {e}")
        return None


# ============================================================================
# DYNAMIC WEIGHTS (persisted in DB, updated by self-learning)
# ============================================================================

def _load_dynamic_weights() -> Dict[str, float]:
    """Ładuj wagi ensemble z bazy danych. Fallback na domyślne.
    Inicjalizuje brakujące wagi w bazie przy pierwszym uruchomieniu."""
    default_weights = {
        "smc": 0.25,
        "attention": 0.15,
        "dpformer": 0.15,
        "lstm": 0.15,
        "xgb": 0.18,
        "dqn": 0.12,
        # deeptrans is ignored unless QUANT_ENABLE_TRANSFORMER=1 — starts
        # tiny so self-learning has to earn its weight.
        "deeptrans": 0.05,
    }
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        loaded = {}
        for model_name, default_val in default_weights.items():
            val = db.get_param(f"ensemble_weight_{model_name}", None)
            if val is None:
                # Initialize missing weight in DB with default value
                db.set_param(f"ensemble_weight_{model_name}", default_val)
                val = default_val
            loaded[model_name] = val
        # Normalizuj wagi do sumy = 1
        total = sum(loaded.values())
        if total > 0:
            loaded = {k: v / total for k, v in loaded.items()}
        return loaded
    except Exception:
        return default_weights


_WEIGHT_MIN = 0.05
_WEIGHT_MAX = 0.60
_MAX_STEP = 0.05  # hard per-update cap — belt-and-braces against a single bad batch
_TARGET_HIGH = 0.60  # asymptote for consistently-correct models
_TARGET_LOW = 0.05   # asymptote for consistently-wrong models


def _ema_update(current: float, target: float, alpha: float) -> float:
    """EMA-smoothed weight update toward target.

    new = current*(1-alpha) + target*alpha

    Converges toward target geometrically rather than linearly (old code was
    additive + clamp, which let a model race from 0.05 → 0.60 in 28 wins and
    back down in 28 losses — too reactive for the live-trade resolution rate).
    Per-update delta is also capped at _MAX_STEP as a defensive ceiling.
    """
    raw = current * (1.0 - alpha) + target * alpha
    delta = raw - current
    if delta > _MAX_STEP:
        raw = current + _MAX_STEP
    elif delta < -_MAX_STEP:
        raw = current - _MAX_STEP
    return max(_WEIGHT_MIN, min(_WEIGHT_MAX, raw))


def update_ensemble_weights(correct_models: list, incorrect_models: list, learning_rate: float = 0.02):
    """
    Aktualizuj wagi ensemble na podstawie które modele miały rację.
    Wywoływane po rozwiązaniu trade'u (resolve_trades_task).

    Używa EMA smoothing (alpha=learning_rate) zamiast liniowego add/sub —
    stabilniej i asymptotycznie zbieżne do _TARGET_HIGH/LOW. Clamp do
    [_WEIGHT_MIN, _WEIGHT_MAX] + hard cap _MAX_STEP na pojedynczy update.

    Aktualizuje też liczniki per-model (correct/incorrect) w dynamic_params
    do auditu historycznej skuteczności każdego modelu.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        current = _load_dynamic_weights()

        for model in correct_models:
            if model in current:
                new_w = _ema_update(current[model], _TARGET_HIGH, learning_rate)
                db.set_param(f"ensemble_weight_{model}", new_w)
            prev = db.get_param(f"model_{model}_correct", 0) or 0
            try:
                prev = int(float(prev))
            except (ValueError, TypeError):
                prev = 0
            db.set_param(f"model_{model}_correct", prev + 1)

        for model in incorrect_models:
            if model in current:
                new_w = _ema_update(current[model], _TARGET_LOW, learning_rate)
                db.set_param(f"ensemble_weight_{model}", new_w)
            prev = db.get_param(f"model_{model}_incorrect", 0) or 0
            try:
                prev = int(float(prev))
            except (ValueError, TypeError):
                prev = 0
            db.set_param(f"model_{model}_incorrect", prev + 1)

        logger.info(f"📊 Ensemble weights updated: correct={correct_models}, incorrect={incorrect_models}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to update ensemble weights: {e}")


def get_model_track_record() -> Dict[str, Dict]:
    """Zwraca historyczny track record per-model: {model: {correct, incorrect, accuracy, n}}.

    Używane do auditu self-learning weight updates: czy model z wysoką wagą
    faktycznie miał wysoką accuracy, czy został sztucznie pompniety.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        models = ["smc", "attention", "dpformer", "lstm", "xgb", "dqn", "deeptrans"]
        result = {}
        for m in models:
            correct = db.get_param(f"model_{m}_correct", 0) or 0
            incorrect = db.get_param(f"model_{m}_incorrect", 0) or 0
            try:
                correct = int(float(correct))
                incorrect = int(float(incorrect))
            except (ValueError, TypeError):
                correct, incorrect = 0, 0
            n = correct + incorrect
            acc = (correct / n) if n > 0 else None
            result[m] = {"correct": correct, "incorrect": incorrect, "n": n, "accuracy": acc}
        return result
    except Exception as e:
        logger.warning(f"Failed to get model track record: {e}")
        return {}


def _persist_prediction(results: Dict):
    """Zapisz predykcję ensemble do bazy dla post-hoc analizy (z agreement + regime)."""
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        import json
        predictions_json = json.dumps({
            k: {kk: (str(vv) if not isinstance(vv, (int, float, bool, type(None))) else vv)
                for kk, vv in v.items()}
            for k, v in results.get('predictions', {}).items()
        })

        # Model agreement i regime data
        agreement = results.get('model_agreement', {})
        agreement_ratio = agreement.get('ratio', 0)
        vol_pctile = results.get('volatility_percentile', 0.5)
        vol_regime = "low" if vol_pctile < 0.25 else ("high" if vol_pctile > 0.75 else "normal")

        # Rozszerzony zapis — dodajemy agreement i regime
        predictions_json_ext = json.dumps({
            'predictions': {
                k: {kk: (str(vv) if not isinstance(vv, (int, float, bool, type(None))) else vv)
                    for kk, vv in v.items()}
                for k, v in results.get('predictions', {}).items()
            },
            'model_agreement': agreement,
            'vol_regime': vol_regime,
            'regime_weights': {k: round(v, 4) for k, v in results.get('regime_weights', {}).items()},
        })

        # Per-voter columns mirror the JSON blob for fast SQL filtering
        # (e.g. "give me rows where deeptrans disagreed with SMC"). Writing
        # None for absent voters keeps historical queries clean.
        def _voter_value(name: str):
            v = results['predictions'].get(name, {})
            if 'status' in v:  # voter marked 'unavailable'
                return None
            return v.get('value')

        db._execute("""
            INSERT INTO ml_predictions
            (lstm_pred, xgb_pred, dqn_action, ensemble_score, ensemble_signal,
             confidence, predictions_json,
             smc_pred, attention_pred, dpformer_pred, deeptrans_pred)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            results['predictions'].get('lstm', {}).get('value'),
            results['predictions'].get('xgb', {}).get('value'),
            results['predictions'].get('dqn', {}).get('action'),
            results.get('final_score', 0),
            results.get('ensemble_signal', 'CZEKAJ'),
            results.get('confidence', 0),
            predictions_json_ext,
            _voter_value('smc'),
            _voter_value('attention'),
            _voter_value('dpformer'),
            _voter_value('deeptrans'),
        ))
    except Exception as e:
        # Escalated from debug -> warning. Losing ensemble predictions means
        # losing the audit trail used by /api/models/voter-attribution. If
        # this fires regularly something is structurally broken (schema,
        # disk, lock timeout) and we want it visible.
        logger.warning(f"_persist_prediction failed: {e}")


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
                from src.data.data_sources import get_provider
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

    # Domyślne wagi – ładuj dynamiczne z bazy jeśli dostępne
    if weights is None:
        weights = _load_dynamic_weights()

    results: Dict[str, Any] = {
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

    # --- 2. Attention (TFT-lite) Prediction ---
    try:
        from src.ml.attention_model import predict_attention
        attn_pred = predict_attention(df)
        if attn_pred is not None:
            results["predictions"]["attention"] = {
                "value": attn_pred,
                "direction": "LONG" if attn_pred > 0.5 else "SHORT",
                "confidence": abs(attn_pred - 0.5) * 2
            }
        else:
            results["predictions"]["attention"] = {
                "value": 0.5, "direction": "NEUTRAL",
                "confidence": 0.0, "status": "unavailable"
            }
    except Exception as e:
        logger.debug(f"Attention model skipped: {e}")
        results["predictions"]["attention"] = {
            "value": 0.5, "direction": "NEUTRAL",
            "confidence": 0.0, "status": "unavailable"
        }

    # --- 2c. DeepTrans (pre-LN deep transformer, flag-gated) ---
    # QUANT_ENABLE_TRANSFORMER=1 activates. Otherwise `predict_deeptrans`
    # returns None and the voter is marked unavailable (skipped in fusion).
    try:
        from src.ml.transformer_model import predict_deeptrans
        dt_pred = predict_deeptrans(df)
        if dt_pred is not None:
            results["predictions"]["deeptrans"] = {
                "value": dt_pred,
                "direction": "LONG" if dt_pred > 0.5 else "SHORT",
                "confidence": abs(dt_pred - 0.5) * 2,
            }
        else:
            results["predictions"]["deeptrans"] = {
                "value": 0.5, "direction": "NEUTRAL",
                "confidence": 0.0, "status": "unavailable"
            }
    except Exception as e:
        logger.debug(f"DeepTrans skipped: {e}")
        results["predictions"]["deeptrans"] = {
            "value": 0.5, "direction": "NEUTRAL",
            "confidence": 0.0, "status": "unavailable"
        }

    # --- 2b. DPformer (Decomposition + LSTM + Attention Fusion) ---
    try:
        from src.ml.decompose_model import predict_decompose
        dp_pred = predict_decompose(df)
        if dp_pred is not None:
            results["predictions"]["dpformer"] = {
                "value": dp_pred,
                "direction": "LONG" if dp_pred > 0.5 else "SHORT",
                "confidence": abs(dp_pred - 0.5) * 2
            }
        else:
            results["predictions"]["dpformer"] = {
                "value": 0.5, "direction": "NEUTRAL",
                "confidence": 0.0, "status": "unavailable"
            }
    except Exception as e:
        logger.debug(f"DPformer skipped: {e}")
        results["predictions"]["dpformer"] = {
            "value": 0.5, "direction": "NEUTRAL",
            "confidence": 0.0, "status": "unavailable"
        }

    # --- Calibrator (Platt Scaling) ---
    try:
        from src.ml.model_calibration import get_calibrator
        calibrator = get_calibrator()
    except (ImportError, AttributeError):
        calibrator = None

    # --- 3. LSTM Prediction ---
    lstm_pred = predict_lstm_direction(df)
    if lstm_pred is not None:
        raw_lstm = lstm_pred
        if calibrator:
            lstm_pred = calibrator.calibrate("lstm", lstm_pred)
        results["predictions"]["lstm"] = {
            "value": lstm_pred,
            "raw_value": raw_lstm,
            "direction": "LONG" if lstm_pred > 0.5 else "SHORT",
            "confidence": abs(lstm_pred - 0.5) * 2,
            "calibrated": calibrator.is_calibrated("lstm") if calibrator else False,
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
        raw_xgb = xgb_pred
        if calibrator:
            xgb_pred = calibrator.calibrate("xgb", xgb_pred)
        results["predictions"]["xgb"] = {
            "value": xgb_pred,
            "raw_value": raw_xgb,
            "direction": "LONG" if xgb_pred > 0.5 else "SHORT",
            "confidence": abs(xgb_pred - 0.5) * 2,
            "calibrated": calibrator.is_calibrated("xgb") if calibrator else False,
        }
    else:
        results["predictions"]["xgb"] = {
            "value": 0.5,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": "unavailable"
        }

    # --- 4. DQN Action (z dynamicznym confidence z Q-values) ---
    norm_balance = balance / initial_balance if initial_balance > 0 else 1.0
    close_prices = df['close'].tail(20).values

    dqn_result = predict_dqn_action(close_prices, norm_balance, position)
    if dqn_result is not None:
        dqn_action = dqn_result['action']
        dqn_confidence = dqn_result['confidence']

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

        raw_dqn = dqn_signal
        if calibrator:
            dqn_signal = calibrator.calibrate("dqn", dqn_signal)
        results["predictions"]["dqn"] = {
            "value": dqn_signal,
            "raw_value": raw_dqn,
            "action": dqn_action,
            "direction": dqn_direction,
            "confidence": dqn_confidence,
            "calibrated": calibrator.is_calibrated("dqn") if calibrator else False,
        }
    else:
        results["predictions"]["dqn"] = {
            "value": 0.5,
            "action": None,
            "direction": "NEUTRAL",
            "confidence": 0.0,
            "status": "unavailable"
        }

    # ========== REGIME-DEPENDENT WEIGHTS ==========
    # Adjust model weights based on volatility regime + historical per-regime accuracy
    try:
        vol_pctile = df['close'].pct_change().rolling(20).std().rank(pct=True).iloc[-1]
    except Exception:
        vol_pctile = 0.5

    vol_regime = "low" if vol_pctile < 0.25 else ("high" if vol_pctile > 0.75 else "normal")

    regime_weights = dict(weights)  # copy

    # Spróbuj załadować historyczną accuracy per-regime z bazy
    try:
        from src.core.database import NewsDB
        _rdb = NewsDB()
        regime_history = _rdb.get_model_accuracy_by_regime(vol_regime)
        if len(regime_history) >= 10:
            # Oblicz accuracy ensemble w tym regime
            regime_wins = sum(1 for r in regime_history if r[1] == "WIN")
            regime_total = len(regime_history)
            regime_wr = regime_wins / regime_total

            # Jeśli WR w tym regime jest niski, zwiększ próg ostrożności
            if regime_wr < 0.40:
                logger.info(f"⚠️ Ensemble: regime={vol_regime} WR={regime_wr:.0%} — ostrożniejsze wagi")
                # Wzmocnij SMC (rule-based, stabilniejszy w złych reżimach)
                regime_weights['smc'] = regime_weights.get('smc', 0.3) * 1.3
    except Exception as e:
        logger.warning(f"Ensemble regime history lookup failed: {e} — "
                       f"falling back to default weights")

    if vol_pctile < 0.25:
        # Low volatility — XGB (mean reversion) stronger, LSTM/DQN weaker
        regime_weights['xgb'] = regime_weights.get('xgb', 0.2) * 1.5
        regime_weights['lstm'] = regime_weights.get('lstm', 0.25) * 0.7
    elif vol_pctile > 0.75:
        # High volatility — LSTM/DQN (trend) stronger, XGB weaker
        regime_weights['lstm'] = regime_weights.get('lstm', 0.25) * 1.4
        regime_weights['dqn'] = regime_weights.get('dqn', 0.2) * 1.3
        regime_weights['xgb'] = regime_weights.get('xgb', 0.2) * 0.7
    # Normalize
    rw_total = sum(regime_weights.values())
    if rw_total > 0:
        regime_weights = {k: v / rw_total for k, v in regime_weights.items()}

    # ========== FUZJA PREDYKCJI ==========
    total_weight = 0.0
    weighted_sum = 0.0
    confidence_sum = 0.0
    available_models = 0
    # Model Agreement tracking
    models_long = 0
    models_short = 0
    models_neutral = 0

    for model_name, weight in regime_weights.items():
        if model_name in results["predictions"]:
            pred = results["predictions"][model_name]
            if "status" not in pred:  # Model dostepny
                weighted_sum += pred["value"] * weight
                confidence_sum += pred.get("confidence", 0.5) * weight
                total_weight += weight
                available_models += 1
                # Count directional agreement
                if pred["value"] > 0.55:
                    models_long += 1
                elif pred["value"] < 0.45:
                    models_short += 1
                else:
                    models_neutral += 1

    # Znormalizuj wagi
    if total_weight > 0:
        results["final_score"] = weighted_sum / total_weight
        results["confidence"] = confidence_sum / total_weight
    else:
        # Degenerate case — all voters unavailable or all weights zero.
        # Force CZEKAJ immediately so downstream signal logic doesn't
        # treat NaN/default 0.5 as "neutral but valid".
        results["final_score"] = 0.5
        results["confidence"] = 0.0
        results["ensemble_signal"] = "CZEKAJ"
        logger.warning("Ensemble: total_weight=0 (no active voters) — forcing CZEKAJ")

    # ========== MODEL AGREEMENT FILTER ==========
    # Sprawdź czy modele się zgadzają w kierunku
    # Wymagamy >= 60% modeli w tym samym kierunku (ale nie blokujemy przy 2 modelach)
    agreement_ratio = 0.0
    agreement_direction = "NEUTRAL"
    if available_models > 0:
        long_ratio = models_long / available_models
        short_ratio = models_short / available_models
        agreement_ratio = max(long_ratio, short_ratio)
        if long_ratio > short_ratio:
            agreement_direction = "LONG"
        elif short_ratio > long_ratio:
            agreement_direction = "SHORT"

    results["model_agreement"] = {
        "ratio": round(agreement_ratio, 2),
        "direction": agreement_direction,
        "long": models_long,
        "short": models_short,
        "neutral": models_neutral,
    }

    # ========== HIGH-CONFIDENCE MODEL COUNT ==========
    # Count models with confidence > 50% in the majority direction
    high_conf_count = 0
    for model_name in regime_weights:
        if model_name in results["predictions"]:
            pred = results["predictions"][model_name]
            if "status" not in pred and pred.get("confidence", 0) > 0.50:
                pred_dir = "LONG" if pred["value"] > 0.55 else ("SHORT" if pred["value"] < 0.45 else "NEUTRAL")
                if pred_dir == agreement_direction:
                    high_conf_count += 1

    results["model_agreement"]["high_confidence_count"] = high_conf_count

    # ========== OSTATECZNY SYGNAL ==========
    # Confidence threshold: 0.30 (professional level)
    # Agreement: >= 60% modeli musi się zgadzać
    # Require: 2+ models with confidence > 50% in same direction
    if available_models == 0:
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "NEUTRAL"
    elif results["confidence"] < 0.30:
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "UNCERTAIN"
    elif agreement_ratio < 0.60 and available_models >= 3:
        # Modele zbyt podzielone — nie ryzykuj
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "CONFLICTED"
        logger.info(f"Ensemble: modele podzielone (agreement={agreement_ratio:.0%}) — CZEKAJ")
    elif high_conf_count < 2 and available_models >= 3:
        # Nie wystarczająco pewnych modeli
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "LOW_CONVICTION"
        logger.info(f"Ensemble: only {high_conf_count} high-confidence models — CZEKAJ")
    elif results["final_score"] > 0.58:
        results["ensemble_signal"] = "LONG"
        results["final_direction"] = "LONG"
    elif results["final_score"] < 0.42:
        results["ensemble_signal"] = "SHORT"
        results["final_direction"] = "SHORT"
    else:
        results["ensemble_signal"] = "CZEKAJ"
        results["final_direction"] = "NEUTRAL"

    # ========== SIGNAL CONFIRMATION (post-filter) ==========
    if results["ensemble_signal"] in ("LONG", "SHORT"):
        try:
            from src.analysis.signal_confirmation import confirm_signal
            confirmation = confirm_signal(
                df=df,
                signal_direction=results["ensemble_signal"],
                ensemble_score=results["final_score"],
                ensemble_confidence=results["confidence"],
                symbol=symbol,
                use_mtf=False,  # MTF costs API credits — use only in scanner
            )
            results["confirmation"] = confirmation
            if not confirmation["confirmed"]:
                results["ensemble_signal"] = "CZEKAJ"
                results["final_direction"] = "FILTERED"
            else:
                # Boost confidence with confirmation
                results["confidence"] = confirmation["final_confidence"]
        except Exception as e:
            logger.debug(f"Signal confirmation skipped: {e}")

    results["models_available"] = available_models
    results["regime_weights"] = regime_weights
    results["volatility_percentile"] = round(vol_pctile, 3)

    # Instrument ensemble outcome for /api/metrics (confidence distribution + signal rate)
    try:
        from src.ops.metrics import (
            ensemble_confidence,
            ensemble_signals_long,
            ensemble_signals_short,
            ensemble_signals_wait,
        )
        ensemble_confidence.observe(float(results.get("confidence", 0.0)))
        _sig = results.get("ensemble_signal", "CZEKAJ")
        if _sig == "LONG":
            ensemble_signals_long.inc()
        elif _sig == "SHORT":
            ensemble_signals_short.inc()
        else:
            ensemble_signals_wait.inc()
    except Exception:
        pass

    logger.info(
        f"Ensemble: {available_models} modele | "
        f"Score: {results.get('final_score', 0):.3f} | "
        f"Confidence: {results.get('confidence', 0):.1%} | "
        f"Signal: {results.get('ensemble_signal', 'CZEKAJ')} | "
        f"Vol regime: {vol_pctile:.0%}"
    )

    # Persist prediction for post-hoc analysis
    _persist_prediction(results)

    return results

