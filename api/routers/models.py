"""
api/routers/models.py - ML Model endpoints
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from api.schemas.models import ModelStats, AllModelsStats

router = APIRouter()

@router.get(
    "/stats",
    response_model=AllModelsStats,
    summary="Get all models statistics",
    description="Get performance stats for RL, LSTM, and XGBoost models"
)
async def get_models_stats():
    """Get statistics for all ML models"""
    try:
        rl_stats = ModelStats(
            model_name="RL Agent (DQN)",
            accuracy=None,
            win_rate=0.55,
            episodes=47,
            epsilon=0.3,
            last_training=datetime.now(timezone.utc)
        )

        lstm_stats = ModelStats(
            model_name="LSTM",
            accuracy=0.58,
            precision=0.60,
            recall=0.56,
            last_training=datetime.now(timezone.utc)
        )

        xgb_stats = ModelStats(
            model_name="XGBoost",
            accuracy=0.62,
            precision=0.64,
            recall=0.60,
            last_training=datetime.now(timezone.utc)
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
    return {
        "model_name": "RL Agent (DQN)",
        "episodes": 47,
        "epsilon": 0.3,
        "last_training": datetime.now(timezone.utc),
        "status": "idle"
    }

@router.get("/lstm", summary="Get LSTM stats")
async def get_lstm_stats():
    """Get LSTM specific statistics"""
    return {
        "model_name": "LSTM",
        "accuracy": 0.58,
        "last_training": datetime.now(timezone.utc),
        "status": "idle"
    }

@router.get("/xgboost", summary="Get XGBoost stats")
async def get_xgboost_stats():
    """Get XGBoost specific statistics"""
    return {
        "model_name": "XGBoost",
        "accuracy": 0.62,
        "last_training": datetime.now(timezone.utc),
        "status": "idle"
    }

