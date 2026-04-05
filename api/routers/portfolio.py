"""
api/routers/portfolio.py - Portfolio endpoints

Portfel przechowuje:
- balance, pnl, equity - W PLN (waluta użytkownika)
- position_entry - W USD (cena złota)

Konwersje walut TYLKO w portfelu!
"""

import sys
import os
import asyncio
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
    """Pobierz portfolio z bazy danych (persistentne) — single batch query"""
    try:
        db = NewsDB()
        params = db.get_portfolio_params()

        balance = params.get("portfolio_balance")
        if balance is not None:
            balance = float(balance)
            initial = float(params.get("portfolio_initial_balance", balance) or balance)
            equity = float(params.get("portfolio_equity", balance) or balance)
            pnl = float(params.get("portfolio_pnl", 0) or 0)

            # Currency stored as text
            try:
                row = db._query_one(
                    "SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_currency_text'"
                )
                currency = str(row[0]) if row and row[0] else "PLN"
            except Exception:
                currency = "PLN"

            return {
                "balance": balance,
                "initial_balance": initial,
                "equity": equity,
                "pnl": pnl,
                "currency": currency,
                "current_price": float(params.get("current_price", 2050.0) or 2050.0)
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
        db.set_param("portfolio_balance", float(portfolio_data["balance"]))
        db.set_param("portfolio_initial_balance", float(portfolio_data["initial_balance"]))
        db.set_param("portfolio_equity", float(portfolio_data["equity"]))
        db.set_param("portfolio_pnl", float(portfolio_data["pnl"]))
        # Waluta (text) — przechowywana jako string w osobnym param
        db._execute(
            "INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) "
            "ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value",
            ("portfolio_currency_text", portfolio_data.get("currency", "PLN"))
        )
        logger.debug("Portfolio saved to database")
    except Exception as e:
        logger.warning(f"Could not save portfolio to database: {e}")

@router.get(
    "/status",
    response_model=PortfolioStatus,
    summary="Get portfolio status",
    description="Get current portfolio balance in PLN, P&L, and position info"
)
def get_portfolio_status():
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
def get_portfolio_history():
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
def get_portfolio_summary():
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
def update_balance(update: BalanceUpdate):
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
def get_current_price():
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
        db.set_param("current_price", float(current_price))

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
def add_trade(trade: TradeUpdate):
    """Add proposed trade from analysis to database"""
    try:
        db = NewsDB()

        # Używaj _execute() który auto-commituje (działa z SQLite i Turso)
        db._execute(
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

        # Pobierz last insert rowid w sposób kompatybilny z SQLite i Turso
        try:
            db.cursor.execute("SELECT last_insert_rowid()")
            row = db.cursor.fetchone()
            trade_id = row[0] if row else 0
        except Exception:
            trade_id = 0

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


@router.post("/quick-trade", summary="Quick-add trade from SMC analysis (no AI call)")
def quick_add_trade():
    """
    Szybkie dodanie transakcji na podstawie aktualnej analizy SMC.
    NIE wywołuje OpenAI — używa tylko silnika SMC + Finance.
    Natychmiastowy wynik (~1-3s).
    """
    try:
        from src.smc_engine import get_smc_analysis
        from src.finance import calculate_position

        # Odczytaj aktualny balans portfela z bazy
        portfolio = _get_portfolio()
        balance = portfolio.get("balance", 10000.0)
        currency = portfolio.get("currency", "USD")

        # Analiza SMC (bez OpenAI)
        analysis = get_smc_analysis("15m")
        if not analysis:
            return {
                "success": False,
                "direction": "WAIT",
                "message": "Brak danych rynkowych — sprawdź połączenie z Twelve Data API"
            }

        price = float(analysis.get('price', 2000.0))
        trend = analysis.get('trend', 'bull')

        # Oblicz pozycję (bez AI)
        try:
            position = calculate_position(analysis, balance, currency, "")
        except Exception as pos_err:
            logger.warning(f"Position calc fallback: {pos_err}")
            position = {
                "direction": "LONG" if trend.lower() == "bull" else "SHORT",
                "entry": price,
                "sl": round(price - analysis.get('atr', 5.0), 2),
                "tp": round(price + analysis.get('atr', 5.0) * 2.5, 2),
                "lot": 0.01,
                "logic": "SMC Auto"
            }

        direction = position.get("direction", "CZEKAJ")

        if direction in ("CZEKAJ", "WAIT", None):
            return {
                "success": False,
                "direction": "WAIT",
                "message": position.get("reason", "Rynek nie daje wyraźnego sygnału — czekaj na setup.")
            }

        entry = float(position.get("entry") or price)
        sl = float(position.get("sl") or (price - 10))
        tp = float(position.get("tp") or (price + 20))

        db = NewsDB()
        db._execute(
            "INSERT INTO trades (direction, entry, sl, tp, status, timestamp, pattern) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                direction,
                entry,
                sl,
                tp,
                "PROPOSED",
                datetime.now(timezone.utc).isoformat(),
                position.get("logic", "SMC Auto")
            )
        )

        try:
            db.cursor.execute("SELECT last_insert_rowid()")
            row = db.cursor.fetchone()
            trade_id = row[0] if row else 0
        except Exception:
            trade_id = 0

        logger.info(f"✅ Quick-trade #{trade_id}: {direction} @ ${entry:.2f} SL:{sl:.2f} TP:{tp:.2f}")

        return {
            "success": True,
            "trade_id": trade_id,
            "direction": direction,
            "entry": f"${entry:.2f}",
            "sl": f"${sl:.2f}",
            "tp": f"${tp:.2f}",
            "lot": position.get("lot", 0.01),
            "message": f"Trade {direction} dodany @ ${entry:.2f}",
            "trend": trend,
            "rsi": analysis.get("rsi"),
        }

    except Exception as e:
        logger.error(f"❌ quick-trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
