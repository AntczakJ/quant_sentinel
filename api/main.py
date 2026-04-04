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
    FastAPI lifespan context manager - startup and shutdown
    """
    # Startup
    logger.info("🚀 Starting QUANT SENTINEL API...")
    try:
        from src.rl_agent import DQNAgent

        # Load RL Agent (bez TradingEnv - będzie inicjalizowany gdy będą dane)
        rl_agent = DQNAgent(state_size=22, action_size=3)

        # Try to load saved models
        try:
            model_path = "models/rl_agent.keras"
            if os.path.exists(model_path):
                rl_agent.load(model_path)
                logger.info("✅ RL Agent loaded from models/rl_agent.keras")
            else:
                logger.info("ℹ️ No saved RL Agent model found - using fresh agent")
        except Exception as e:
            logger.warning(f"⚠️ Could not load RL Agent: {e}")
            logger.info("ℹ️ Using fresh RL Agent instance")

        app_state["rl_agent"] = rl_agent
        app_state["rl_env"] = None  # Will be initialized when needed
        app_state["models_loaded"] = True
        logger.info("✅ All models initialized")

    except Exception as e:
        logger.error(f"❌ Error loading models: {e}")

    yield

    # Shutdown
    logger.info("🛑 Shutting down QUANT SENTINEL API...")

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
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connection manager and app state
app.connection_manager = connection_manager
app.state.app_state = app_state

# Include routers
from api.routers import market, signals, portfolio, models, training, analysis

app.include_router(market.router, prefix="/api/market", tags=["Market Data"])
app.include_router(signals.router, prefix="/api/signals", tags=["Trading Signals"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(models.router, prefix="/api/models", tags=["ML Models"])
app.include_router(training.router, prefix="/api/training", tags=["Training"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis & Bot Features"])

# WebSocket endpoints
@app.websocket("/ws/prices")
async def websocket_prices(websocket):
    """WebSocket endpoint for live price updates"""
    await connection_manager.connect(websocket, "prices")
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
            await connection_manager.broadcast({"type": "ping"}, "prices")
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, "prices")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await connection_manager.disconnect(websocket, "prices")

@app.websocket("/ws/signals")
async def websocket_signals(websocket):
    """WebSocket endpoint for live signal updates"""
    await connection_manager.connect(websocket, "signals")
    try:
        while True:
            data = await websocket.receive_text()
            await connection_manager.broadcast({"type": "ping"}, "signals")
    except WebSocketDisconnect:
        await connection_manager.disconnect(websocket, "signals")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
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
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )



