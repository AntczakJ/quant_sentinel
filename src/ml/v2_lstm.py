"""
src/ml/v2_lstm.py — v2 LSTM (per-direction) shadow predictor.

Discovered 2026-05-04 audit: models/v2/xau_long_lstm_v2.keras +
xau_short_lstm_v2.keras were trained 2026-04-25 alongside v2_xgb but
never wired into the ensemble. v2_xgb (regression on R-multiples) IS
in the ensemble; v2 LSTM should be too once we verify it adds signal.

This module exposes:
    predict_v2_lstm(df) -> dict {long_r, short_r, value, available}
where:
    - long_r: predicted R-multiple if we LONG (1ATR SL)
    - short_r: predicted R-multiple if we SHORT (per training convention,
      positive = SHORT wins)
    - value: 0-1 LONG bias (matches ensemble_models v2_xgb convention)

Read-only: returned but not consumed by live decision until validated by
≥30 resolved trades + factor_predictive_power confirms net positive
correlation with WIN/LOSS.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.core.logger import logger

_REPO = Path(__file__).resolve().parents[2]
_BASE = _REPO / "models" / "v2"

_cache = {
    "loaded": False,
    "long_model": None,
    "short_model": None,
    "feature_cols": None,
    "seq_len": None,
    "scaler_mean": None,
    "scaler_std": None,
    "meta_mtime": None,
}


def _load_models() -> bool:
    """Lazy-load v2 LSTM (long + short) + scaler. Returns True if available."""
    long_path = _BASE / "xau_long_lstm_v2.keras"
    short_path = _BASE / "xau_short_lstm_v2.keras"
    meta_path = _BASE / "xau_long_lstm_v2.meta.json"
    scaler_path = _BASE / "xau_long_lstm_v2.scaler.npz"
    for p in (long_path, short_path, meta_path, scaler_path):
        if not p.exists():
            return False
    try:
        meta_mt = meta_path.stat().st_mtime
        if _cache["loaded"] and _cache["meta_mtime"] == meta_mt:
            return True
        # Load
        import keras  # heavy — defer
        meta = json.loads(meta_path.read_text())
        scaler = np.load(scaler_path)
        _cache.update({
            "long_model": keras.models.load_model(str(long_path), compile=False),
            "short_model": keras.models.load_model(str(short_path), compile=False),
            "feature_cols": meta["feature_cols"],
            "seq_len": int(meta["seq_length"]),
            "scaler_mean": scaler["mean"],
            "scaler_std": scaler["std"],
            "meta_mtime": meta_mt,
            "loaded": True,
        })
        logger.info(
            f"v2_lstm loaded (seq_len={_cache['seq_len']}, "
            f"features={len(_cache['feature_cols'])})"
        )
        return True
    except Exception as e:
        logger.debug(f"v2_lstm load failed: {e}")
        return False


def predict_v2_lstm(df: pd.DataFrame) -> Optional[dict]:
    """Compute LONG-R and SHORT-R predictions for the latest bar.

    Returns dict {long_r, short_r, value, available} or None on failure.
    `value` matches v2_xgb convention: 0.5 = neutral, >0.5 = LONG bias,
    <0.5 = SHORT bias, mapped from R-multiple deltas.
    """
    if not _load_models():
        return None
    try:
        from src.analysis.features_v2 import compute_features_v2
        features = compute_features_v2(df.copy())
        if features.empty:
            return None
        seq_len = _cache["seq_len"]
        if len(features) < seq_len:
            return None
        feature_cols = _cache["feature_cols"]
        x = features[feature_cols].iloc[-seq_len:].values
        x = (x - _cache["scaler_mean"]) / _cache["scaler_std"]
        x = x.reshape(1, seq_len, len(feature_cols))
        long_r = float(_cache["long_model"].predict(x, verbose=0)[0, 0])
        short_r = float(_cache["short_model"].predict(x, verbose=0)[0, 0])

        # Match v2_xgb conversion: ensemble convention high=LONG.
        # SHORT model returns POSITIVE R when SHORT wins (training convention).
        if long_r >= 0.3 and long_r > short_r:
            value = 0.5 + min(long_r / 3.0, 0.4)
        elif short_r >= 0.3 and short_r > long_r:
            value = 0.5 - min(short_r / 3.0, 0.4)
        else:
            value = 0.5

        return {
            "long_r": round(long_r, 4),
            "short_r": round(short_r, 4),
            "value": round(value, 4),
            "available": True,
        }
    except Exception as e:
        logger.debug(f"v2_lstm predict error: {e}")
        return None
