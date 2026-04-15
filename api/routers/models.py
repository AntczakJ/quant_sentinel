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
    Persists warn/alert drift results to model_alerts table.
    """
    try:
        from src.ml.model_monitor import check_prediction_drift, compute_rolling_accuracy
        from src.ml.model_calibration import get_calibrator
        from src.core.database import NewsDB

        drift = check_prediction_drift()
        accuracy = compute_rolling_accuracy()
        calibration = get_calibrator().get_status()

        alerts = []
        db = NewsDB()
        for model, info in drift.items():
            if info.get("status") in ("warn", "alert"):
                msg = f"{model}: PSI={info['psi']:.3f} ({info['status']})"
                alerts.append(msg)
                db.save_model_alert(
                    model_name=model,
                    alert_type="drift",
                    severity=info["status"],
                    message=msg,
                    psi_value=info.get("psi"),
                )

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


@router.get("/alerts", summary="Get model drift alerts")
async def get_model_alerts(limit: int = 20, unresolved_only: bool = False):
    """
    Fetch persisted model alerts (drift, accuracy, calibration).
    Query params: limit (default 20), unresolved_only (default false).
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        alerts = db.get_model_alerts(limit=limit, unresolved_only=unresolved_only)
        unresolved_count = db.get_unresolved_alert_count()
        return {"alerts": alerts, "unresolved_count": unresolved_count}
    except Exception as e:
        logger.error(f"Error fetching model alerts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


LSTM_SWAP_TS = "2026-04-13T01:36:00"  # sweep winner deployed


def _hist_stats(vals: list[float], bins: int = 20) -> dict:
    """Compute histogram + bimodality metrics for a list of [0,1] predictions."""
    hist = [0] * bins
    for v in vals:
        idx = min(int(v * bins), bins - 1)
        hist[idx] += 1
    n = len(vals)
    if n == 0:
        return {
            "histogram": hist, "bins": bins, "n": 0,
            "mean": None, "std": None, "conviction": None,
            "extreme_frac": None, "middle_frac": None,
        }
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    conviction = sum(abs(v - 0.5) for v in vals) / n
    extreme = sum(1 for v in vals if v < 0.1 or v > 0.9)
    middle = sum(1 for v in vals if 0.35 <= v <= 0.65)
    return {
        "histogram": hist, "bins": bins, "n": n,
        "mean": round(mean, 4), "std": round(var ** 0.5, 4),
        "conviction": round(conviction, 4),
        "extreme_frac": round(extreme / n, 4),
        "middle_frac": round(middle / n, 4),
    }


@router.get("/lstm-distribution", summary="LSTM prediction distribution (bimodality monitor)")
async def get_lstm_distribution(hours: int = 48):
    """
    Histogram of lstm_pred over last `hours` vs a pre-swap reference window.
    Detects degenerate overconfident models (2026-04-13 sweep-winner concern).
    Extreme fraction >0.7 with middle fraction <0.15 = bimodal/degenerate.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        post_rows = db._query(
            "SELECT lstm_pred FROM ml_predictions "
            "WHERE timestamp >= ? AND lstm_pred IS NOT NULL",
            (LSTM_SWAP_TS,),
        )
        post_vals = [float(r[0]) for r in post_rows if r[0] is not None]
        pre_rows = db._query(
            "SELECT lstm_pred FROM ml_predictions "
            "WHERE timestamp >= ? AND timestamp < ? AND lstm_pred IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 5000",
            ("2026-04-06T00:00:00", LSTM_SWAP_TS),
        )
        pre_vals = [float(r[0]) for r in pre_rows if r[0] is not None]

        post = _hist_stats(post_vals)
        pre = _hist_stats(pre_vals)

        verdict = "healthy"
        if post["n"] >= 20:
            if post["extreme_frac"] and post["extreme_frac"] > 0.7 and (post["middle_frac"] or 0) < 0.15:
                verdict = "degenerate"
            elif post["conviction"] and pre["conviction"] and post["conviction"] > 3 * pre["conviction"]:
                verdict = "concerning"

        return {
            "post_swap": post,
            "pre_swap_reference": pre,
            "swap_timestamp": LSTM_SWAP_TS,
            "verdict": verdict,
            "hours_requested": hours,
        }
    except Exception as e:
        logger.error(f"lstm-distribution error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerts/{alert_id}/resolve", summary="Resolve a model alert")
async def resolve_model_alert(alert_id: int):
    """Mark a model alert as resolved."""
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        updated = db.resolve_alert(alert_id)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found or already resolved")
        return {"status": "resolved", "alert_id": alert_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

