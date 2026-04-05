"""
api/main.py - FastAPI application main entry point
"""

import sys
import os
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
# from fastapi.middleware.gzip import GZIPMiddleware  # Not available in this FastAPI version
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reduce uvicorn access log noise for frequent endpoints
_uvicorn_logger = logging.getLogger("uvicorn.access")
_uvicorn_logger.addFilter(
    type("QuietHealthFilter", (), {
        "filter": lambda self, record: "/api/health" not in record.getMessage()
            and "/health" not in record.getMessage()
    })()
)

from src.logger import logger
from api.websocket.manager import ConnectionManager

# Initialize global objects
connection_manager = ConnectionManager()
app_state = {
    "rl_agent": None,
    "rl_env": None,
    "models_loaded": False,
    "last_update": None,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager - startup and shutdown.
    Heavy model loading runs in a background thread so uvicorn starts
    accepting HTTP / WebSocket connections immediately.
    """
    # Startup — mark server as starting, yield quickly
    logger.info("🚀 Starting QUANT SENTINEL API...")

    async def _load_models():
        """Load ML models off the event-loop thread (import + init + load)."""
        def _sync_load():
            """Runs entirely in a worker thread — keeps the event loop free."""
            from src.rl_agent import DQNAgent  # triggers TF/Keras import
            rl_agent = DQNAgent(state_size=22, action_size=3)
            model_path = "models/rl_agent.keras"
            if os.path.exists(model_path):
                rl_agent.load(model_path)
                logger.info("✅ RL Agent loaded from models/rl_agent.keras")
            else:
                logger.info("ℹ️ No saved RL Agent model found - using fresh agent")
            return rl_agent

        try:
            rl_agent = await asyncio.to_thread(_sync_load)
            app_state["rl_agent"] = rl_agent
            app_state["rl_env"] = None
            app_state["models_loaded"] = True
            logger.info("✅ All models initialized")

        except Exception as e:
            logger.error(f"❌ Error loading models: {e}")
            app_state["models_loaded"] = False

    # Start model loading + background tasks (all non-blocking)
    model_task = asyncio.create_task(_load_models())
    scanner_task = asyncio.create_task(_background_scanner())
    prices_task = asyncio.create_task(_broadcast_prices_task())
    resolver_task = asyncio.create_task(_auto_resolve_trades())
    logger.info("📡 Background tasks started (scanner 15min | prices 5s | resolver 5min)")

    yield

    # Shutdown — cancel all background tasks
    for task in (model_task, scanner_task, prices_task, resolver_task):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    logger.info("🛑 Shutting down QUANT SENTINEL API...")


async def _background_scanner():
    """
    Background scanner: runs SMC analysis every 15 minutes and saves signals to DB.
    This ensures the signal history is always populated even without the Telegram bot.
    """
    # Initial delay — wait for the API to fully start up
    await asyncio.sleep(45)

    while True:
        try:
            from src.smc_engine import get_smc_analysis
            from src.finance import calculate_position
            from src.database import NewsDB

            logger.info("📡 [BG Scanner] Running SMC scan...")
            analysis = await asyncio.to_thread(get_smc_analysis, "15m")

            if analysis:
                price = float(analysis.get('price', 2000.0))
                trend = str(analysis.get('trend', 'bull'))
                rsi = float(analysis.get('rsi', 50.0))
                structure = str(analysis.get('structure', 'Stable'))
                direction = "LONG" if trend.lower() == "bull" else "SHORT"
                atr = float(analysis.get('atr', 5.0))

                # Calculate SL/TP from position engine
                try:
                    pos = await asyncio.to_thread(calculate_position, analysis, 10000, "USD", "")
                    sl = float(pos.get('sl') or (price - atr))
                    tp = float(pos.get('tp') or (price + atr * 2.5))
                except Exception:
                    sl = round(price - atr, 2)
                    tp = round(price + atr * 2.5, 2)

                db = NewsDB()
                db.save_scanner_signal(
                    direction=direction,
                    entry=price,
                    sl=sl,
                    tp=tp,
                    rsi=rsi,
                    trend=trend,
                    structure=structure
                )
                logger.info(f"📡 [BG Scanner] Saved {direction} signal @ ${price:.2f} | RSI={rsi:.1f}")
            else:
                logger.warning("📡 [BG Scanner] No analysis data available")

        except asyncio.CancelledError:
            logger.info("📡 [BG Scanner] Task cancelled")
            return
        except Exception as e:
            logger.warning(f"📡 [BG Scanner] Error: {e}")

        # Wait 15 minutes until next scan
        await asyncio.sleep(900)


async def _broadcast_prices_task():
    """
    Broadcast live XAU/USD price via WebSocket to all connected clients every 10 seconds.
    Only fetches price when at least one client is connected to save API calls.
    """
    await asyncio.sleep(15)  # Wait for server to fully start

    while True:
        try:
            if connection_manager.get_connection_count("prices") > 0:
                from src.data_sources import get_provider
                provider = get_provider()
                ticker = await asyncio.to_thread(provider.get_current_price, "XAU/USD")
                if ticker:
                    await connection_manager.broadcast(
                        {
                            "type": "price",
                            "symbol": "XAU/USD",
                            "price": float(ticker.get("price", 0)),
                            "change": float(ticker.get("change", 0)),
                            "change_pct": float(ticker.get("change_pct", 0)),
                            "high_24h": float(ticker["high_24h"]) if ticker.get("high_24h") else None,
                            "low_24h": float(ticker["low_24h"]) if ticker.get("low_24h") else None,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        "prices",
                    )
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[PriceBroadcast] Error: {e}")

        await asyncio.sleep(10)


async def _auto_resolve_trades():
    """
    Auto-resolve PROPOSED/OPEN trades every 5 minutes.
    Marks trades WIN if current price hits TP, LOSS if it hits SL.
    """
    await asyncio.sleep(120)  # 2 min initial delay

    while True:
        try:
            from src.data_sources import get_provider
            from src.database import NewsDB

            provider = get_provider()
            ticker = await asyncio.to_thread(provider.get_current_price, "XAU/USD")
            if not ticker:
                await asyncio.sleep(300)
                continue

            current_price = float(ticker.get("price", 0))
            if current_price <= 0:
                await asyncio.sleep(300)
                continue

            db = NewsDB()
            db.cursor.execute(
                "SELECT id, direction, entry, sl, tp FROM trades WHERE status IN ('PROPOSED', 'OPEN')"
            )
            open_trades = db.cursor.fetchall()

            resolved = 0
            for row in open_trades:
                trade_id, direction, entry, sl, tp = row
                try:
                    entry_f = float(entry or 0)
                    sl_f = float(sl or 0)
                    tp_f = float(tp or 0)

                    hit_tp = hit_sl = False
                    if direction == "LONG":
                        hit_tp = tp_f > 0 and current_price >= tp_f
                        hit_sl = sl_f > 0 and current_price <= sl_f
                    elif direction == "SHORT":
                        hit_tp = tp_f > 0 and current_price <= tp_f
                        hit_sl = sl_f > 0 and current_price >= sl_f

                    if hit_tp:
                        profit = round(abs(tp_f - entry_f), 2) if entry_f > 0 else 0
                        db._execute(
                            "UPDATE trades SET status='WIN', profit=? WHERE id=?",
                            (profit, trade_id),
                        )
                        resolved += 1
                        logger.info(f"✅ [Resolver] Trade #{trade_id} WIN @ ${current_price:.2f} (TP:{tp_f})")
                    elif hit_sl:
                        loss = round(-abs(entry_f - sl_f), 2) if entry_f > 0 else 0
                        db._execute(
                            "UPDATE trades SET status='LOSS', profit=? WHERE id=?",
                            (loss, trade_id),
                        )
                        resolved += 1
                        logger.info(f"❌ [Resolver] Trade #{trade_id} LOSS @ ${current_price:.2f} (SL:{sl_f})")
                except Exception as e:
                    logger.debug(f"[Resolver] Trade #{trade_id} error: {e}")

            if resolved > 0:
                logger.info(f"📊 [Resolver] Resolved {resolved}/{len(open_trades)} trades @ ${current_price:.2f}")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[Resolver] Error: {e}")

        await asyncio.sleep(300)  # Every 5 minutes


# Create FastAPI app
app = FastAPI(
    title="QUANT SENTINEL Trading API",
    description="Professional trading platform API with ML models",
    version="2.1.0",
    lifespan=lifespan
)

# Middleware
# app.add_middleware(GZIPMiddleware, minimum_size=1000)  # Not available in this FastAPI version
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connection manager and app state
app.connection_manager = connection_manager
app.state.app_state = app_state

# Include routers
from api.routers import market, signals, portfolio, models, training, analysis, agent

app.include_router(market.router, prefix="/api/market", tags=["Market Data"])
app.include_router(signals.router, prefix="/api/signals", tags=["Trading Signals"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(models.router, prefix="/api/models", tags=["ML Models"])
app.include_router(training.router, prefix="/api/training", tags=["Training"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis & Bot Features"])
app.include_router(agent.router, prefix="/api/agent", tags=["AI Agent"])

# WebSocket endpoints
@app.websocket("/ws/prices")
async def websocket_prices(websocket):
    """WebSocket endpoint for live price updates (server-push every 5s).
    The receive loop keeps the connection alive and detects client disconnects.
    """
    await connection_manager.connect(websocket, "prices")
    logger.info("🟢 WebSocket client connected to /ws/prices")
    try:
        while True:
            # Block until the client sends something (ping/pong or close frame).
            # WebSocketDisconnect is raised when the client closes the connection.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("🟡 WebSocket /ws/prices client disconnected")
    except Exception as e:
        logger.debug(f"WebSocket /ws/prices closed: {type(e).__name__}")
    finally:
        await connection_manager.disconnect(websocket, "prices")

@app.websocket("/ws/signals")
async def websocket_signals(websocket):
    """WebSocket endpoint for live signal updates."""
    await connection_manager.connect(websocket, "signals")
    logger.info("🟢 WebSocket client connected to /ws/signals")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("🟡 WebSocket /ws/signals client disconnected")
    except Exception as e:
        logger.debug(f"WebSocket /ws/signals closed: {type(e).__name__}")
    finally:
        await connection_manager.disconnect(websocket, "signals")

# Health check - both /health and /api/health
@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models_loaded": app_state["models_loaded"],
    }

# Root endpoint
@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "QUANT SENTINEL Trading API",
        "version": "2.1.0",
        "docs": "/docs",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn
    _port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=_port,
        reload=True,
        log_level="info",
    )



