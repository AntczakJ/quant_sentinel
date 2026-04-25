"""
shadow_predictor.py — Run v2 ensemble alongside v1, log decisions only.

Phase 6.1 of master plan. Goal: collect 2-4 weeks of v2 predictions
parallel to live v1 trading without ANY effect on production.

How it works:
  - Production scanner (v1) runs as before, opens trades.
  - shadow_predictor() is called from the same scanner background loop
    AFTER v1 has done its work (so cache is warm).
  - shadow_predictor loads v2 models lazily, computes v2 features +
    v2 ensemble prediction, writes record to data/shadow_predictions.jsonl.
  - Each record includes price-at-decision and timestamp so later we
    can backtest v2's hypothetical PnL against actual subsequent prices.

Failure modes are contained:
  - If v2 model files don't exist → log warning once, return silently.
  - If feature compute fails → log + return.
  - All exceptions caught at top level — never bubble to scanner.

Schema of shadow_predictions.jsonl (one JSON per line):
{
  "ts": "2026-04-25T14:30:00Z",
  "tf": "5m",
  "v1_signal": "LONG"|"SHORT"|"WAIT",
  "v1_score": 35.0,
  "v2_long_r_pred": 0.42,    // predicted R for LONG (xgb avg)
  "v2_short_r_pred": -0.12,  // predicted R for SHORT (xgb avg)
  "v2_signal": "LONG"|"SHORT"|"WAIT",  // derived from v2 preds
  "v2_confidence": 0.65,
  "price": 2400.50,
  "atr": 4.2,
  "models_loaded": ["xgb_long", "xgb_short", "lstm_long", "lstm_short"]
}
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("quant_sentinel.shadow_predictor")

MODELS_V2_DIR = Path("models/v2")
SHADOW_LOG = Path("data/shadow_predictions.jsonl")

# Module-level cache to avoid repeated load
_v2_models = {"loaded": False, "xgb_long": None, "xgb_short": None,
              "lstm_long": None, "lstm_short": None,
              "lstm_long_scaler": None, "lstm_short_scaler": None,
              "feature_cols": None}
_load_lock = threading.Lock()
_v1_warned_about_missing = False


def _load_v2_models() -> dict:
    """Load v2 models once, cache. Thread-safe."""
    global _v2_models, _v1_warned_about_missing
    with _load_lock:
        if _v2_models["loaded"]:
            return _v2_models

        meta_path = MODELS_V2_DIR / "xau_long_xgb_v2.meta.json"
        if not meta_path.exists():
            if not _v1_warned_about_missing:
                logger.info(
                    "shadow_predictor: v2 models not yet trained "
                    f"({meta_path} missing) — shadow mode dormant"
                )
                _v1_warned_about_missing = True
            _v2_models["loaded"] = True  # mark as "tried"
            return _v2_models

        try:
            with open(meta_path) as f:
                meta = json.load(f)
            _v2_models["feature_cols"] = meta["feature_cols"]
        except Exception as e:
            logger.warning(f"shadow: failed to read meta: {e}")
            return _v2_models

        # XGB
        try:
            import xgboost as xgb
            for d in ("long", "short"):
                p = MODELS_V2_DIR / f"xau_{d}_xgb_v2.json"
                if p.exists():
                    m = xgb.XGBRegressor()
                    m.load_model(str(p))
                    _v2_models[f"xgb_{d}"] = m
                    logger.info(f"shadow: loaded {p.name}")
        except Exception as e:
            logger.warning(f"shadow: XGB load failed: {e}")

        # LSTM
        try:
            import tensorflow as tf
            for d in ("long", "short"):
                p = MODELS_V2_DIR / f"xau_{d}_lstm_v2.keras"
                sp = MODELS_V2_DIR / f"xau_{d}_lstm_v2.scaler.npz"
                if p.exists() and sp.exists():
                    _v2_models[f"lstm_{d}"] = tf.keras.models.load_model(str(p))
                    sc = np.load(str(sp))
                    _v2_models[f"lstm_{d}_scaler"] = (sc["mean"], sc["std"])
                    logger.info(f"shadow: loaded {p.name}")
        except Exception as e:
            logger.warning(f"shadow: LSTM load failed: {e}")

        _v2_models["loaded"] = True
        return _v2_models


def _derive_v2_signal(long_r: float, short_r: float, threshold: float = 0.3) -> str:
    """Convert R-multiple predictions to discrete signal."""
    if long_r >= threshold and long_r > short_r * -1:
        return "LONG"
    if short_r <= -threshold and short_r * -1 > long_r:
        return "SHORT"
    return "WAIT"


def shadow_predict(
    df: pd.DataFrame,
    tf: str = "5m",
    v1_signal: str = "WAIT",
    v1_score: Optional[float] = None,
) -> dict | None:
    """
    Run v2 ensemble on current bar, log to shadow file. Never raises.

    Args:
        df: current TF dataframe (5m bars typically)
        tf: TF label
        v1_signal: production v1 signal at this same moment (for comparison)
        v1_score: v1 setup quality score (optional)

    Returns:
        dict that was logged, or None if shadow inactive / errored.
    """
    try:
        models = _load_v2_models()
        if models.get("xgb_long") is None and models.get("xgb_short") is None \
           and models.get("lstm_long") is None:
            return None  # no models trained yet

        # Lazy import to avoid TF startup unless shadow is active
        from src.analysis.features_v2 import compute_features_v2
        try:
            features = compute_features_v2(df.copy())
        except Exception as e:
            logger.debug(f"shadow: feature compute failed: {e}")
            return None

        if len(features) == 0:
            return None
        last_row = features.iloc[-1]
        feature_cols = models["feature_cols"]
        # Defensive: align columns
        x = np.array([last_row.get(c, 0.0) for c in feature_cols],
                     dtype=np.float32).reshape(1, -1)

        long_r = None
        short_r = None
        loaded = []
        if models.get("xgb_long") is not None:
            long_r = float(models["xgb_long"].predict(x)[0])
            loaded.append("xgb_long")
        if models.get("xgb_short") is not None:
            short_r = float(models["xgb_short"].predict(x)[0])
            loaded.append("xgb_short")

        # LSTM needs sequence — only run if we have enough history
        seq_length = 32
        if len(features) >= seq_length:
            x_seq = features[feature_cols].iloc[-seq_length:].values.astype(np.float32)
            for d in ("long", "short"):
                m = models.get(f"lstm_{d}")
                if m is None:
                    continue
                mean, std = models[f"lstm_{d}_scaler"]
                x_norm = ((x_seq - mean.squeeze()) / std.squeeze())[np.newaxis, ...]
                pred = float(m.predict(x_norm, verbose=0).flatten()[0])
                if d == "long":
                    long_r = (long_r + pred) / 2 if long_r is not None else pred
                else:
                    short_r = (short_r + pred) / 2 if short_r is not None else pred
                loaded.append(f"lstm_{d}")

        long_r_safe = float(long_r) if long_r is not None else 0.0
        short_r_safe = float(short_r) if short_r is not None else 0.0

        v2_signal = _derive_v2_signal(long_r_safe, short_r_safe)
        v2_confidence = max(abs(long_r_safe), abs(short_r_safe))

        record = {
            "ts": pd.Timestamp.now(tz="UTC").isoformat(),
            "tf": tf,
            "v1_signal": v1_signal,
            "v1_score": v1_score,
            "v2_long_r_pred": long_r_safe,
            "v2_short_r_pred": short_r_safe,
            "v2_signal": v2_signal,
            "v2_confidence": v2_confidence,
            "price": float(df["close"].iloc[-1]) if "close" in df.columns else None,
            "atr": float(features["atr"].iloc[-1]) if "atr" in features.columns else None,
            "models_loaded": loaded,
        }

        # Append to JSONL
        SHADOW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_LOG, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

        return record

    except Exception as e:
        logger.debug(f"shadow_predict outer error: {e}")
        return None
