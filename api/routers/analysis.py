"""
api/routers/analysis.py - Trading analysis endpoints
Provides analysis functions from the bot
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger
from src.smc_engine import get_smc_analysis
from src.ai_engine import ask_ai_gold
from src.finance import calculate_position
from src.data_sources import get_provider
from src.config import USER_PREFS
from src.database import NewsDB

router = APIRouter()

@router.get(
    "/quant-pro",
    summary="Run QUANT PRO Analysis",
    description="Comprehensive SMC + AI + ML Ensemble analysis for XAU/USD"
)
async def quant_pro_analysis(
    tf: str = Query("15m", description="Timeframe: 5m, 15m, 1h, 4h")
):
    """
    QUANT PRO Analysis - Full comprehensive analysis with ML Ensemble.
    Returns: SMC analysis + AI evaluation + ML predictions + ensemble signal + trade parameters
    """
    try:
        # Get SMC analysis
        analysis = get_smc_analysis(tf)
        if not analysis:
            raise HTTPException(status_code=404, detail="Could not analyze market")

        # Get current price
        provider = get_provider()
        ticker = provider.get_current_price('XAU/USD')
        if not ticker:
            raise HTTPException(status_code=404, detail="Could not fetch price")

        current_price = ticker['price']

        # Get historical data for ML models
        try:
            candles = provider.get_candles('XAU/USD', tf, 200)
        except Exception as e:
            logger.warning(f"Could not fetch candles for ML: {e}")
            candles = None

        # Build AI prompt
        trend = analysis.get('trend', 'unknown')
        fvg = analysis.get('fvg', 'None')
        structure = analysis.get('structure', 'Stable')
        rsi = analysis.get('rsi', 50)
        ob_price = analysis.get('ob_price', current_price)

        prompt = f"""
        Analiza XAU/USD na interwale {tf}:
        - Trend: {trend}
        - Struktura: {structure}
        - FVG: {fvg}
        - RSI: {rsi}
        - Order Block: {ob_price}
        - Obecna cena: {current_price}

        Oceń na skali 0-10 czy to dobry sygnał. Zwróć też rekomendację kierunku.
        """

        # Get AI assessment
        try:
            ai_response = ask_ai_gold("trading_signal", prompt)
        except Exception as ai_err:
            logger.warning(f"AI analysis unavailable: {ai_err}")
            ai_response = "AI unavailable - SMC + ML Ensemble analysis only"

        # Calculate position with ML Ensemble integration
        direction = "LONG" if trend == "bull" else "SHORT"
        try:
            position = calculate_position(
                analysis_data=analysis,
                balance=10000,  # Default balance - w przyszłości z bazy
                user_currency="USD",
                td_api_key=USER_PREFS.get('td_api_key', ''),
                df=candles  # ← PASS DATAFRAME FOR ML MODELS
            )
        except Exception as pos_err:
            logger.warning(f"Position calculation failed: {pos_err}")
            position = {
                "lot": 0.1,
                "entry": ob_price,
                "sl": ob_price - 5 if trend == "bull" else ob_price + 5,
                "tp": ob_price + 15 if trend == "bull" else ob_price - 15,
            }

        # Build response with ML Ensemble data
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

        # Add ML Ensemble data if available
        if "ensemble_data" in position:
            response_data["ml_ensemble"] = position["ensemble_data"]
            logger.info(f"✅ ML Ensemble integrated: {position['ensemble_data']['signal']}")

        return response_data

    except Exception as e:
        logger.error(f"❌ Error in QUANT PRO: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/ml-ensemble",
    summary="Get ML Ensemble Predictions",
    description="Get predictions from all ML models (LSTM, XGBoost, DQN) with voting ensemble"
)
async def get_ml_ensemble_predictions(
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
async def get_sentiment_analysis():
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
async def get_news_analysis():
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
async def get_trading_stats():
    """
    Get trading statistics and performance metrics
    """
    try:
        db = NewsDB()

        # Get patterns stats
        patterns = db.get_all_patterns_stats()

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
                    "win_rate": round(p[4] * 100, 2),
                }
                for p in patterns
            ] if patterns else [],
        }

    except Exception as e:
        logger.error(f"❌ Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/trades",
    summary="Get Recent Trades",
    description="Get recent trading history"
)
async def get_recent_trades(limit: int = Query(20, description="Number of trades to return")):
    """
    Get recent trading history with win/loss status
    """
    try:
        db = NewsDB()

        # Query recent trades
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

        # Format trades
        formatted_trades = []
        wins = 0
        losses = 0

        for trade in trades:
            trade_id, direction, entry, sl, tp, status, trade_time, profit = trade

            # Determine if trade was win or loss
            is_win = status in ("WIN", "PROFIT") if status else False
            if is_win:
                wins += 1
            elif status in ("LOSS",):
                losses += 1

            formatted_trades.append({
                "id": trade_id,
                "direction": direction,
                "entry": f"${float(entry):.2f}" if entry else None,
                "sl": f"${float(sl):.2f}" if sl else None,
                "tp": f"${float(tp):.2f}" if tp else None,
                "status": status or "PENDING",
                "profit": f"${float(profit):.2f}" if profit else None,
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
        raise HTTPException(status_code=500, detail=str(e))

