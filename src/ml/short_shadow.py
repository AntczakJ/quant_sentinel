"""
SHORT-direction shadow logger.

Loads the XGB model trained 2026-05-02 against triple_barrier `label_short`
(walk-forward acc 60.3%) and exposes `predict_short_xgb(df)` returning
P(SHORT TP hit) — i.e., higher value = more bearish.

Designed for shadow logging only:
- Predictions are written to ml_predictions.predictions_json under the
  `shadow_short_xgb` key by the ensemble persistence layer.
- They do NOT influence the live trade decision.
- Once we have ≥30 resolved trades with shadow data, we can decide
  whether to wire the SHORT model into per-direction routing.

The shadow path is intentionally segregated from the live ensemble's
xgb voter (`predict_xgb_direction`) to:
1. Keep weights / regime-routing math unchanged.
2. Avoid the muting/MIN_ACTIVE_WEIGHT thresholds that affect live voters.
3. Provide a clean A/B audit trail in JSON.
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
_DEFAULT_PATH = _REPO / "models" / "short_2026-05-02" / "xgb.pkl"

_model = None
_loaded_path: Optional[str] = None
_load_failed_logged = False


def _load_short_xgb(path: Path = _DEFAULT_PATH):
    """Lazy-load the SHORT XGB pickle. Returns None if missing/corrupt."""
    global _model, _loaded_path, _load_failed_logged
    if _model is not None and _loaded_path == str(path):
        return _model
    if not path.exists():
        if not _load_failed_logged:
            logger.info(
                f"[shadow_short] XGB SHORT model missing at {path} — "
                "shadow logging disabled. Re-run train_all.py with "
                "--target-direction=short to populate."
            )
            _load_failed_logged = True
        _model = None
        return None
    try:
        with open(path, "rb") as f:
            _model = pickle.load(f)
        _loaded_path = str(path)
        logger.info(f"[shadow_short] Loaded XGB SHORT model: {path.name}")
        return _model
    except Exception as e:
        logger.warning(f"[shadow_short] Failed to load {path}: {e}")
        _model = None
        return None


def predict_short_xgb(df: pd.DataFrame, usdjpy_df: Optional[pd.DataFrame] = None) -> Optional[float]:
    """Compute P(SHORT TP hit) for the latest bar.

    Returns:
        float in [0, 1] where higher = more bearish, None if model unavailable
        or features can't be computed.

    Read-only: does not write to DB or modify live ensemble state.
    """
    model = _load_short_xgb()
    if model is None:
        return None
    try:
        from src.analysis.compute import compute_features, FEATURE_COLS
        feats = compute_features(df, usdjpy_df=usdjpy_df)
        if feats.empty:
            return None
        # Last row only (current bar)
        x = feats[FEATURE_COLS].iloc[[-1]].values
        # XGBClassifier predict_proba returns [[P(0), P(1)]]; class 1 = SHORT TP hit
        proba = model.predict_proba(x)
        if proba.ndim == 2 and proba.shape[1] >= 2:
            return float(proba[0, 1])
        # Fallback: regressor / binary model with single output
        return float(proba.flatten()[0])
    except Exception as e:
        logger.debug(f"[shadow_short] predict failed: {e}")
        return None
