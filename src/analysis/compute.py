"""
compute.py — Centralized compute acceleration module.

Provides:
  - GPU detection (CUDA, DirectML, Apple Metal)
  - CuPy/NumPy abstraction (xp = cupy if GPU else numpy)
  - Numba JIT helpers for hot loops
  - TensorFlow / XGBoost GPU configuration
  - Shared feature computation (single source of truth)
"""

import os
import numpy as np
import pandas as pd
from functools import lru_cache
from src.core.logger import logger

# ============================================================================
# GPU / ACCELERATOR DETECTION
# ============================================================================

@lru_cache(maxsize=1)
def detect_gpu() -> dict:
    """Detect available GPU acceleration. Cached — called once per process.

    Supports: NVIDIA CUDA, AMD/Intel via DirectML (ONNX Runtime), CuPy, Numba.
    """
    info = {
        "tf_gpu": False,
        "tf_devices": [],
        "xgb_gpu": None,        # 'cuda' | 'gpu_hist' | None
        "cupy_available": False,
        "numba_available": False,
        "numba_cuda": False,
        "onnx_directml": False,  # ONNX Runtime DirectML (AMD/Intel/NVIDIA)
        "onnx_providers": [],    # available ONNX execution providers
    }

    # --- TensorFlow GPU ---
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
            try:
                tf.keras.mixed_precision.set_global_policy('mixed_float16')
                logger.info(f"TF GPU: {[g.name for g in gpus]} (mixed_float16)")
            except (RuntimeError, AttributeError, ValueError):
                logger.info(f"TF GPU: {[g.name for g in gpus]}")
            info["tf_gpu"] = True
            info["tf_devices"] = [g.name for g in gpus]
    except Exception as e:
        logger.debug(f"TF GPU detection skipped: {e}")

    # --- ONNX Runtime DirectML (AMD/Intel/NVIDIA on Windows) ---
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        info["onnx_providers"] = providers
        if 'DmlExecutionProvider' in providers:
            info["onnx_directml"] = True
            logger.info(f"ONNX Runtime DirectML GPU enabled (providers: {providers})")
        elif 'CUDAExecutionProvider' in providers:
            logger.info(f"ONNX Runtime CUDA GPU enabled")
        else:
            logger.info(f"ONNX Runtime: CPU only (providers: {providers})")
    except ImportError:
        logger.debug("ONNX Runtime not installed")

    # --- XGBoost GPU ---
    # First check if NVIDIA GPU actually exists (prevents false positive on AMD/Intel)
    _has_nvidia = False
    try:
        import subprocess
        _nv = subprocess.run(
            ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=3
        )
        _has_nvidia = _nv.returncode == 0 and len(_nv.stdout.strip()) > 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    if _has_nvidia:
        try:
            from xgboost import XGBClassifier
            _t = XGBClassifier(device='cuda', tree_method='hist',
                               n_estimators=1, verbosity=0)
            _t.fit([[1]*5]*4, [0, 1, 0, 1])
            info["xgb_gpu"] = "cuda"
            logger.info("XGBoost GPU (CUDA) enabled")
        except (ImportError, RuntimeError, ValueError):
            try:
                from xgboost import XGBClassifier
                _t = XGBClassifier(tree_method='gpu_hist', n_estimators=1, verbosity=0)
                _t.fit([[1]*5]*4, [0, 1, 0, 1])
                info["xgb_gpu"] = "gpu_hist"
                logger.info("XGBoost GPU (gpu_hist) enabled")
            except (ImportError, RuntimeError, ValueError):
                logger.info("XGBoost: CPU histogram mode (NVIDIA GPU present but CUDA unavailable)")
    else:
        logger.info("XGBoost: CPU histogram mode (no NVIDIA GPU)")

    # --- CuPy (GPU-accelerated NumPy) ---
    try:
        import cupy as cp
        _ = cp.array([1.0])  # test allocation
        info["cupy_available"] = True
        logger.info(f"CuPy available (CUDA {cp.cuda.runtime.runtimeGetVersion()})")
    except Exception:
        pass

    # --- Numba ---
    try:
        import numba
        info["numba_available"] = True
        try:
            from numba import cuda as numba_cuda
            if numba_cuda.is_available():
                info["numba_cuda"] = True
                logger.info("Numba CUDA available")
        except Exception:
            pass
        logger.info(f"Numba {numba.__version__} available (JIT compilation)")
    except ImportError:
        logger.debug("Numba not installed — JIT acceleration disabled")

    return info


# ============================================================================
# ARRAY BACKEND (CuPy if GPU, else NumPy)
# ============================================================================

def get_array_module():
    """Return cupy if GPU available, else numpy. Use as: xp = get_array_module()"""
    info = detect_gpu()
    if info["cupy_available"]:
        import cupy as cp
        return cp
    return np


def to_numpy(arr) -> np.ndarray:
    """Convert CuPy array back to NumPy (no-op if already NumPy)."""
    if hasattr(arr, 'get'):  # CuPy array
        return arr.get()
    return np.asarray(arr)


# ============================================================================
# XGBoost GPU PARAMS
# ============================================================================

def get_xgb_params() -> dict:
    """Return XGBoost params dict with GPU if available."""
    info = detect_gpu()
    base = {'tree_method': 'hist', 'n_jobs': -1}
    if info["xgb_gpu"] == "cuda":
        return {**base, 'device': 'cuda'}
    elif info["xgb_gpu"] == "gpu_hist":
        return {**base, 'tree_method': 'gpu_hist'}
    return base


def get_tf_batch_size(default_cpu: int = 32, default_gpu: int = 128) -> int:
    """Return optimal batch size based on GPU availability."""
    info = detect_gpu()
    if info["tf_gpu"]:
        return default_gpu
    # DirectML GPU — use medium batch (GPU present but via ONNX, not native TF)
    if info["onnx_directml"]:
        return min(default_gpu, 64)
    return default_cpu


# ============================================================================
# ONNX RUNTIME GPU INFERENCE (DirectML — AMD/Intel/NVIDIA on Windows)
# ============================================================================

_onnx_sessions = {}  # cache: model_path -> ort.InferenceSession


def get_onnx_providers() -> list:
    """Return best available ONNX execution providers (GPU first)."""
    info = detect_gpu()
    providers = []
    if info["onnx_directml"]:
        providers.append('DmlExecutionProvider')
    if 'CUDAExecutionProvider' in info.get("onnx_providers", []):
        providers.append('CUDAExecutionProvider')
    providers.append('CPUExecutionProvider')  # always fallback
    return providers


def convert_keras_to_onnx(keras_model_path: str, onnx_path: str = None,
                          opset: int = 15) -> str:
    """Convert Keras .keras model to ONNX format for GPU inference via DirectML.

    Uses tf2onnx.convert.from_function with a tf.function wrapper — compatible
    with TF 2.20+ and Keras 3.x models (LSTM, DQN, etc.).
    Returns path to the ONNX model file, or None on failure.
    """
    if onnx_path is None:
        onnx_path = keras_model_path.replace('.keras', '.onnx')

    if os.path.exists(onnx_path):
        # Check if ONNX is newer than Keras model
        if os.path.getmtime(onnx_path) >= os.path.getmtime(keras_model_path):
            logger.debug(f"ONNX model up-to-date: {onnx_path}")
            return onnx_path

    try:
        import tf2onnx
        import tensorflow as tf

        model = tf.keras.models.load_model(keras_model_path)

        # Build input signature with fixed batch=1
        input_sig = []
        for inp in model.inputs:
            shape = list(inp.shape)
            shape[0] = 1
            input_sig.append(tf.TensorSpec(shape=shape, dtype=tf.float32))

        # Wrap model in tf.function for tracing
        @tf.function(input_signature=input_sig)
        def predict_fn(*args):
            return model(args[0] if len(args) == 1 else args, training=False)

        model_proto, _ = tf2onnx.convert.from_function(
            predict_fn, input_signature=input_sig,
            opset=opset, output_path=onnx_path
        )
        logger.info(f"Converted {keras_model_path} -> {onnx_path} (opset {opset})")
        return onnx_path
    except Exception as e:
        logger.warning(f"ONNX conversion failed for {keras_model_path}: {e}")
        return None


def get_onnx_session(model_path: str):
    """Get or create an ONNX Runtime inference session with GPU (DirectML/CUDA).
    Caches sessions for reuse."""
    if model_path in _onnx_sessions:
        return _onnx_sessions[model_path]

    try:
        import onnxruntime as ort
        providers = get_onnx_providers()
        session = ort.InferenceSession(model_path, providers=providers)
        actual = session.get_providers()
        _onnx_sessions[model_path] = session
        logger.info(f"ONNX session created: {model_path} (providers: {actual})")
        return session
    except Exception as e:
        logger.warning(f"ONNX session creation failed: {e}")
        return None


def onnx_predict(session, input_data: np.ndarray) -> np.ndarray:
    """Run inference on ONNX model. input_data must be float32 numpy array."""
    if session is None:
        return None
    try:
        input_name = session.get_inputs()[0].name
        result = session.run(None, {input_name: input_data.astype(np.float32)})
        return result[0]
    except Exception as e:
        logger.debug(f"ONNX inference error: {e}")
        return None


def convert_xgboost_to_onnx(xgb_model, n_features: int, onnx_path: str = "models/xgb.onnx") -> str:
    """Convert trained XGBoost model to ONNX for GPU inference via DirectML.
    Handles named features by temporarily remapping to f0..fN format.
    Returns path to ONNX file, or None on failure."""
    if os.path.exists(onnx_path):
        pkl_path = onnx_path.replace('.onnx', '.pkl')
        if os.path.exists(pkl_path) and os.path.getmtime(onnx_path) >= os.path.getmtime(pkl_path):
            return onnx_path

    try:
        from onnxmltools import convert_xgboost as _convert_xgb
        from onnxmltools.convert.common.data_types import FloatTensorType
        import onnx

        # onnxmltools requires numeric feature names (f0, f1, ...)
        # Temporarily remap named features in the booster
        booster = xgb_model.get_booster()
        original_names = booster.feature_names
        if original_names and not all(n.startswith('f') and n[1:].isdigit() for n in original_names):
            booster.feature_names = [f'f{i}' for i in range(n_features)]

        initial_type = [('features', FloatTensorType([None, n_features]))]
        onnx_model = _convert_xgb(xgb_model, initial_types=initial_type)
        onnx.save(onnx_model, onnx_path)

        # Restore original feature names
        if original_names:
            booster.feature_names = original_names

        logger.info(f"XGBoost -> ONNX: {onnx_path}")
        return onnx_path
    except Exception as e:
        logger.debug(f"XGBoost ONNX conversion failed: {e}")
    return None


def print_gpu_summary():
    """Print a clear summary of GPU acceleration status."""
    info = detect_gpu()
    lines = [
        "=" * 60,
        "GPU ACCELERATION STATUS",
        "=" * 60,
    ]

    if info["onnx_directml"]:
        lines.append("[GPU] ONNX Runtime DirectML — AMD/Intel GPU aktywne")
        lines.append("      -> LSTM inference: GPU")
        lines.append("      -> DQN inference:  GPU")
        lines.append("      -> XGBoost inference: GPU (jesli ONNX skonwertowany)")
    elif 'CUDAExecutionProvider' in info.get("onnx_providers", []):
        lines.append("[GPU] ONNX Runtime CUDA — NVIDIA GPU aktywne")

    if info["tf_gpu"]:
        lines.append(f"[GPU] TensorFlow GPU: {info['tf_devices']}")
        lines.append("      -> LSTM/DQN training: GPU")
    else:
        lines.append("[CPU] TensorFlow: CPU (training)")
        if info["onnx_directml"]:
            lines.append("      -> Ale inference na GPU przez ONNX DirectML")

    if info["xgb_gpu"]:
        lines.append(f"[GPU] XGBoost: {info['xgb_gpu']}")
    else:
        lines.append("[CPU] XGBoost: CPU histogram (training)")

    if info["numba_available"]:
        lines.append(f"[JIT] Numba: aktywne (kompilacja hot loops)")
        lines.append("      -> swing detection, equity simulation: 10-50x szybciej")

    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================================
# NUMBA JIT ACCELERATED FUNCTIONS
# ============================================================================

try:
    from numba import njit, prange

    @njit(cache=True)
    def _swing_points_numba(highs, lows, window):
        """Detect swing highs/lows — O(n*window) with Numba JIT.
        Returns (last_swing_high, last_swing_high_idx, last_swing_low, last_swing_low_idx)."""
        n = len(highs)
        last_sh = highs[0]
        last_sh_idx = 0
        last_sl = lows[0]
        last_sl_idx = 0

        for i in range(window, n - window):
            is_high = True
            is_low = True
            for j in range(i - window, i + window + 1):
                if j == i:
                    continue
                if highs[j] > highs[i]:
                    is_high = False
                if lows[j] < lows[i]:
                    is_low = False
                if not is_high and not is_low:
                    break
            if is_high:
                last_sh = highs[i]
                last_sh_idx = i
            if is_low:
                last_sl = lows[i]
                last_sl_idx = i

        return last_sh, last_sh_idx, last_sl, last_sl_idx

    @njit(cache=True)
    def _find_all_swings_numba(values, lookback):
        """Find all swing highs and lows indices in values array.
        Returns (swing_high_indices, swing_low_indices) as lists."""
        n = len(values)
        sh_indices = []
        sl_indices = []
        for i in range(lookback, n - lookback):
            is_high = True
            is_low = True
            for j in range(i - lookback, i + lookback + 1):
                if j == i:
                    continue
                if values[j] > values[i]:
                    is_high = False
                if values[j] < values[i]:
                    is_low = False
                if not is_high and not is_low:
                    break
            if is_high:
                sh_indices.append(i)
            if is_low:
                sl_indices.append(i)
        return sh_indices, sl_indices

    @njit(cache=True)
    def _equity_simulation_numba(dists, tp_dists, is_profit, risk_pct,
                                  min_tp_mult, target_rr, initial_equity):
        """Vectorized-filter + sequential equity simulation with Numba JIT.
        Returns (final_equity, total_trades)."""
        n = len(dists)
        equity = initial_equity
        total_trades = 0

        for i in range(n):
            if dists[i] <= 0:
                continue
            min_tp = dists[i] * target_rr
            alt_tp = dists[i] * min_tp_mult
            if alt_tp > min_tp:
                min_tp = alt_tp
            if min_tp < 5.0:
                min_tp = 5.0
            if tp_dists[i] < min_tp:
                continue

            risk_usd = equity * (risk_pct / 100.0)
            lot = risk_usd / (dists[i] * 100.0)
            if lot < 0.01:
                lot = 0.01

            if is_profit[i]:
                equity += tp_dists[i] * lot * 100.0
            else:
                equity -= risk_usd
            total_trades += 1

        return equity, total_trades

    @njit(cache=True)
    def _equity_sim_with_drawdown_numba(dists, tp_dists, is_profit, risk_pct,
                                         min_tp_mult, target_rr, initial_equity):
        """Equity simulation with max drawdown tracking. For Bayesian optimization."""
        n = len(dists)
        equity = initial_equity
        peak = equity
        max_dd = 0.0

        for i in range(n):
            if dists[i] <= 0:
                continue
            min_tp = dists[i] * target_rr
            alt_tp = dists[i] * min_tp_mult
            if alt_tp > min_tp:
                min_tp = alt_tp
            if min_tp < 5.0:
                min_tp = 5.0
            if tp_dists[i] < min_tp * 0.8:
                continue

            risk_usd = equity * (risk_pct / 100.0)
            lot = risk_usd / (dists[i] * 100.0)
            if lot < 0.01:
                lot = 0.01

            if is_profit[i]:
                equity += tp_dists[i] * lot * 100.0
            else:
                equity -= risk_usd

            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

        return equity, max_dd

    NUMBA_AVAILABLE = True
    logger.info("Numba JIT functions compiled and cached")

except ImportError:
    NUMBA_AVAILABLE = False
    logger.debug("Numba not available — using pure NumPy fallbacks")

    # Pure NumPy fallbacks
    def _swing_points_numba(highs, lows, window):
        n = len(highs)
        last_sh = highs[0]
        last_sh_idx = 0
        last_sl = lows[0]
        last_sl_idx = 0
        for i in range(window, n - window):
            is_high = all(highs[i] >= highs[j] for j in range(i-window, i+window+1) if j != i)
            is_low = all(lows[i] <= lows[j] for j in range(i-window, i+window+1) if j != i)
            if is_high:
                last_sh = highs[i]
                last_sh_idx = i
            if is_low:
                last_sl = lows[i]
                last_sl_idx = i
        return last_sh, last_sh_idx, last_sl, last_sl_idx

    def _find_all_swings_numba(values, lookback):
        n = len(values)
        sh = []
        sl = []
        for i in range(lookback, n - lookback):
            is_high = all(values[i] >= values[j] for j in range(i-lookback, i+lookback+1) if j != i)
            is_low = all(values[i] <= values[j] for j in range(i-lookback, i+lookback+1) if j != i)
            if is_high:
                sh.append(i)
            if is_low:
                sl.append(i)
        return sh, sl

    def _equity_simulation_numba(dists, tp_dists, is_profit, risk_pct,
                                  min_tp_mult, target_rr, initial_equity):
        n = len(dists)
        equity = initial_equity
        total_trades = 0
        for i in range(n):
            if dists[i] <= 0:
                continue
            min_tp = max(dists[i] * target_rr, dists[i] * min_tp_mult, 5.0)
            if tp_dists[i] < min_tp:
                continue
            risk_usd = equity * (risk_pct / 100.0)
            lot = max(risk_usd / (dists[i] * 100.0), 0.01)
            if is_profit[i]:
                equity += tp_dists[i] * lot * 100.0
            else:
                equity -= risk_usd
            total_trades += 1
        return equity, total_trades

    def _equity_sim_with_drawdown_numba(dists, tp_dists, is_profit, risk_pct,
                                         min_tp_mult, target_rr, initial_equity):
        n = len(dists)
        equity = initial_equity
        peak = equity
        max_dd = 0.0
        for i in range(n):
            if dists[i] <= 0:
                continue
            min_tp = max(dists[i] * target_rr, dists[i] * min_tp_mult, 5.0)
            if tp_dists[i] < min_tp * 0.8:
                continue
            risk_usd = equity * (risk_pct / 100.0)
            lot = max(risk_usd / (dists[i] * 100.0), 0.01)
            if is_profit[i]:
                equity += tp_dists[i] * lot * 100.0
            else:
                equity -= risk_usd
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd
        return equity, max_dd


# ============================================================================
# SHARED FEATURE COMPUTATION (Single Source of Truth)
# ============================================================================

# Feature columns — canonical list used by all models
FEATURE_COLS = [
    'rsi', 'macd', 'atr', 'volatility', 'ret_1', 'ret_5',
    'is_green', 'above_ema20',
    # Momentum
    'williams_r', 'cci', 'ema_distance',
    'ichimoku_signal', 'engulfing_score', 'pin_bar_score',
    'ret_10', 'body_ratio', 'upper_shadow_ratio', 'lower_shadow_ratio',
    # Price action patterns
    'higher_high', 'lower_low', 'double_top', 'double_bottom',
    'atr_ratio',
    # Volume & Order Flow (NEW)
    'volume_delta', 'obv_momentum', 'relative_volume', 'ofi',
    # Volatility Regime (NEW)
    'volatility_percentile', 'atr_expansion',
    # Trend Strength (NEW)
    'adx', 'trend_strength',
]

# Feature cache (keyed by (id(df), len(df)))
_feature_cache = {"key": None, "result": None}


def compute_features(df: pd.DataFrame, use_cache: bool = True) -> pd.DataFrame:
    """Compute all ML features from OHLCV data. Single source of truth.

    Used by: ml_models.py (train/predict), ensemble_models.py (predict).
    Cached by (id(df), len(df)) to avoid recomputation.
    """
    import pandas_ta as ta

    cache_key = (id(df), len(df))
    if use_cache and _feature_cache["key"] == cache_key and _feature_cache["result"] is not None:
        return _feature_cache["result"].copy()

    xp = get_array_module()
    df = df.copy()

    # --- Basic indicators ---
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

    # --- Williams %R ---
    high_14 = df['high'].rolling(14).max()
    low_14 = df['low'].rolling(14).min()
    df['williams_r'] = -100 * (high_14 - df['close']) / (high_14 - low_14 + 1e-10)

    # --- CCI (vectorized MAD approximation) ---
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    sma_tp = typical_price.rolling(20).mean()
    mad_tp = typical_price.rolling(20).std() * 0.7979
    df['cci'] = (typical_price - sma_tp) / (0.015 * mad_tp + 1e-10)

    # --- Ichimoku signal ---
    try:
        tenkan = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
        kijun = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
        span_a = ((tenkan + kijun) / 2).shift(26)
        span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(26)
        cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
        df['ichimoku_signal'] = (df['close'] > cloud_top).astype(int)
    except Exception:
        df['ichimoku_signal'] = 0

    # --- Candlestick patterns (vectorized) ---
    body = abs(df['close'] - df['open'])
    high_low = df['high'] - df['low'] + 1e-10
    df['body_ratio'] = body / high_low
    df['upper_shadow_ratio'] = (df['high'] - df[['close', 'open']].max(axis=1)) / high_low
    df['lower_shadow_ratio'] = (df[['close', 'open']].min(axis=1) - df['low']) / high_low

    # Engulfing
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

    # Pin bar
    lower_s = df[['close', 'open']].min(axis=1) - df['low']
    upper_s = df['high'] - df[['close', 'open']].max(axis=1)
    small_body = (body / high_low) <= 0.3
    bullish_pin = small_body & (lower_s > 2 * upper_s) & (lower_s > body)
    bearish_pin = small_body & (upper_s > 2 * lower_s) & (upper_s > body)
    df['pin_bar_score'] = bullish_pin.astype(int) - bearish_pin.astype(int)

    # --- Price action patterns ---
    lookback = 5
    df['higher_high'] = (df['high'].rolling(lookback).max().shift(1) < df['high']).astype(int)
    df['lower_low'] = (df['low'].rolling(lookback).min().shift(1) > df['low']).astype(int)

    rolling_high = df['high'].rolling(lookback)
    high_mean = rolling_high.mean()
    high_std = rolling_high.std()
    above_thresh = (df['high'] > high_mean + high_std * 0.5).astype(int)
    df['double_top'] = (above_thresh.rolling(lookback).sum().shift(1) >= 2).astype(int)

    rolling_low = df['low'].rolling(lookback)
    low_mean = rolling_low.mean()
    low_std = rolling_low.std()
    below_thresh = (df['low'] < low_mean - low_std * 0.5).astype(int)
    df['double_bottom'] = (below_thresh.rolling(lookback).sum().shift(1) >= 2).astype(int)

    # ATR ratio
    df['atr_ratio'] = df['atr'] / (df['close'] + 1e-10)

    # =====================================================================
    # NEW FEATURES: Volume & Order Flow
    # =====================================================================
    has_volume = 'volume' in df.columns and df['volume'].sum() > 0

    if has_volume:
        # Volume Delta: positive volume on green candles, negative on red
        green = (df['close'] > df['open'])
        df['volume_delta'] = np.where(green, df['volume'], -df['volume'])
        df['volume_delta'] = df['volume_delta'].rolling(14).sum()
        # Normalize to [-1, 1] range
        vd_max = df['volume_delta'].rolling(50).apply(lambda x: max(abs(x.max()), abs(x.min()), 1), raw=True)
        df['volume_delta'] = df['volume_delta'] / (vd_max + 1e-10)

        # OBV Momentum: OBV change over 20 bars (normalized)
        obv = (np.where(green, df['volume'], -df['volume'])).cumsum()
        obv_series = pd.Series(obv, index=df.index)
        df['obv_momentum'] = (obv_series - obv_series.shift(20)) / (obv_series.rolling(50).std() + 1e-10)
        df['obv_momentum'] = df['obv_momentum'].clip(-3, 3)

        # Relative Volume: current vs 20-bar average
        df['relative_volume'] = df['volume'] / (df['volume'].rolling(20).mean() + 1e-10)
        df['relative_volume'] = df['relative_volume'].clip(0, 5)

        # Order Flow Imbalance (OFI): buying pressure proxy
        df['ofi'] = ((df['close'] - df['low']) / (df['high'] - df['low'] + 1e-10)) * 2 - 1
        df['ofi'] = df['ofi'].rolling(14).mean()
    else:
        df['volume_delta'] = 0
        df['obv_momentum'] = 0
        df['relative_volume'] = 1.0
        df['ofi'] = 0

    # =====================================================================
    # NEW FEATURES: Volatility Regime
    # =====================================================================
    # Volatility Percentile: where is current vol vs last 100 bars
    vol_20 = df['close'].pct_change().rolling(20).std()
    df['volatility_percentile'] = vol_20.rolling(100).rank(pct=True)
    df['volatility_percentile'] = df['volatility_percentile'].fillna(0.5)

    # ATR Expansion: current ATR vs recent average (>1 = expanding, <1 = contracting)
    atr_sma = df['atr'].rolling(20).mean()
    df['atr_expansion'] = df['atr'] / (atr_sma + 1e-10)
    df['atr_expansion'] = df['atr_expansion'].clip(0.3, 3.0)

    # =====================================================================
    # NEW FEATURES: Trend Strength
    # =====================================================================
    # ADX (Average Directional Index) — trend strength 0-100
    try:
        _adx = ta.adx(df['high'], df['low'], df['close'], 14)
        df['adx'] = _adx['ADX_14'] if _adx is not None and 'ADX_14' in _adx.columns else 25.0
    except Exception:
        df['adx'] = 25.0
    df['adx'] = df['adx'].fillna(25.0) / 100.0  # normalize to 0-1

    # Trend Strength: EMA alignment (EMA8 > EMA20 > EMA50 = strong bull)
    ema8 = ta.ema(df['close'], 8)
    ema50 = ta.ema(df['close'], 50)
    bull_align = ((ema8 > ema20) & (ema20 > ema50)).astype(float)
    bear_align = ((ema8 < ema20) & (ema20 < ema50)).astype(float)
    df['trend_strength'] = bull_align - bear_align  # +1 strong bull, -1 strong bear, 0 mixed

    df.dropna(inplace=True)

    # Ensure all feature columns exist
    for c in FEATURE_COLS:
        if c not in df.columns:
            df[c] = 0

    # Cache result
    _feature_cache["key"] = cache_key
    _feature_cache["result"] = df

    return df.copy()


def compute_target(features: pd.DataFrame, lookahead: int = 5,
                   atr_threshold: float = 0.5) -> pd.Series:
    """Compute binary target: significant price move (>atr_threshold*ATR in lookahead bars).
    Shared by LSTM and XGBoost training."""
    future_max = features['close'].rolling(lookahead).max().shift(-lookahead)
    future_min = features['close'].rolling(lookahead).min().shift(-lookahead)
    atr_val = features['atr'].replace(0, np.nan).ffill().fillna(1.0)

    up_move = (future_max - features['close']) / atr_val > atr_threshold
    down_move = (features['close'] - future_min) / atr_val > atr_threshold
    return (up_move & ~down_move).astype(int)


def invalidate_feature_cache():
    """Clear the feature cache (e.g., after new data arrives)."""
    _feature_cache["key"] = None
    _feature_cache["result"] = None
