"""
api/routers/signals.py - Trading signal endpoints
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.logger import logger
from api.schemas.models import SignalResponse, SignalHistoryItem

router = APIRouter()

# Direction mapping — DB stores LONG/SHORT, Pydantic expects BUY/SELL/HOLD and UP/DOWN/NEUTRAL
_RL_ACTION_MAP = {"LONG": "BUY", "SHORT": "SELL"}
_XGB_DIR_MAP = {"LONG": "UP", "SHORT": "DOWN"}

# Signal cache
_signal_cache = {"current": None, "history": []}

def initialize_default_signal():
    """Initialize default signal for testing — no API call at startup"""
    # Use market persistent cache price if available
    current_price = 4720.0  # Fallback price (nie wywołuj API przy starcie)
    try:
        from api.routers.market import _persistent_cache as _mkt_pc
        ref = float(_mkt_pc.get("ticker", {}).get("price", 0))
        if ref > 1000:
            current_price = ref
    except Exception:
        pass

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
def get_current_signal():
    """Get current combined signal from RL, LSTM, and XGBoost models"""
    try:
        # Use cached price from market router instead of calling external API again
        # (market/ticker caches last price; avoids duplicate provider call + 8s timeout)
        current_price = 3100.0
        try:
            from api.routers.market import _data_cache as _market_data_cache, _ticker_cache as _market_ticker_cache
            cached_price = _market_data_cache.get("last_price")
            if cached_price and float(cached_price) > 0:
                current_price = float(cached_price)
            else:
                # Try ticker cache
                ticker_cached = _market_ticker_cache.get("XAU/USD")
                if ticker_cached and ticker_cached.get("data"):
                    p = ticker_cached["data"].get("price")
                    if p and float(p) > 0:
                        current_price = float(p)
        except Exception as e:
            logger.debug(f"Could not read cached price from market router: {e}")

        # Try to get latest signal from database first
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            latest_db_signal = db.get_latest_scanner_signal()

            if latest_db_signal:
                # Safe unpack — handle varying column counts
                # Query: id, direction, entry, sl, tp, rsi, trend, structure, status, timestamp
                cols = len(latest_db_signal)
                signal_id = latest_db_signal[0] if cols > 0 else None
                direction = latest_db_signal[1] if cols > 1 else None
                entry_price = latest_db_signal[2] if cols > 2 else None
                sl = latest_db_signal[3] if cols > 3 else None
                tp = latest_db_signal[4] if cols > 4 else None
                rsi = latest_db_signal[5] if cols > 5 else None
                trend = latest_db_signal[6] if cols > 6 else None
                structure = latest_db_signal[7] if cols > 7 else None
                status = latest_db_signal[8] if cols > 8 else "PENDING"
                timestamp = latest_db_signal[9] if cols > 9 else None

                if signal_id and direction and entry_price:
                    # Map database signal to SignalResponse
                    consensus = "STRONG_BUY" if direction == "LONG" else "STRONG_SELL"

                    try:
                        entry_f = float(entry_price)
                    except (ValueError, TypeError):
                        entry_f = current_price

                    try:
                        parsed_ts = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else datetime.now(timezone.utc)
                    except Exception:
                        parsed_ts = datetime.now(timezone.utc)

                    signal = SignalResponse(
                        timestamp=parsed_ts,
                        symbol="XAU/USD",
                        rl_action=_RL_ACTION_MAP.get(direction, "HOLD"),
                        rl_confidence=0.75,
                        rl_epsilon=0.1,
                        lstm_prediction=entry_f,
                        lstm_change_pct=round((entry_f - current_price) / current_price * 100, 2) if current_price > 0 else 0.0,
                        xgb_direction=_XGB_DIR_MAP.get(direction, "NEUTRAL"),
                        xgb_probability=0.75,
                        consensus=consensus,
                        consensus_score=0.75,
                        current_price=current_price,  # live price, not entry
                        current_rsi=float(rsi) if rsi else 50.0,
                        signal_id=str(signal_id)
                    )

                    _signal_cache["current"] = signal
                    logger.debug(f"✅ Loaded signal from DB: {direction} @ {current_price}")
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
def get_signal_history(limit: int = 50):
    """Get historical signals from scanner and trades"""
    try:
        from src.core.database import NewsDB
        from datetime import datetime, timezone

        db = NewsDB()
        try:
            db_signals = db.get_all_scanner_signals(limit=limit)
        except Exception as e:
            logger.warning(f"get_all_scanner_signals failed in history: {e}")
            db_signals = []

        if db_signals:
            history = []
            for sig in db_signals:
                if not sig or not isinstance(sig, (list, tuple)):
                    continue
                # Safe unpack — rows may have 8-10 columns depending on DB migrations
                try:
                    cols = len(sig)
                    sig_id = sig[0] if cols > 0 else None
                    direction = sig[1] if cols > 1 else None
                    entry = sig[2] if cols > 2 else None
                    sl = sig[3] if cols > 3 else None
                    tp = sig[4] if cols > 4 else None
                    rsi = sig[5] if cols > 5 else None
                    trend = sig[6] if cols > 6 else None
                    structure = sig[7] if cols > 7 else None
                    status = sig[8] if cols > 8 else "PENDING"
                    timestamp = sig[9] if cols > 9 else None
                except (ValueError, TypeError, IndexError):
                    continue

                if sig_id is None or direction is None or entry is None:
                    continue

                try:
                    entry_f = float(entry)
                except (ValueError, TypeError):
                    continue

                consensus = "STRONG_BUY" if direction == "LONG" else "STRONG_SELL"
                try:
                    parsed_ts = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else datetime.now(timezone.utc)
                except Exception:
                    parsed_ts = datetime.now(timezone.utc)

                # Use live price from market cache for current_price
                live_price = entry_f  # fallback
                try:
                    from api.routers.market import _data_cache as _mdc, _ticker_cache as _mtc
                    lp = _mdc.get("last_price")
                    if lp and float(lp) > 0:
                        live_price = float(lp)
                    else:
                        tc = _mtc.get("XAU/USD")
                        if tc and tc.get("data") and float(tc["data"].get("price", 0)) > 0:
                            live_price = float(tc["data"]["price"])
                except Exception:
                    pass

                signal = SignalResponse(
                    timestamp=parsed_ts,
                    symbol="XAU/USD",
                    rl_action=_RL_ACTION_MAP.get(direction, "HOLD"),
                    rl_confidence=0.75,
                    rl_epsilon=0.1,
                    lstm_prediction=entry_f,
                    lstm_change_pct=round((entry_f - live_price) / live_price * 100, 2) if live_price > 0 else 0.0,
                    xgb_direction=_XGB_DIR_MAP.get(direction, "NEUTRAL"),
                    xgb_probability=0.75,
                    consensus=consensus,
                    consensus_score=0.75,
                    current_price=live_price,  # live market price, not entry
                    current_rsi=float(rsi) if rsi else 50.0,
                    signal_id=str(sig_id)
                )
                history.append(signal)

            logger.info(f"✅ Loaded {len(history)} signals from scanner_signals")
            _signal_cache["history"] = history
            return {"signals": history}

        # Fallback: load from trades table when scanner_signals is empty
        try:
            trades = db._query("""
                SELECT id, direction, entry, rsi, timestamp, status
                FROM trades
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
            if trades:
                history = []
                for t in trades:
                    t_id, direction, entry, rsi, ts, status = t
                    if not direction or not entry:
                        continue
                    consensus = "STRONG_BUY" if direction == "LONG" else "STRONG_SELL"
                    try:
                        parsed_ts = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.now(timezone.utc)
                    except Exception:
                        parsed_ts = datetime.now(timezone.utc)
                    signal = SignalResponse(
                        timestamp=parsed_ts,
                        symbol="XAU/USD",
                        rl_action=_RL_ACTION_MAP.get(direction, "HOLD"),
                        rl_confidence=0.6,
                        rl_epsilon=0.1,
                        lstm_prediction=float(entry),
                        lstm_change_pct=0.0,
                        xgb_direction=_XGB_DIR_MAP.get(direction, "NEUTRAL"),
                        xgb_probability=0.6,
                        consensus=consensus,
                        consensus_score=0.6,
                        current_price=float(entry),
                        current_rsi=float(rsi) if rsi else 50.0,
                        signal_id=f"trade_{t_id}"
                    )
                    history.append(signal)
                if history:
                    logger.info(f"✅ Loaded {len(history)} signals from trades table (fallback)")
                    return {"signals": history}
        except Exception as e:
            logger.debug(f"Trade fallback for signals failed: {e}")

        return {"signals": _signal_cache["history"][-limit:]}
    except Exception as e:
        logger.error(f"❌ Error fetching signal history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/consensus",
    summary="Get signal consensus",
    description="Get current consensus between all models"
)
def get_consensus():
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
def get_signal_stats():
    """Get signal statistics from trades table"""
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        # Count both WIN and PROFIT as wins (scanner uses PROFIT, API resolver uses WIN)
        row = db._query_one(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status IN ('WIN','PROFIT') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) "
            "FROM trades WHERE status IN ('WIN','PROFIT','LOSS')"
        )
        total = int(row[0] or 0) if row else 0
        wins = int(row[1] or 0) if row else 0
        losses = int(row[2] or 0) if row else 0
        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total if total > 0 else 0,
            "last_update": datetime.now(timezone.utc),
        }
    except Exception as e:
        logger.warning(f"Signal stats fallback: {e}")
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "last_update": datetime.now(timezone.utc)}


@router.get("/scanner", summary="Get rich SMC scanner signal history")
def get_scanner_signals(limit: int = 30):
    """
    Return scanner signals with full SMC data: direction, entry, SL, TP, RSI, trend, structure, status.
    These are richer than the generic /history endpoint.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        try:
            db_signals = db.get_all_scanner_signals(limit=limit)
        except Exception as e:
            logger.warning(f"get_all_scanner_signals failed: {e}")
            db_signals = []

        result = []
        for sig in (db_signals or []):
            if not sig or not isinstance(sig, (list, tuple)):
                continue
            # Safe unpack — rows may have 8-10 columns depending on DB migrations
            try:
                cols = len(sig)
                sig_id = sig[0] if cols > 0 else None
                direction = sig[1] if cols > 1 else None
                entry = sig[2] if cols > 2 else None
                sl = sig[3] if cols > 3 else None
                tp = sig[4] if cols > 4 else None
                rsi = sig[5] if cols > 5 else None
                trend = sig[6] if cols > 6 else None
                structure = sig[7] if cols > 7 else None
                status = sig[8] if cols > 8 else "PENDING"
                timestamp = sig[9] if cols > 9 else None
            except (ValueError, TypeError, IndexError):
                continue

            if sig_id is None or direction is None:
                continue

            try:
                parsed_ts = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else datetime.now(timezone.utc)
            except Exception:
                parsed_ts = datetime.now(timezone.utc)

            def _safe_float(v):
                try:
                    return float(v) if v is not None else None
                except (ValueError, TypeError):
                    return None

            result.append(
                SignalHistoryItem(
                    signal_id=str(sig_id),
                    timestamp=parsed_ts,
                    direction=direction,
                    entry_price=_safe_float(entry),
                    sl=_safe_float(sl),
                    tp=_safe_float(tp),
                    rsi=_safe_float(rsi),
                    structure=structure,
                    result=status if status in ("WIN", "LOSS", "BREAKEVEN") else None,
                )
            )

        return {"signals": result, "count": len(result)}
    except Exception as e:
        logger.error(f"❌ Error fetching scanner signals: {e}")
        return {"signals": [], "count": 0}
