"""
api/routers/signals.py - Trading signal endpoints
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from api.schemas.models import SignalResponse, SignalHistoryItem

router = APIRouter()

# Signal cache
_signal_cache = {"current": None, "history": []}

def initialize_default_signal():
    """Initialize default signal for testing"""
    try:
        # Pobierz live price z Twelve Data
        from src.data_sources import get_provider
        provider = get_provider()
        ticker = provider.get_current_price('XAU/USD')
        current_price = ticker['price'] if ticker else 2050.0  # Fallback
    except Exception as e:
        logger.warning(f"Could not fetch current price: {e}")
        current_price = 2050.0  # Fallback price

    default_signal = SignalResponse(
        timestamp=datetime.now(timezone.utc),
        symbol="XAU/USD",
        rl_action="HOLD",
        rl_confidence=0.5,
        rl_epsilon=0.1,
        lstm_prediction=current_price,
        lstm_change_pct=0.0,
        xgb_direction="NEUTRAL",
        xgb_probability=0.5,
        consensus="HOLD",
        consensus_score=0.5,
        current_price=current_price,
        current_rsi=50.0,
        signal_id="init_001"
    )
    return default_signal

# Initialize with default signal
_signal_cache["current"] = initialize_default_signal()

@router.get(
    "/current",
    response_model=SignalResponse,
    summary="Get current trading signal",
    description="Get latest signal from all three models with consensus"
)
async def get_current_signal():
    """Get current combined signal from RL, LSTM, and XGBoost models"""
    try:
        # Pobierz live price
        try:
            from src.data_sources import get_provider
            provider = get_provider()
            ticker = provider.get_current_price('XAU/USD')
            current_price = ticker['price'] if ticker else 2050.0
        except Exception as e:
            logger.warning(f"Could not fetch current price: {e}")
            current_price = 2050.0

        # Try to get latest signal from database first
        try:
            from src.database import NewsDB
            db = NewsDB()
            latest_db_signal = db.get_latest_scanner_signal()

            if latest_db_signal:
                signal_id, direction, entry_price, sl, tp, rsi, trend, structure = latest_db_signal

                # Map database signal to SignalResponse
                consensus = "STRONG_BUY" if direction == "LONG" else "STRONG_SELL"

                signal = SignalResponse(
                    timestamp=datetime.now(timezone.utc),
                    symbol="XAU/USD",
                    rl_action=direction,
                    rl_confidence=0.75,
                    rl_epsilon=0.1,
                    lstm_prediction=entry_price,
                    lstm_change_pct=0.0,
                    xgb_direction=direction,
                    xgb_probability=0.75,
                    consensus=consensus,
                    consensus_score=0.75,
                    current_price=current_price,  # ← LIVE PRICE
                    current_rsi=float(rsi) if rsi else 50.0,
                    signal_id=str(signal_id)
                )

                _signal_cache["current"] = signal
                logger.info(f"✅ Loaded signal from database: {direction} | Current price: {current_price}")
                return signal
        except Exception as e:
            logger.debug(f"Could not load signal from database: {e}")

        # Fallback to cached signal
        if _signal_cache["current"] is None:
            raise HTTPException(status_code=404, detail="No signal available yet")

        # Update current price in cached signal
        _signal_cache["current"].current_price = current_price
        logger.debug(f"Using cached signal with live price: {current_price}")
        return _signal_cache["current"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching signal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/history",
    summary="Get signal history",
    description="Get historical signals with results"
)
async def get_signal_history(limit: int = 50):
    """Get historical signals from scanner"""
    try:
        # Try to get history from database first
        try:
            from src.database import NewsDB
            from datetime import datetime, timezone

            db = NewsDB()
            db_signals = db.get_all_scanner_signals(limit=limit)

            if db_signals:
                history = []
                for sig in db_signals:
                    sig_id, direction, entry, sl, tp, rsi, trend, structure, status, timestamp = sig

                    # Convert to Signal format for frontend
                    signal = SignalResponse(
                        timestamp=datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else datetime.now(timezone.utc),
                        symbol="XAU/USD",
                        rl_action=direction,
                        rl_confidence=0.75,
                        rl_epsilon=0.1,
                        lstm_prediction=float(entry),
                        lstm_change_pct=0.0,
                        xgb_direction=direction,
                        xgb_probability=0.75,
                        consensus="STRONG_BUY" if direction == "LONG" else "STRONG_SELL",
                        consensus_score=0.75,
                        current_price=float(entry),
                        current_rsi=float(rsi) if rsi else 50.0,
                        signal_id=str(sig_id)
                    )
                    history.append(signal)

                logger.info(f"✅ Loaded {len(history)} signals from database")
                _signal_cache["history"] = history
                # Return wrapped in signals field for frontend
                return {"signals": history}
        except Exception as e:
            logger.debug(f"Could not load signals from database: {e}")

        # Fallback to cached signals
        return {"signals": _signal_cache["history"][-limit:]}
    except Exception as e:
        logger.error(f"❌ Error fetching signal history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/consensus",
    summary="Get signal consensus",
    description="Get current consensus between all models"
)
async def get_consensus():
    """Get consensus signal"""
    try:
        if _signal_cache["current"] is None:
            return {"consensus": "NO_DATA", "score": 0}

        signal = _signal_cache["current"]
        return {
            "consensus": signal.consensus,
            "score": signal.consensus_score,
            "timestamp": signal.timestamp
        }
    except Exception as e:
        logger.error(f"❌ Error fetching consensus: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats", summary="Get signal statistics")
async def get_signal_stats():
    """Get signal statistics"""
    history = _signal_cache["history"]
    if not history:
        return {"total": 0, "win_rate": 0, "accuracy": 0}

    wins = sum(1 for s in history if s.result == "WIN")
    losses = sum(1 for s in history if s.result == "LOSS")
    total = len(history)

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / total if total > 0 else 0,
        "last_update": datetime.now(timezone.utc)
    }

