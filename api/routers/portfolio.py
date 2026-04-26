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

from src.core.logger import logger
from src.core.database import NewsDB
from api.schemas.models import PortfolioStatus, PortfolioHistory

router = APIRouter()

# Portfolio update request model
class BalanceUpdate(BaseModel):
    balance: float
    currency: str = "PLN"


def _get_portfolio():
    """Pobierz portfolio z bazy danych (persistentne) — single batch query.

    PnL is derived from SUM(trades.profit) for consistency with digest +
    system-health. balance-vs-initial drifts when user resets /cap or
    tests pollute state. Canonical source: realized trade P&L.
    """
    try:
        db = NewsDB()
        params = db.get_portfolio_params()

        balance = params.get("portfolio_balance")
        if balance is not None:
            balance = float(balance)
            initial = float(params.get("portfolio_initial_balance", balance) or balance)
            equity = float(params.get("portfolio_equity", balance) or balance)
            currency = str(params.get("portfolio_currency_text", "PLN") or "PLN")

            # Canonical PnL: SUM of realized trade profit. Keeps all three
            # surfaces (portfolio-status / system-health / digest) in sync.
            pnl_row = db._query_one(
                "SELECT COALESCE(SUM(profit), 0) FROM trades "
                "WHERE status IN ('WIN','LOSS','PROFIT','CLOSED') AND profit IS NOT NULL"
            )
            canonical_pnl = float(pnl_row[0] or 0) if pnl_row else 0.0

            return {
                "balance": balance,
                "initial_balance": initial,
                "equity": equity if equity > 0 else balance,
                "pnl": round(canonical_pnl, 2),
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
    description=(
        "Equity timeline. Returns the cached `dynamic_params.portfolio_history` "
        "JSON when present; otherwise reconstructs the timeline from the `trades` "
        "table (cumulative P&L over `initial_balance`)."
    ),
)
def get_portfolio_history():
    """Get portfolio equity history (in PLN)."""
    try:
        db = NewsDB()
        history = db.get_param("portfolio_history", None)

        hist_data = {"timestamps": [], "equity_values": [], "pnl_values": []}
        if history:
            import json
            try:
                if isinstance(history, str):
                    hist_data = json.loads(history)
                else:
                    logger.debug(f"portfolio_history is not JSON string: {type(history)}")
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: reconstruct from resolved trades when cache is empty.
        # Cheap query (~1 ms even at 10k rows) and produces a usable curve
        # for the BalanceDetail expandable on the frontend.
        if not hist_data.get("timestamps"):
            rows = db._query(
                "SELECT timestamp, profit FROM trades "
                "WHERE status IN ('WIN','LOSS','PROFIT','LOSE','CLOSED') "
                "AND profit IS NOT NULL "
                "ORDER BY timestamp ASC, id ASC"
            )
            if rows:
                portfolio = _get_portfolio()
                initial = float(portfolio.get("initial_balance") or 0.0)
                ts: list[str] = []
                eq: list[float] = []
                pnl_series: list[float] = []
                cum = 0.0
                for r in rows:
                    try:
                        p = float(r[1] or 0.0)
                    except (TypeError, ValueError):
                        continue
                    cum += p
                    ts.append(str(r[0]))
                    pnl_series.append(round(cum, 2))
                    eq.append(round(initial + cum, 2))
                hist_data = {
                    "timestamps": ts,
                    "equity_values": eq,
                    "pnl_values": pnl_series,
                }

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
        from src.data.data_sources import get_provider
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

class CloseTradeRequest(BaseModel):
    trade_id: int
    close_price: float = None


@router.get("/open-positions", summary="Get all open positions with unrealized P&L")
def get_open_positions():
    """Get all open trades with live unrealized P&L calculated from current price."""
    try:
        db = NewsDB()

        # Fetch current price
        try:
            from src.data.data_sources import get_provider
            provider = get_provider()
            ticker = provider.get_current_price('XAU/USD')
            current_price = ticker['price'] if ticker else None
        except Exception:
            current_price = None

        if current_price is None:
            # Fallback to cached price in DB
            cached = db.get_param("current_price", None)
            current_price = float(cached) if cached else 2050.0

        rows = db._query(
            "SELECT id, direction, entry, sl, tp, lot, timestamp FROM trades WHERE status = 'OPEN'"
        )

        positions = []
        total_unrealized = 0.0

        for row in rows:
            trade_id, direction, entry, sl, tp, lot_size, opened_at = row
            lot_size = float(lot_size or 0.01)
            entry = float(entry or 0)

            if direction == "LONG":
                unrealized_pnl = (current_price - entry) * lot_size * 100
            else:
                unrealized_pnl = (entry - current_price) * lot_size * 100

            unrealized_pnl = round(unrealized_pnl, 2)
            total_unrealized += unrealized_pnl

            positions.append({
                "id": trade_id,
                "direction": direction,
                "entry": entry,
                "sl": float(sl or 0),
                "tp": float(tp or 0),
                "unrealized_pnl": unrealized_pnl,
                "opened_at": opened_at,
                "lot_size": lot_size,
            })

        return {
            "positions": positions,
            "total_unrealized_pnl": round(total_unrealized, 2),
            "current_price": current_price,
        }

    except Exception as e:
        logger.error(f"Error fetching open positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/close-trade", summary="Close an open trade")
def close_trade(req: CloseTradeRequest):
    """Close an open trade, calculate realized P&L, and update portfolio balance."""
    try:
        db = NewsDB()

        # Validate trade exists and is OPEN — use explicit columns to avoid index issues
        row = db._query_one(
            "SELECT id, direction, entry, lot, status FROM trades WHERE id = ?",
            (req.trade_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Trade #{req.trade_id} not found")

        trade_id_db, direction, entry, lot_raw, status = row

        if status != 'OPEN':
            raise HTTPException(
                status_code=400,
                detail=f"Trade #{req.trade_id} is not OPEN (current status: {status})"
            )

        entry = float(entry)
        lot_size = float(lot_raw or 0.01)

        # Determine close price
        close_price = req.close_price
        if close_price is None:
            try:
                from src.data.data_sources import get_provider
                provider = get_provider()
                ticker = provider.get_current_price('XAU/USD')
                close_price = ticker['price'] if ticker else None
            except Exception:
                close_price = None

            if close_price is None:
                cached = db.get_param("current_price", None)
                close_price = float(cached) if cached else None

            if close_price is None:
                raise HTTPException(
                    status_code=400,
                    detail="Could not determine close price. Provide close_price in request body."
                )

        close_price = float(close_price)

        # Calculate P&L
        if direction == "LONG":
            pnl = (close_price - entry) * lot_size * 100
        else:
            pnl = (entry - close_price) * lot_size * 100

        pnl = round(pnl, 2)

        # Update trade status and profit
        db._execute(
            "UPDATE trades SET status = 'CLOSED', profit = ? WHERE id = ?",
            (pnl, req.trade_id)
        )

        # Audit log
        try:
            db.log_trade_audit(req.trade_id, 'OPEN', 'CLOSED', reason=f"Manual close @ {close_price:.2f}")
        except Exception:
            pass

        # Update portfolio balance
        portfolio = _get_portfolio()
        portfolio["balance"] = round(portfolio["balance"] + pnl, 2)
        portfolio["pnl"] = round(portfolio["balance"] - portfolio["initial_balance"], 2)
        portfolio["equity"] = portfolio["balance"]
        _save_portfolio(portfolio)

        # Append to equity-curve history (same shape as auto-resolver writes)
        try:
            import json as _json
            raw = db.get_param("portfolio_history", None)
            hist = []
            if raw:
                try:
                    hist = _json.loads(raw) if isinstance(raw, str) else []
                except Exception:
                    hist = []
            if not isinstance(hist, list):
                hist = []
            hist.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "balance": portfolio["balance"],
                "pnl": portfolio["pnl"],
                "trade_id": req.trade_id,
                "delta": pnl,
            })
            if len(hist) > 500:
                hist = hist[-500:]
            db.set_param("portfolio_history", _json.dumps(hist))
        except Exception as _hist_err:
            logger.debug(f"portfolio_history append skipped: {_hist_err}")

        logger.info(f"Trade #{req.trade_id} closed @ ${close_price:.2f} | P&L: {pnl:+.2f}")

        return {
            "success": True,
            "trade_id": req.trade_id,
            "pnl": pnl,
            "close_price": close_price,
            "new_balance": portfolio["balance"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing trade #{req.trade_id}: {e}")
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
        from src.trading.scanner import cascade_mtf_scan

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


# ══════════════════════════════════════════════════════════════════════
#  TRADE JOURNALING ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

class JournalEntryRequest(BaseModel):
    trade_id: int
    rationale: str = None
    emotion: str = None
    lesson: str = None
    notes: str = None


@router.post("/journal", summary="Save or update a trade journal entry")
def save_journal_entry(entry: JournalEntryRequest):
    """
    Upsert a journal entry for a trade.
    If an entry already exists for the given trade_id, it will be updated.
    """
    try:
        db = NewsDB()

        # Validate trade exists
        trade = db._query_one("SELECT id FROM trades WHERE id = ?", (entry.trade_id,))
        if not trade:
            # Also check archive
            try:
                trade = db._query_one("SELECT id FROM trades_archive WHERE id = ?", (entry.trade_id,))
            except Exception:
                pass
            if not trade:
                raise HTTPException(status_code=404, detail=f"Trade #{entry.trade_id} not found")

        journal_id = db.save_journal_entry(
            trade_id=entry.trade_id,
            rationale=entry.rationale,
            emotion=entry.emotion,
            lesson=entry.lesson,
            notes=entry.notes,
        )

        logger.info(f"Journal entry saved for trade #{entry.trade_id}")

        return {
            "success": True,
            "journal_id": journal_id,
            "trade_id": entry.trade_id,
            "message": f"Journal entry saved for trade #{entry.trade_id}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving journal entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/{trade_id}", summary="Get journal entry for a trade")
def get_journal_entry(trade_id: int):
    """Get the journal entry associated with a specific trade."""
    try:
        db = NewsDB()
        entry = db.get_journal_entry(trade_id)

        if not entry:
            raise HTTPException(status_code=404, detail=f"No journal entry for trade #{trade_id}")

        return entry
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching journal entry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal", summary="Get recent journal entries")
def get_journal_entries(limit: int = 20):
    """Get recent trade journal entries with associated trade info."""
    try:
        db = NewsDB()
        entries = db.get_journal_entries(limit=min(limit, 100))

        return {
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        logger.error(f"Error fetching journal entries: {e}")
        raise HTTPException(status_code=500, detail=str(e))
