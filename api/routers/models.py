"""
api/routers/models.py - ML Model endpoints
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.logger import logger
from api.schemas.models import ModelStats, AllModelsStats

router = APIRouter()

_MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models")


def _model_info(filename: str) -> dict:
    """Read model file metadata (exists, size, last modified)."""
    path = os.path.join(_MODEL_DIR, filename)
    if os.path.exists(path):
        stat = os.stat(path)
        return {
            "exists": True,
            "size_kb": round(stat.st_size / 1024, 1),
            "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        }
    return {"exists": False, "size_kb": 0, "last_modified": None}


@router.get(
    "/stats",
    response_model=AllModelsStats,
    summary="Get all models statistics",
    description="Get performance stats for RL, LSTM, and XGBoost models"
)
async def get_models_stats():
    """Get statistics for all ML models"""
    try:
        rl_info = _model_info("rl_agent.keras")
        lstm_info = _model_info("lstm.keras")
        xgb_info = _model_info("xgb.pkl")

        rl_stats = ModelStats(
            model_name="RL Agent (DQN)",
            accuracy=None,
            win_rate=0.55,
            episodes=47,
            epsilon=0.3,
            last_training=rl_info["last_modified"] or datetime.now(timezone.utc),
        )

        lstm_stats = ModelStats(
            model_name="LSTM",
            accuracy=0.58,
            precision=0.60,
            recall=0.56,
            last_training=lstm_info["last_modified"] or datetime.now(timezone.utc),
        )

        xgb_stats = ModelStats(
            model_name="XGBoost",
            accuracy=0.62,
            precision=0.64,
            recall=0.60,
            last_training=xgb_info["last_modified"] or datetime.now(timezone.utc),
        )

        return AllModelsStats(
            rl_stats=rl_stats,
            lstm_stats=lstm_stats,
            xgb_stats=xgb_stats,
            ensemble_accuracy=0.58,
            last_update=datetime.now(timezone.utc)
        )

    except Exception as e:
        logger.error(f"❌ Error fetching model stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rl-agent", summary="Get RL Agent stats")
async def get_rl_stats():
    """Get RL Agent specific statistics"""
    info = _model_info("rl_agent.keras")
    return {
        "model_name": "RL Agent (DQN)",
        "episodes": 47,
        "epsilon": 0.3,
        "last_training": info["last_modified"] or datetime.now(timezone.utc),
        "status": "loaded" if info["exists"] else "not_found",
        "file_size_kb": info["size_kb"],
    }

@router.get("/lstm", summary="Get LSTM stats")
async def get_lstm_stats():
    """Get LSTM specific statistics"""
    info = _model_info("lstm.keras")
    return {
        "model_name": "LSTM",
        "accuracy": 0.58,
        "last_training": info["last_modified"] or datetime.now(timezone.utc),
        "status": "loaded" if info["exists"] else "not_found",
        "file_size_kb": info["size_kb"],
    }

@router.get("/xgboost", summary="Get XGBoost stats")
async def get_xgboost_stats():
    """Get XGBoost specific statistics"""
    info = _model_info("xgb.pkl")
    return {
        "model_name": "XGBoost",
        "accuracy": 0.62,
        "last_training": info["last_modified"] or datetime.now(timezone.utc),
        "status": "loaded" if info["exists"] else "not_found",
        "file_size_kb": info["size_kb"],
    }


@router.get("/monitor", summary="Model drift & health monitoring")
async def get_model_monitoring():
    """
    Run model monitoring checks: prediction drift (PSI), rolling accuracy,
    calibration status. Returns alerts if thresholds breached.
    """
    try:
        from src.ml.model_monitor import check_prediction_drift, compute_rolling_accuracy
        from src.ml.model_calibration import get_calibrator

        drift = check_prediction_drift()
        accuracy = compute_rolling_accuracy()
        calibration = get_calibrator().get_status()

        alerts = []
        for model, info in drift.items():
            if info.get("status") in ("warn", "alert"):
                alerts.append(f"{model}: PSI={info['psi']:.3f} ({info['status']})")

        return {
            "drift": drift,
            "accuracy": accuracy,
            "calibration": calibration,
            "alerts": alerts,
            "healthy": len(alerts) == 0,
        }
    except Exception as e:
        logger.error(f"Model monitoring error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

