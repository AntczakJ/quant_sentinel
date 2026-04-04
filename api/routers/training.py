"""
api/routers/training.py - Model training endpoints
"""

import sys
import os
import subprocess
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from api.schemas.models import TrainingStartRequest, TrainingStatus

router = APIRouter()

# Training state
_training_state = {
    "is_training": False,
    "current_episode": 0,
    "total_episodes": 0,
    "process": None,
    "started_at": None,
    "last_reward": None,
    "avg_reward": None
}

async def run_training(episodes: int, save_model: bool):
    """Background task to run training"""
    try:
        _training_state["is_training"] = True
        _training_state["started_at"] = datetime.now(timezone.utc)
        _training_state["total_episodes"] = episodes

        logger.info(f"🚀 Starting training: {episodes} episodes")

        # Run training script
        cmd = [
            "python",
            "train_rl.py",
            f"--episodes={episodes}",
            f"--save_model={'true' if save_model else 'false'}"
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        _training_state["process"] = process

        # Wait for completion
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            logger.info("✅ Training completed successfully")
        else:
            logger.error(f"❌ Training failed: {stderr}")

    except Exception as e:
        logger.error(f"❌ Error during training: {e}")
    finally:
        _training_state["is_training"] = False

@router.post(
    "/start",
    response_model=TrainingStatus,
    summary="Start model training",
    description="Start training the RL Agent"
)
async def start_training(request: TrainingStartRequest, background_tasks: BackgroundTasks):
    """Start RL Agent training in background"""
    try:
        if _training_state["is_training"]:
            raise HTTPException(status_code=409, detail="Training already in progress")

        # Add training task to background
        background_tasks.add_task(run_training, request.episodes, request.save_model)

        logger.info(f"📋 Training job queued: {request.episodes} episodes")

        return TrainingStatus(
            is_training=True,
            current_episode=0,
            total_episodes=request.episodes,
            progress_pct=0,
            started_at=datetime.now(timezone.utc)
        )

    except Exception as e:
        logger.error(f"❌ Error starting training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/status",
    response_model=TrainingStatus,
    summary="Get training status",
    description="Get current training progress"
)
async def get_training_status():
    """Get current training status"""
    try:
        state = _training_state

        progress_pct = 0
        if state["total_episodes"] > 0:
            progress_pct = (state["current_episode"] / state["total_episodes"]) * 100

        eta_seconds = None
        if state["started_at"] and state["current_episode"] > 0:
            elapsed = (datetime.now(timezone.utc) - state["started_at"]).total_seconds()
            per_episode = elapsed / state["current_episode"]
            remaining = state["total_episodes"] - state["current_episode"]
            eta_seconds = int(per_episode * remaining)

        return TrainingStatus(
            is_training=state["is_training"],
            current_episode=state["current_episode"],
            total_episodes=state["total_episodes"],
            progress_pct=progress_pct,
            last_reward=state["last_reward"],
            avg_reward=state["avg_reward"],
            started_at=state["started_at"],
            eta_seconds=eta_seconds
        )

    except Exception as e:
        logger.error(f"❌ Error fetching training status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stop", summary="Stop training")
async def stop_training():
    """Stop training if in progress"""
    try:
        if _training_state["is_training"] and _training_state["process"]:
            _training_state["process"].terminate()
            _training_state["is_training"] = False
            logger.info("🛑 Training stopped")
            return {"status": "stopped"}

        return {"status": "not training"}

    except Exception as e:
        logger.error(f"❌ Error stopping training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

