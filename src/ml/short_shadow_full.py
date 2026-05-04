"""
SHORT-direction shadow ensemble — extends short_shadow.py to LSTM and
Attention models that already exist in models/short_2026-05-02/ but
weren't being consumed.

Discovered 2026-05-04 audit: when training pipeline was re-run with
--target-direction=short on 2026-05-02, it produced 3 SHORT-trained
artifacts (xgb, lstm, attention). Only XGB was wired into short_shadow.
LSTM and Attention SHORT-trained models sat unused.

This module exposes:
    predict_short_lstm(df, usdjpy_df) -> P(SHORT TP hit)
    predict_short_attention(df, usdjpy_df) -> P(SHORT TP hit)
    predict_short_ensemble(df, usdjpy_df) -> dict {xgb, lstm, attention, mean}

Like XGB shadow, these are READ-ONLY — written to ml_predictions JSON for
post-hoc analysis, never used to modify a live decision until validated.

Once ≥30 resolved trades have all three SHORT shadow signals, the
factor_predictive_power analyzer can compare:
- LONG-trained voter on SHORT setup vs SHORT-trained voter on SHORT setup
- agreement vs disagreement of the SHORT trio
- mean accuracy delta vs the LONG-only ensemble we use today
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.core.logger import logger

_REPO = Path(__file__).resolve().parents[2]
_BASE = _REPO / "models" / "short_2026-05-02"

_short_lstm = None
_short_lstm_scaler = None
_short_attn = None
_short_attn_scaler = None
_load_attempted = False
_load_failed_logged = False


def _try_load_short_lstm():
    """Lazy-load SHORT LSTM keras + scaler."""
    global _short_lstm, _short_lstm_scaler
    if _short_lstm is not None:
        return True
    keras_path = _BASE / "lstm.keras"
    scaler_path = _BASE / "lstm_scaler.pkl"
    if not keras_path.exists() or not scaler_path.exists():
        return False
    try:
        # Defer keras import (heavy) until first call.
        import keras  # type: ignore
        _short_lstm = keras.models.load_model(str(keras_path), compile=False)
        with open(scaler_path, "rb") as f:
            _short_lstm_scaler = pickle.load(f)
        logger.info(f"[shadow_short_full] Loaded LSTM SHORT: {keras_path.name}")
        return True
    except Exception as e:
        logger.debug(f"[shadow_short_full] LSTM SHORT load failed: {e}")
        return False


def _try_load_short_attention():
    """Lazy-load SHORT Attention keras + scaler."""
    global _short_attn, _short_attn_scaler
    if _short_attn is not None:
        return True
    keras_path = _BASE / "attention.keras"
    scaler_path = _BASE / "attention_scaler.pkl"
    if not keras_path.exists() or not scaler_path.exists():
        return False
    try:
        import keras  # type: ignore
        _short_attn = keras.models.load_model(str(keras_path), compile=False)
        with open(scaler_path, "rb") as f:
            _short_attn_scaler = pickle.load(f)
        logger.info(f"[shadow_short_full] Loaded Attention SHORT: {keras_path.name}")
        return True
    except Exception as e:
        logger.debug(f"[shadow_short_full] Attention SHORT load failed: {e}")
        return False


def _build_features(df: pd.DataFrame, usdjpy_df: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """Compute features for the current bar; returns None on any failure."""
    try:
        from src.analysis.compute import compute_features, FEATURE_COLS
        feats = compute_features(df, usdjpy_df=usdjpy_df)
        if feats.empty:
            return None
        return feats
    except Exception as e:
        logger.debug(f"[shadow_short_full] feature compute failed: {e}")
        return None


def predict_short_lstm(
    df: pd.DataFrame, usdjpy_df: Optional[pd.DataFrame] = None
) -> Optional[float]:
    """P(SHORT TP hit) from the SHORT-trained LSTM. None if unavailable."""
    if not _try_load_short_lstm():
        return None
    feats = _build_features(df, usdjpy_df=usdjpy_df)
    if feats is None:
        return None
    try:
        from src.analysis.compute import FEATURE_COLS
        # LSTM expects sequence input — match training shape.
        # If the scaler is per-bar (StandardScaler), scale last window.
        # We use the last 50 bars as the standard sequence length.
        seq_len = 60  # SHORT models trained 2026-05-02 with seq_len=60
        if len(feats) < seq_len:
            return None
        x = feats[FEATURE_COLS].iloc[-seq_len:].values
        x = _short_lstm_scaler.transform(x)
        x = x.reshape(1, seq_len, len(FEATURE_COLS))
        proba = _short_lstm.predict(x, verbose=0)
        # Most binary keras heads output single-sigmoid in [0, 1].
        val = float(proba.flatten()[0])
        return max(0.0, min(1.0, val))
    except Exception as e:
        logger.debug(f"[shadow_short_full] LSTM predict failed: {e}")
        return None


def predict_short_attention(
    df: pd.DataFrame, usdjpy_df: Optional[pd.DataFrame] = None
) -> Optional[float]:
    """P(SHORT TP hit) from the SHORT-trained Attention model."""
    if not _try_load_short_attention():
        return None
    feats = _build_features(df, usdjpy_df=usdjpy_df)
    if feats is None:
        return None
    try:
        from src.analysis.compute import FEATURE_COLS
        seq_len = 60  # SHORT models trained 2026-05-02 with seq_len=60
        if len(feats) < seq_len:
            return None
        x = feats[FEATURE_COLS].iloc[-seq_len:].values
        x = _short_attn_scaler.transform(x)
        x = x.reshape(1, seq_len, len(FEATURE_COLS))
        proba = _short_attn.predict(x, verbose=0)
        val = float(proba.flatten()[0])
        return max(0.0, min(1.0, val))
    except Exception as e:
        logger.debug(f"[shadow_short_full] Attention predict failed: {e}")
        return None


def predict_short_ensemble(
    df: pd.DataFrame, usdjpy_df: Optional[pd.DataFrame] = None
) -> dict:
    """All 3 SHORT shadow predictions + mean.

    Returns dict with keys: xgb, lstm, attention, mean, n_available.
    Each model entry is float in [0,1] or None. mean is over available
    only; None if all unavailable.
    """
    from src.ml.short_shadow import predict_short_xgb
    p_xgb = predict_short_xgb(df, usdjpy_df)
    p_lstm = predict_short_lstm(df, usdjpy_df)
    p_attn = predict_short_attention(df, usdjpy_df)
    available = [p for p in (p_xgb, p_lstm, p_attn) if p is not None]
    return {
        "xgb": p_xgb,
        "lstm": p_lstm,
        "attention": p_attn,
        "mean": (sum(available) / len(available)) if available else None,
        "n_available": len(available),
    }
