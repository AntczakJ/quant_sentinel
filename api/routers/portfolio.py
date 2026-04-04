"""
api/routers/portfolio.py - Portfolio endpoints

Portfel przechowuje:
- balance, pnl, equity - W PLN (waluta użytkownika)
- position_entry - W USD (cena złota)

Konwersje walut TYLKO w portfelu!
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from src.database import NewsDB
from api.schemas.models import PortfolioStatus, PortfolioHistory

router = APIRouter()

# Portfolio update request model
class BalanceUpdate(BaseModel):
    balance: float
    currency: str = "PLN"


def _get_portfolio():
    """Pobierz portfolio z bazy danych (persistentne)"""
    try:
        db = NewsDB()

        # Próbuj pobrać istniejące portfolio
        balance = db.get_param("portfolio_balance", None)
        if balance is not None:
            return {
                "balance": float(balance),
                "initial_balance": float(db.get_param("portfolio_initial_balance", balance)),
                "equity": float(db.get_param("portfolio_equity", balance)),
                "pnl": float(db.get_param("portfolio_pnl", 0)),
                "currency": db.get_param("portfolio_currency", "PLN"),
                "current_price": float(db.get_param("current_price", 2050.0))
            }
    except Exception as e:
        logger.debug(f"Could not load portfolio from database: {e}")

    # Fallback - domyślne portfolio
    return {
        "balance": 10000,
        "initial_balance": 10000,
        "equity": 10000,
        "pnl": 0,
        "currency": "PLN",
        "current_price": 2050.0
    }


def _save_portfolio(portfolio_data):
    """Zapisz portfolio do bazy danych (persistentne)"""
    try:
        db = NewsDB()
        db.set_param("portfolio_balance", str(portfolio_data["balance"]))
        db.set_param("portfolio_initial_balance", str(portfolio_data["initial_balance"]))
        db.set_param("portfolio_equity", str(portfolio_data["equity"]))
        db.set_param("portfolio_pnl", str(portfolio_data["pnl"]))
        db.set_param("portfolio_currency", portfolio_data.get("currency", "PLN"))
        logger.debug("Portfolio saved to database")
    except Exception as e:
        logger.warning(f"Could not save portfolio to database: {e}")

@router.get(
    "/status",
    response_model=PortfolioStatus,
    summary="Get portfolio status",
    description="Get current portfolio balance in PLN, P&L, and position info"
)
async def get_portfolio_status():
    """Get current portfolio status (in PLN)"""
    try:
        portfolio = _get_portfolio()

        return PortfolioStatus(
            balance=portfolio["balance"],
            initial_balance=portfolio["initial_balance"],
            equity=portfolio["equity"],
            pnl=portfolio["pnl"],
            pnl_pct=(portfolio["pnl"] / portfolio["initial_balance"] * 100) if portfolio["initial_balance"] > 0 else 0,
            currency=portfolio.get("currency", "PLN"),
            has_position=False,
            position_type=None,
            position_entry=None,
            position_unrealized_pnl=None,
            timestamp=datetime.now(timezone.utc)
        )
    except Exception as e:
        logger.error(f"❌ Error fetching portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/history",
    response_model=PortfolioHistory,
    summary="Get portfolio history",
    description="Get historical portfolio values in PLN"
)
async def get_portfolio_history():
    """Get portfolio equity history (in PLN)"""
    try:
        db = NewsDB()
        history = db.get_param("portfolio_history", None)

        if history:
            import json
            hist_data = json.loads(history)
        else:
            hist_data = {"timestamps": [], "equity_values": [], "pnl_values": []}

        return PortfolioHistory(
            timestamps=hist_data.get("timestamps", []),
            equity_values=hist_data.get("equity_values", []),
            pnl_values=hist_data.get("pnl_values", [])
        )
    except Exception as e:
        logger.error(f"❌ Error fetching portfolio history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/summary", summary="Get portfolio summary")
async def get_portfolio_summary():
    """Get quick portfolio summary (in PLN)"""
    portfolio = _get_portfolio()

    return {
        "balance": portfolio["balance"],
        "currency": portfolio.get("currency", "PLN"),
        "pnl": portfolio["pnl"],
        "pnl_pct": (portfolio["pnl"] / portfolio["initial_balance"] * 100) if portfolio["initial_balance"] > 0 else 0,
        "timestamp": datetime.now(timezone.utc)
    }

@router.post("/update-balance", summary="Update portfolio balance")
async def update_balance(update: BalanceUpdate):
    """Update portfolio starting balance (in PLN)"""
    try:
        if update.balance <= 0:
            raise HTTPException(status_code=400, detail="Balance must be greater than 0")

        portfolio = {
            "balance": update.balance,
            "initial_balance": update.balance,
            "equity": update.balance,
            "pnl": 0,
            "currency": update.currency
        }

        _save_portfolio(portfolio)

        logger.info(f"✅ Portfolio balance updated to {update.balance:.2f} {update.currency}")

        return {
            "success": True,
            "message": f"Balance updated to {update.balance:.2f} {update.currency}",
            "balance": update.balance,
            "currency": update.currency
        }
    except Exception as e:
        logger.error(f"❌ Error updating balance: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/current-price", summary="Get current gold price")
async def get_current_price():
    """Get current XAU/USD price from Twelve Data"""
    try:
        from src.data_sources import get_provider
        provider = get_provider()
        ticker = provider.get_current_price('XAU/USD')

        if not ticker:
            raise HTTPException(status_code=404, detail="Could not fetch price")

        current_price = ticker['price']

        # Zapisz cenę do bazy
        db = NewsDB()
        db.set_param("current_price", str(current_price))

        logger.info(f"💰 Current price: ${current_price:.2f}")

        return {
            "price": current_price,
            "symbol": "XAU/USD",
            "timestamp": datetime.now(timezone.utc)
        }
    except Exception as e:
        logger.error(f"❌ Error fetching current price: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class TradeUpdate(BaseModel):
    direction: str  # LONG/SHORT
    entry: float
    sl: float
    tp: float
    lot_size: float
    logic: str = ""

@router.post("/add-trade", summary="Add proposed trade to database")
async def add_trade(trade: TradeUpdate):
    """Add proposed trade from analysis to database"""
    try:
        db = NewsDB()

        # Zapisz trade do bazy
        db.cursor.execute(
            """
            INSERT INTO trades (direction, entry, sl, tp, status, timestamp, pattern)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.direction,
                trade.entry,
                trade.sl,
                trade.tp,
                "PROPOSED",
                datetime.now(timezone.utc).isoformat(),
                trade.logic
            )
        )
        db.conn.commit()

        trade_id = db.cursor.lastrowid
        logger.info(f"✅ Trade #{trade_id} added: {trade.direction} @ ${trade.entry:.2f}")

        return {
            "success": True,
            "trade_id": trade_id,
            "message": f"Trade added: {trade.direction} @ ${trade.entry:.2f}",
            "direction": trade.direction,
            "entry": f"${trade.entry:.2f}",
            "sl": f"${trade.sl:.2f}",
            "tp": f"${trade.tp:.2f}"
        }
    except Exception as e:
        logger.error(f"❌ Error adding trade: {e}")
        raise HTTPException(status_code=500, detail=str(e))

