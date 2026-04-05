"""
api/routers/analysis.py - Trading analysis endpoints
Provides analysis functions from the bot
"""

import sys
import os
import asyncio
import time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from src.smc_engine import get_smc_analysis
from src.openai_agent import ask_agent_with_memory
from src.finance import calculate_position
from src.data_sources import get_provider
from src.config import USER_PREFS
from src.database import NewsDB

router = APIRouter()

# ---------------------------------------------------------------------------
# Prosty cache TTL dla endpointu quant-pro (unikamy wielokrotnych wywołań OpenAI)
# ---------------------------------------------------------------------------
_quant_pro_cache: dict = {}   # key: tf → {"data": ..., "ts": float}
_QUANT_PRO_TTL = 300          # 5 minut cache

_AI_TIMEOUT = 15  # Max seconds to wait for OpenAI response


@router.get(
    "/quant-pro",
    summary="Run QUANT PRO Analysis",
    description="Comprehensive SMC + AI + ML Ensemble analysis for XAU/USD"
)
async def quant_pro_analysis(
    tf: str = Query("15m", description="Timeframe: 5m, 15m, 1h, 4h"),
    force: bool = Query(False, description="Force refresh — skip cache")
):
    """
    QUANT PRO Analysis - Full comprehensive analysis with ML Ensemble.
    Returns: SMC analysis + AI evaluation + ML predictions + ensemble signal + trade parameters.
    Results are cached for 5 minutes to avoid repeated OpenAI calls.

    The AI assessment has a 15-second timeout — if OpenAI is slow the rest of
    the data (SMC + ML + position) is still returned immediately.
    """
    # Check cache (unless force refresh requested)
    if not force:
        cached = _quant_pro_cache.get(tf)
        if cached and (time.time() - cached["ts"]) < _QUANT_PRO_TTL:
            logger.debug(f"✅ Returning cached quant-pro for {tf}")
            return cached["data"]

    try:
        # --- Phase 1: SMC + Market data (fast, <5s) --------------------------
        analysis = await asyncio.to_thread(get_smc_analysis, tf)
        if not analysis:
            raise HTTPException(status_code=404, detail="Could not analyze market")

        provider = get_provider()
        try:
            ticker = await asyncio.to_thread(provider.get_current_price, 'XAU/USD')
            current_price = ticker['price'] if ticker else None
        except Exception as e:
            logger.warning(f"Could not fetch price: {e}")
            current_price = None

        if current_price is None:
            current_price = analysis.get('price', 2050.0)
            logger.warning(f"⚠️ Using SMC analysis price as fallback: {current_price}")

        try:
            candles = await asyncio.to_thread(provider.get_candles, 'XAU/USD', tf, 200)
        except Exception as e:
            logger.warning(f"Could not fetch candles for ML: {e}")
            candles = None

        # --- Phase 2: Position calculation with ML Ensemble (fast, cached) ----
        trend = analysis.get('trend', 'unknown')
        fvg = analysis.get('fvg', 'None')
        structure = analysis.get('structure', 'Stable')
        rsi = analysis.get('rsi', 50)
        ob_price = analysis.get('ob_price', current_price)
        direction = "LONG" if trend == "bull" else "SHORT"

        try:
            _db = NewsDB()
            actual_balance = float(_db.get_param("portfolio_balance", None) or 10000)
            try:
                _db.cursor.execute(
                    "SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_currency_text'"
                )
                _row = _db.cursor.fetchone()
                actual_currency = str(_row[0]) if _row and _row[0] else "USD"
            except Exception:
                actual_currency = "USD"
        except Exception:
            actual_balance = 10000
            actual_currency = "USD"

        try:
            position = await asyncio.to_thread(
                calculate_position,
                analysis, actual_balance, actual_currency,
                USER_PREFS.get('td_api_key', ''),
                candles,
            )
        except Exception as pos_err:
            logger.warning(f"Position calculation failed: {pos_err}")
            position = {
                "lot": 0.1,
                "entry": ob_price,
                "sl": ob_price - 5 if trend == "bull" else ob_price + 5,
                "tp": ob_price + 15 if trend == "bull" else ob_price - 15,
            }

        # --- Phase 3: AI assessment (slow — timeout-guarded) -----------------
        prompt = (
            f"Analiza XAU/USD na interwale {tf}:\n"
            f"- Trend: {trend}\n- Struktura: {structure}\n- FVG: {fvg}\n"
            f"- RSI: {rsi}\n- Order Block: {ob_price}\n- Obecna cena: {current_price}\n\n"
            f"Oceń na skali 0-10 czy to dobry sygnał. Zwróć też rekomendację kierunku."
        )

        try:
            ai_response = await asyncio.wait_for(
                asyncio.to_thread(
                    ask_agent_with_memory,
                    f"Oceń setup tradingowy XAU/USD na interwale {tf} i wydaj werdykt:\n{prompt}",
                    "web_analysis",
                ),
                timeout=_AI_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ AI assessment timed out after {_AI_TIMEOUT}s — returning SMC+ML only")
            ai_response = f"⏱️ AI assessment timed out ({_AI_TIMEOUT}s). Dane SMC i ML Ensemble poniżej są aktualne."
        except Exception as ai_err:
            logger.warning(f"AI analysis unavailable: {ai_err}")
            ai_response = "AI unavailable — SMC + ML Ensemble analysis only"

        # --- Build response ---------------------------------------------------
        response_data = {
            "timeframe": tf,
            "timestamp": datetime.now(timezone.utc),
            "smc_analysis": {
                "trend": trend,
                "structure": structure,
                "fvg": fvg,
                "rsi": rsi,
                "order_block": ob_price,
                "current_price": current_price,
            },
            "ai_assessment": ai_response,
            "position": {
                "direction": position.get("direction", direction),
                "entry": position.get("entry", ob_price),
                "stop_loss": position.get("sl"),
                "take_profit": position.get("tp"),
                "lot_size": position.get("lot", 0.1),
                "pattern": structure,
                "logic": position.get("logic", "SMC-based"),
            },
        }

        if "ensemble_data" in position:
            response_data["ml_ensemble"] = position["ensemble_data"]
            logger.info(f"✅ ML Ensemble integrated: {position['ensemble_data']['signal']}")

        _quant_pro_cache[tf] = {"data": response_data, "ts": time.time()}

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in QUANT PRO: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/ml-ensemble",
    summary="Get ML Ensemble Predictions",
    description="Get predictions from all ML models (LSTM, XGBoost, DQN) with voting ensemble"
)
def get_ml_ensemble_predictions(
    tf: str = Query("15m", description="Timeframe: 5m, 15m, 1h, 4h")
):
    """
    Get detailed ML ensemble predictions including individual model scores.
    """
    try:
        from src.ensemble_models import get_ensemble_prediction

        provider = get_provider()
        analysis = get_smc_analysis(tf)

        if not analysis:
            raise HTTPException(status_code=404, detail="Could not analyze market")

        ticker = provider.get_current_price('XAU/USD')
        if not ticker:
            raise HTTPException(status_code=404, detail="Could not fetch price")

        # Get candles for ML
        try:
            candles = provider.get_candles('XAU/USD', tf, 200)
        except Exception as e:
            logger.warning(f"Could not fetch candles: {e}")
            candles = None

        if candles is None or candles.empty:
            raise HTTPException(status_code=404, detail="Insufficient data for ML models")

        # Get ensemble prediction
        ensemble = get_ensemble_prediction(
            df=candles,
            smc_trend=analysis.get('trend', 'bull'),
            current_price=ticker['price'],
            balance=10000,
            initial_balance=10000,
            position=0
        )

        return {
            "timestamp": datetime.now(timezone.utc),
            "timeframe": tf,
            "current_price": ticker['price'],
            "ensemble_signal": ensemble['ensemble_signal'],
            "final_score": round(ensemble['final_score'], 4),
            "confidence": round(ensemble['confidence'], 2),
            "models_available": ensemble['models_available'],
            "individual_predictions": {
                model: {
                    "direction": pred.get("direction"),
                    "confidence": round(pred.get("confidence", 0), 2),
                    "value": round(pred.get("value", 0.5), 4),
                    "status": pred.get("status", "ok")
                }
                for model, pred in ensemble['predictions'].items()
            },
            "weights": ensemble['weights']
        }

    except Exception as e:
        logger.error(f"❌ Error in ML Ensemble: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/sentiment",
    summary="Get Market Sentiment",
    description="Get AI-based market sentiment analysis"
)
def get_sentiment_analysis():
    """
    Get market sentiment from AI analysis
    """
    try:
        from src.sentiment import get_sentiment_data

        sentiment = get_sentiment_data()

        return {
            "timestamp": datetime.now(timezone.utc),
            "sentiment": sentiment,
        }

    except Exception as e:
        logger.error(f"❌ Error fetching sentiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/news",
    summary="Get Economic News",
    description="Get latest economic calendar and news"
)
def get_news_analysis():
    """
    Get latest news and economic calendar
    """
    try:
        from src.news import get_latest_news, get_economic_calendar

        news = get_latest_news()
        calendar = get_economic_calendar()

        return {
            "timestamp": datetime.now(timezone.utc),
            "news": news,
            "economic_calendar": calendar,
        }

    except Exception as e:
        logger.error(f"❌ Error fetching news: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/stats",
    summary="Get Trading Statistics",
    description="Get trading performance stats"
)
def get_trading_stats():
    """
    Get trading statistics and performance metrics
    """
    try:
        db = NewsDB()

        # Get patterns stats
        try:
            patterns = db.get_all_patterns_stats()
        except Exception:
            patterns = []

        # Calculate totals
        total_trades = sum(p[1] for p in patterns) if patterns else 0
        total_wins = sum(p[2] for p in patterns) if patterns else 0
        total_losses = sum(p[3] for p in patterns) if patterns else 0
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

        return {
            "timestamp": datetime.now(timezone.utc),
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(win_rate, 2),
            "patterns": [
                {
                    "pattern": p[0],
                    "count": p[1],
                    "wins": p[2],
                    "losses": p[3],
                    "win_rate": round(p[4] * 100, 2) if len(p) > 4 and p[4] is not None else 0,
                }
                for p in patterns
                if len(p) >= 4
            ] if patterns else [],
        }

    except Exception as e:
        logger.error(f"❌ Error fetching stats: {e}")
        return {
            "timestamp": datetime.now(timezone.utc),
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "patterns": [],
        }


@router.get(
    "/trades",
    summary="Get Recent Trades",
    description="Get recent trading history"
)
def get_recent_trades(limit: int = Query(20, description="Number of trades to return")):
    """
    Get recent trading history with win/loss status
    """
    try:
        db = NewsDB()

        # Query recent trades — explicit column list
        db.cursor.execute(
            """
            SELECT id, direction, entry, sl, tp, status, timestamp, profit
            FROM trades
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        )

        trades = db.cursor.fetchall()

        if not trades:
            return {
                "timestamp": datetime.now(timezone.utc),
                "trades": [],
                "total": 0,
                "wins": 0,
                "losses": 0,
            }

        def _safe_float(v):
            """Convert to float safely, skipping non-numeric strings."""
            if v is None:
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        # Format trades
        formatted_trades = []
        wins = 0
        losses = 0

        for trade in trades:
            if not trade or not isinstance(trade, (list, tuple)):
                continue
            # Safe unpack — guard against column count mismatches from migrations
            try:
                cols = len(trade)
                trade_id = trade[0] if cols > 0 else None
                direction = trade[1] if cols > 1 else None
                entry = trade[2] if cols > 2 else None
                sl = trade[3] if cols > 3 else None
                tp = trade[4] if cols > 4 else None
                status = trade[5] if cols > 5 else None
                trade_time = trade[6] if cols > 6 else None
                profit = trade[7] if cols > 7 else None
            except (IndexError, TypeError):
                continue

            if trade_id is None:
                continue

            entry_f = _safe_float(entry)
            sl_f = _safe_float(sl)
            tp_f = _safe_float(tp)
            profit_f = _safe_float(profit)

            # Determine if trade was win or loss
            is_win = status in ("WIN", "PROFIT") if status else False
            if is_win:
                wins += 1
            elif status in ("LOSS",):
                losses += 1

            formatted_trades.append({
                "id": trade_id,
                "direction": direction or "?",
                "entry": f"${entry_f:.2f}" if entry_f is not None else None,
                "sl": f"${sl_f:.2f}" if sl_f is not None else None,
                "tp": f"${tp_f:.2f}" if tp_f is not None else None,
                "status": status or "PENDING",
                "profit": f"${profit_f:.2f}" if profit_f is not None else None,
                "timestamp": trade_time,
                "result": "✅ WIN" if is_win else "❌ LOSS" if status == "LOSS" else "⏳ PENDING"
            })

        return {
            "timestamp": datetime.now(timezone.utc),
            "trades": formatted_trades,
            "total": len(formatted_trades),
            "wins": wins,
            "losses": losses,
        }

    except Exception as e:
        logger.error(f"❌ Error fetching trades: {e}")
        # Return empty data instead of 500
        return {
            "timestamp": datetime.now(timezone.utc),
            "trades": [],
            "total": 0,
            "wins": 0,
            "losses": 0,
        }

