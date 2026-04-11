"""
api/routers/risk.py — Risk Management API endpoints

Provides:
  - GET  /risk/status  — Current risk manager state
  - POST /risk/halt    — Emergency halt (kill switch)
  - POST /risk/resume  — Resume trading after halt
"""

import sys
import os
from fastapi import APIRouter, HTTPException, Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.logger import logger

router = APIRouter()


@router.get("/status", summary="Risk Manager Status")
def get_risk_status():
    """
    Returns current risk management state:
    halted, daily loss, consecutive losses, cooldown, Kelly risk, session, spread.
    """
    try:
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        return rm.get_status()
    except Exception as e:
        logger.error(f"Risk status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/halt", summary="Halt Trading (Kill Switch)")
def halt_trading(request: Request, reason: str = "Manual halt via API"):
    """
    Emergency trading halt. Blocks all new trades until manually resumed.
    Active positions are NOT closed — only new trade creation is blocked.
    Requires authentication (JWT Bearer token or X-API-Key).
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm.halt(reason)
        logger.info(f"Trading halted by user={user.get('username', 'unknown')}: {reason}")
        return {"success": True, "message": f"Trading halted: {reason}", "halted": True}
    except Exception as e:
        logger.error(f"Halt error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume", summary="Resume Trading")
def resume_trading(request: Request):
    """
    Resume trading after a halt. Clears halt state and cooldown timers.
    Requires authentication (JWT Bearer token or X-API-Key).
    """
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm.resume()
        logger.info(f"Trading resumed by user={user.get('username', 'unknown')}")
        return {"success": True, "message": "Trading resumed", "halted": False}
    except Exception as e:
        logger.error(f"Resume error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
