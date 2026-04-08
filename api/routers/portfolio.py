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
            currency = str(params.get("portfolio_currency_text", "PLN") or "PLN")

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
        # Waluta (text) — set_param automatycznie kieruje do param_text
        db.set_param("portfolio_currency_text", portfolio_data.get("currency", "PLN"))
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

        hist_data = {"timestamps": [], "equity_values": [], "pnl_values": []}
        if history:
            import json
            try:
                # history may be a string (JSON) or a numeric value from REAL column
                if isinstance(history, str):
                    hist_data = json.loads(history)
                else:
                    logger.debug(f"portfolio_history is not JSON string: {type(history)}")
            except (json.JSONDecodeError, TypeError):
                pass

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
        # ── Price sanity check ──────────────────────────────────────────
        try:
            from api.routers.market import _persistent_cache as _mkt_pc
            ref = float(_mkt_pc.get("ticker", {}).get("price", 0))
            if ref > 1000 and trade.entry > 0:
                deviation = abs(trade.entry - ref) / ref
                if deviation > 0.25:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cena entry (${trade.entry:.0f}) odbiega o {deviation:.0%} od aktualnej (${ref:.0f}). Odrzucono."
                    )
        except HTTPException:
            raise
        except Exception:
            pass

        db = NewsDB()
        ts = datetime.now(timezone.utc).isoformat()
        session = db.get_session(ts)

        trade_id = db._insert_returning_id(
            """
            INSERT INTO trades (direction, entry, sl, tp, status, timestamp, pattern, lot, session)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.direction,
                trade.entry,
                trade.sl,
                trade.tp,
                "PROPOSED",
                ts,
                trade.logic,
                trade.lot_size,
                session,
            )
        )

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
    Szybkie dodanie transakcji z kaskady multi-timeframe (4h → 1h → 15m → 5m).
    NIE wywołuje OpenAI — używa silnika SMC + Finance.
    Stawia trade na pierwszym TF z ważnym setupem.

    Cascade: jeśli nie widzi nic na 4h, szuka na 1h, 15m, 5m.
    Jeśli na jakimkolwiek TF znajdzie setup, stawia trade.
    """
    try:
        from src.scanner import cascade_mtf_scan

        # Odczytaj aktualny balans portfela z bazy
        portfolio = _get_portfolio()
        balance = portfolio.get("balance", 10000.0)
        currency = portfolio.get("currency", "USD")

        db = NewsDB()
        trade = cascade_mtf_scan(db, balance=balance, currency=currency)

        if not trade:
            return {
                "success": False,
                "direction": "WAIT",
                "message": "Brak ważnego setupu tradingowego na żadnym timeframe (4h→1h→15m→5m) — czekaj na setup."
            }

        direction = trade['direction']
        entry = float(trade['entry'])
        sl = float(trade['sl'])
        tp = float(trade['tp'])
        lot = float(trade.get('lot', 0.01))
        logic = trade.get('logic', 'SMC Auto')
        tf_label = trade.get('tf_label', '?')
        trend = trade.get('trend', 'bull')
        rsi = trade.get('rsi', 50.0)

        # ── Price sanity check (dodatkowy — cascade_mtf_scan ma swój, ale tu chronimy zapis) ──
        try:
            from api.routers.market import _persistent_cache as _mkt_pc
            ref = float(_mkt_pc.get("ticker", {}).get("price", 0))
            if ref > 1000 and entry > 0:
                deviation = abs(entry - ref) / ref
                if deviation > 0.20:
                    logger.warning(
                        f"⚠️ Quick-trade: price sanity FAIL: entry=${entry:.2f} vs "
                        f"ticker=${ref:.2f} (Δ{deviation:.0%})"
                    )
                    return {
                        "success": False,
                        "direction": "WAIT",
                        "message": f"Dane rynkowe niespójne (entry: ${entry:.0f} vs ticker: ${ref:.0f}) — spróbuj ponownie"
                    }
        except Exception:
            pass

        # ── Deduplication — nie twórz tego samego trade'a dwa razy ─────────────
        # Shared key format with _background_scanner and scan_market_task
        import hashlib as _hl
        tf = trade.get('tf', '')
        trade_key = _hl.md5(f"mtf_{direction}_{entry:.1f}_{tf}".encode()).hexdigest()
        if db.is_news_processed(trade_key):
            logger.info(f"⚡ Quick-trade: dedup — {direction}@{entry:.0f} na {tf_label} już istnieje")
            return {
                "success": False,
                "direction": "WAIT",
                "message": f"Trade {direction} @ ${entry:.0f} na {tf_label} już istnieje w bazie — dedup aktywny."
            }

        # Save to trades (PROPOSED — auto-resolver monitoruje)
        ts = datetime.now(timezone.utc).isoformat()
        session = db.get_session(ts)
        import json as _json
        factors = trade.get('factors')
        factors_json = _json.dumps(factors) if factors else None

        trade_id = db._insert_returning_id(
            "INSERT INTO trades (direction, entry, sl, tp, status, timestamp, pattern, lot, rsi, trend, session, factors) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                direction,
                entry,
                sl,
                tp,
                "PROPOSED",
                ts,
                f"[{tf_label}] {logic}",
                lot,
                rsi,
                trend,
                session,
                factors_json,
            )
        )

        # Save to scanner_signals (pojawi się w SignalHistory)
        rsi_val = trade.get('rsi', 50.0)
        structure = trade.get('structure', 'Stable')
        db.save_scanner_signal(
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            rsi=rsi_val,
            trend=trend,
            structure=f"[{tf_label}] {structure}"
        )

        # Mark as processed to prevent duplicates from bg scanner
        db.mark_news_as_processed(trade_key)

        logger.info(f"✅ Quick-trade #{trade_id}: {direction} on {tf_label} @ ${entry:.2f} SL:{sl:.2f} TP:{tp:.2f}")

        return {
            "success": True,
            "trade_id": trade_id,
            "direction": direction,
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "lot": lot,
            "message": f"Trade {direction} na {tf_label} @ ${entry:.2f}",
            "trend": trend,
            "rsi": rsi_val,
            "timeframe": tf_label,
        }

    except Exception as e:
        logger.error(f"❌ quick-trade error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
