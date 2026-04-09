"""
api/routers/training.py - Model training endpoints
"""

import sys
import os
import subprocess
import asyncio
import numpy as np
import pandas as pd
from enum import Enum
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.logger import logger
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


# ═══════════════════════════════════════════════════════════════════════════
#  BACKTESTING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

class BacktestModel(str, Enum):
    XGB = "xgb"
    LSTM = "lstm"
    DQN = "dqn"
    ENSEMBLE = "ensemble"
    ALL = "all"


@router.post("/backtest", summary="Run model backtest")
async def run_backtest(
    model: BacktestModel = Query(BacktestModel.ALL, description="Model to backtest"),
    period: str = Query("3mo", description="Data period: 1mo, 3mo, 6mo, 1y"),
    interval: str = Query("15m", description="Candle interval: 15m, 1h, 4h, 1d"),
    include_monte_carlo: bool = Query(False, description="Include Monte Carlo simulation (slower)"),
    spread_pct: float = Query(0.0003, description="Transaction cost per trade (fraction)"),
):
    """
    Run backtest for specified model(s) on historical data.

    Returns classification metrics (accuracy, MCC, F1) and equity metrics
    (Sharpe, Sortino, Calmar, VaR, max drawdown).

    Optionally runs Monte Carlo simulation (5000 shuffles) for risk distribution.
    """
    try:
        from src.analysis.backtest import (
            backtest_xgb, backtest_lstm, backtest_dqn, backtest_ensemble,
            monte_carlo_simulation, apply_transaction_costs
        )

        # Fetch historical data — prefer Twelve Data, fallback to yfinance
        def _fetch_data():
            # Try Twelve Data first (real-time, accurate)
            try:
                from src.data.data_sources import get_provider
                provider = get_provider()
                limit_map = {"1mo": 500, "3mo": 1500, "6mo": 3000, "1y": 5000}
                limit = limit_map.get(period, 1000)
                df = provider.get_candles("XAU/USD", interval, min(limit, 500))
                if df is not None and len(df) >= 50:
                    logger.info(f"Backtest data from Twelve Data: {len(df)} bars")
                    return df
            except Exception as e:
                logger.debug(f"Twelve Data fetch for backtest skipped: {e}")

            # Fallback: yfinance (free, unlimited history, but delayed)
            try:
                import yfinance as yf
                ticker = yf.Ticker("GC=F")
                df = ticker.history(period=period, interval=interval)
                if df.empty and interval != "1d":
                    df = ticker.history(period=period, interval="1h")
                if df.empty:
                    df = ticker.history(period="2y", interval="1d")
                df = df.reset_index()
                col_map = {c: c.lower() for c in df.columns}
                df.rename(columns=col_map, inplace=True)
                df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
                logger.info(f"Backtest data from yfinance: {len(df)} bars")
                return df
            except ImportError:
                raise ImportError("Neither Twelve Data nor yfinance available for backtest data")

            return pd.DataFrame()

        df = await asyncio.to_thread(_fetch_data)

        if df.empty or len(df) < 50:
            raise HTTPException(status_code=400, detail=f"Insufficient data: {len(df)} bars")

        results = {"data_bars": len(df), "period": period, "interval": interval}

        # Run requested backtests
        model_fns = {
            "xgb": ("XGBoost", backtest_xgb),
            "lstm": ("LSTM", backtest_lstm),
            "dqn": ("DQN", backtest_dqn),
            "ensemble": ("Ensemble", backtest_ensemble),
        }

        models_to_run = list(model_fns.keys()) if model.value == "all" else [model.value]

        for m in models_to_run:
            name, fn = model_fns[m]
            try:
                bt_result = await asyncio.to_thread(fn, df)
                results[m] = bt_result
            except Exception as e:
                results[m] = {"error": str(e)}

        # Monte Carlo
        if include_monte_carlo:
            # Use ensemble returns if available, else xgb
            for m in ("ensemble", "xgb", "lstm"):
                if m in results and "total_return" in results[m] and "n_trades" in results[m]:
                    try:
                        # Re-generate returns for MC by running a lightweight pass
                        bt = results[m]
                        n = bt.get("n_trades", 0)
                        if n > 10:
                            # Synthesize approximate returns from metrics
                            wr = bt.get("win_rate", 0.5)
                            total_ret = bt.get("total_return", 0)
                            avg_ret = total_ret / max(n, 1)
                            synth_returns = np.random.choice(
                                [abs(avg_ret) * 1.5, -abs(avg_ret) * 0.8],
                                size=n,
                                p=[wr, 1 - wr]
                            )
                            results["monte_carlo"] = monte_carlo_simulation(
                                synth_returns, n_simulations=5000, spread_pct=spread_pct
                            )
                    except Exception as e:
                        results["monte_carlo"] = {"error": str(e)}
                    break

        return results

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Data source unavailable: {e}")
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

