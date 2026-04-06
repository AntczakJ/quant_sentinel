"""
api/main.py - FastAPI application main entry point
"""

import sys
import os
import hashlib
import time as _time
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocketDisconnect, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Process start time for uptime tracking
_start_time = _time.monotonic()

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
    # Backfill missing trade profits (one-time migration)
    try:
        from src.database import NewsDB
        _db = NewsDB()
        _backfilled = _db.backfill_trade_profits()
        if _backfilled > 0:
            logger.info(f"🔧 Backfilled profit for {_backfilled} trades")

        # Clean up trades created with wrong/stale API prices
        # (e.g. scanner got $2,350 from API while gold is actually >$4,000)
        try:
            from api.routers.market import _persistent_cache as _mkt_cache
            ref_price = float(_mkt_cache.get("ticker", {}).get("price", 0))
            if ref_price > 1000:  # sanity: only if we have a reasonable reference
                _cleaned = _db.cleanup_invalid_trades(ref_price, tolerance_pct=0.25)
                if _cleaned > 0:
                    logger.info(f"🗑️ Cleaned {_cleaned} trades with invalid prices (ref: ${ref_price:.0f})")
        except Exception as ce:
            logger.debug(f"Trade cleanup skipped: {ce}")
    except Exception as e:
        logger.warning(f"Backfill trade profits skipped: {e}")

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
    Background scanner: cascading multi-timeframe SMC scan every 15 minutes.
    Checks 4h → 1h → 15m → 5m and places a trade on the first TF with a valid setup.

    Uses the same cascade logic as the Telegram bot scanner (src/scanner.py).
    Saves to both trades and scanner_signals with deduplication.

    Fixes vs old version:
    - Multi-TF cascade (was: 15m only)
    - Uses calculate_position() for direction (was: raw trend → LONG/SHORT always)
    - Requires strong SMC setup (was: any trend = trade)
    - Deduplication via processed_news hash (was: none)
    - Saves to trades table too (was: scanner_signals only)
    - Price sanity check (unchanged)
    """
    # Initial delay — wait for the API to fully start up
    await asyncio.sleep(45)

    while True:
        try:
            from src.database import NewsDB
            from src.api_optimizer import get_rate_limiter as _get_rl

            logger.info("📡 [BG Scanner] Starting multi-TF cascade scan (4h→1h→15m→5m)...")

            # Global credit pre-check — need at least 2 credits for the first TF
            _can, _ = _get_rl().can_use_credits(2)
            if not _can:
                logger.info("📡 [BG Scanner] Credits low — skipping this cycle")
                await asyncio.sleep(900)
                continue

            # Prefetch all timeframes to warm cache (reduces per-TF API calls in cascade)
            try:
                from src.data_sources import get_provider as _gp
                _provider = _gp()
                await asyncio.to_thread(_provider.prefetch_all_timeframes, 'XAU/USD')
            except Exception as _pf_err:
                logger.debug(f"📡 [BG Scanner] Prefetch skipped: {_pf_err}")

            db = NewsDB()

            # Read portfolio balance for position sizing
            portfolio_balance = 10000.0
            portfolio_currency = "USD"
            try:
                bal = db.get_param("portfolio_balance")
                if bal and float(bal) > 0:
                    portfolio_balance = float(bal)
                row = db._query_one(
                    "SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_currency_text'"
                )
                if row and row[0]:
                    portfolio_currency = str(row[0])
            except Exception:
                pass

            # Run cascade scan in thread pool (all SMC + finance calls are blocking)
            try:
                from src.scanner import cascade_mtf_scan
                trade = await asyncio.wait_for(
                    asyncio.to_thread(cascade_mtf_scan, db, portfolio_balance, portfolio_currency),
                    timeout=120.0,  # generous — cascade may check up to 4 TFs
                )
            except asyncio.TimeoutError:
                logger.warning("📡 [BG Scanner] MTF cascade timed out (120s)")
                await asyncio.sleep(900)
                continue

            if trade:
                import hashlib as _hl
                tf = trade['tf']
                tf_label = trade['tf_label']
                direction = trade['direction']
                entry = trade['entry']
                sl = trade['sl']
                tp = trade['tp']
                lot = trade.get('lot', 0.01)
                logic = trade.get('logic', 'SMC Auto')
                trend = trade.get('trend', 'bull')
                rsi = trade.get('rsi', 50.0)
                structure = trade.get('structure', 'Stable')

                # Deduplication — don't place the same trade twice
                # Uses same key format as Telegram scanner (src/scanner.py) so
                # they share dedup if both run against the same database.
                trade_key = _hl.md5(
                    f"mtf_{direction}_{entry:.1f}_{tf}".encode()
                ).hexdigest()

                if not db.is_news_processed(trade_key):
                    # Save to scanner_signals (signal history)
                    db.save_scanner_signal(
                        direction=direction,
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rsi=rsi,
                        trend=trend,
                        structure=f"[{tf_label}] {structure}"
                    )

                    # Save to trades (OPEN status for auto-resolver)
                    structure_desc = f"[{tf_label}] {structure}"
                    db.log_trade(
                        direction=direction,
                        price=entry,
                        sl=sl,
                        tp=tp,
                        rsi=rsi,
                        trend=trend,
                        structure=structure_desc,
                        pattern=f"[{tf_label}] {logic}",
                        lot=lot,
                    )

                    db.mark_news_as_processed(trade_key)

                    logger.info(
                        f"📡 [BG Scanner] ✅ {direction} on {tf_label} @ ${entry:.2f} "
                        f"SL:${sl:.2f} TP:${tp:.2f} | RSI={rsi:.1f} | {logic}"
                    )
                else:
                    logger.info(
                        f"📡 [BG Scanner] Trade {direction}@${entry:.1f} on {tf_label} "
                        f"already saved — skipping duplicate"
                    )
            else:
                logger.info("📡 [BG Scanner] No valid trade setup on any TF — waiting for next cycle")

        except asyncio.CancelledError:
            logger.info("📡 [BG Scanner] Task cancelled")
            return
        except Exception as e:
            logger.warning(f"📡 [BG Scanner] Error: {e}")

        # Wait 15 minutes until next scan
        await asyncio.sleep(900)


async def _broadcast_prices_task():
    """
    Broadcast live XAU/USD price via WebSocket to all connected clients every 30 seconds.
    Only fetches price when at least one client is connected to save API calls.
    Reuses ticker cache from market router when available.
    """
    await asyncio.sleep(15)  # Wait for server to fully start

    while True:
        try:
            if connection_manager.get_connection_count("prices") > 0:
                ticker = None

                # Try to reuse cached ticker from market router (0 credits)
                try:
                    from api.routers.market import _ticker_cache, _data_cache
                    import time as _t
                    cached = _ticker_cache.get("XAU/USD")
                    if cached and (_t.time() - cached["ts"]) < 60:
                        ticker = cached["data"]
                except Exception:
                    pass

                # Fallback: fetch from provider (1 credit) only if credits available
                if not ticker:
                    from src.api_optimizer import get_rate_limiter
                    can_use, _ = get_rate_limiter().can_use_credits(1)
                    if not can_use:
                        await asyncio.sleep(30)
                        continue
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

        await asyncio.sleep(30)


async def _auto_resolve_trades():
    """
    Auto-resolve PROPOSED/OPEN trades every 5 minutes.
    Marks trades WIN if current price hits TP, LOSS if it hits SL.
    Skips cycle when API credits are low to prioritize user-facing requests.
    """
    await asyncio.sleep(120)  # 2 min initial delay

    while True:
        try:
            from src.database import NewsDB

            # Try cached price first (0 credits)
            current_price = 0.0
            try:
                from api.routers.market import _ticker_cache, _data_cache
                import time as _t
                cached = _ticker_cache.get("XAU/USD")
                if cached and (_t.time() - cached["ts"]) < 120:
                    current_price = float(cached["data"].get("price", 0))
                elif _data_cache.get("last_price"):
                    current_price = float(_data_cache["last_price"])
            except Exception:
                pass

            # Fallback: fetch from provider (1 credit) only if credits available
            if current_price <= 0:
                from src.api_optimizer import get_rate_limiter
                can_use, _ = get_rate_limiter().can_use_credits(1)
                if not can_use:
                    logger.debug("[Resolver] Skipping — credits low, waiting for refill")
                    await asyncio.sleep(300)
                    continue
                from src.data_sources import get_provider
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
            open_trades = db._query(
                "SELECT id, direction, entry, sl, tp FROM trades WHERE status IN ('PROPOSED', 'OPEN')"
            )

            resolved = 0
            for row in open_trades:
                trade_id, direction, entry, sl, tp = row
                try:
                    entry_f = float(entry or 0)
                    sl_f = float(sl or 0)
                    tp_f = float(tp or 0)

                    # ── Price sanity: if entry is >25% from current price,
                    #    the trade was created with stale/wrong data — remove it.
                    if entry_f > 0 and current_price > 0:
                        deviation = abs(entry_f - current_price) / current_price
                        if deviation > 0.25:
                            db._execute("DELETE FROM trades WHERE id=?", (trade_id,))
                            logger.warning(
                                f"🗑️ [Resolver] Deleted trade #{trade_id}: entry=${entry_f:.2f} "
                                f"vs current=${current_price:.2f} (Δ{deviation:.0%})"
                            )
                            resolved += 1
                            continue

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
app.add_middleware(GZipMiddleware, minimum_size=512)  # Compress responses > 512 bytes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def etag_cache_middleware(request: Request, call_next):
    """
    Add ETag + Cache-Control for cacheable GET /api/* endpoints.
    Saves bandwidth: if the browser already has this data, returns 304 Not Modified.

    Cache strategy per endpoint:
    - /api/market/*       → 15s fresh, 60s stale-while-revalidate (price data)
    - /api/models/stats   → 60s fresh (model stats change rarely)
    - /api/analysis/*     → 30s fresh (session/confluence)
    - /api/signals/stats  → 30s fresh
    - /api/health         → no-store
    """
    response = await call_next(request)
    path = request.url.path

    if request.method != "GET":
        return response

    # Determine Cache-Control TTL based on endpoint
    cache_ttl = None
    if "/api/market/" in path:
        cache_ttl = "public, max-age=15, stale-while-revalidate=60"
    elif "/api/models/stats" in path:
        cache_ttl = "public, max-age=60, stale-while-revalidate=120"
    elif "/api/analysis/" in path:
        cache_ttl = "public, max-age=30, stale-while-revalidate=60"
    elif "/api/signals/stats" in path or "/api/signals/scanner" in path:
        cache_ttl = "public, max-age=30, stale-while-revalidate=90"

    if cache_ttl:
        # Read response body for ETag computation
        body = b""
        body_iterator = getattr(response, 'body_iterator', None)
        if body_iterator:
            async for chunk in body_iterator:
                body += chunk if isinstance(chunk, bytes) else chunk.encode()
        elif hasattr(response, 'body'):
            body = response.body if isinstance(response.body, bytes) else response.body.encode()

        etag = '"' + hashlib.md5(body).hexdigest() + '"'
        response = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_ttl

        # Check If-None-Match from client
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})

    return response

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
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
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
    except (WebSocketDisconnect, RuntimeError):
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


@app.get("/api/health/detailed")
async def health_check_detailed():
    """
    Detailed health check — returns uptime, DB status, background task state.
    Used by frontend ConnectionStatus component.
    """
    uptime_seconds = _time.monotonic() - _start_time

    # DB check
    db_ok = False
    db_tables = 0
    try:
        from src.database import NewsDB
        db = NewsDB()
        row = db._query_one("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        db_tables = row[0] if row else 0
        db_ok = db_tables > 0
    except Exception:
        pass

    # Format uptime
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": uptime_str,
        "uptime_seconds": round(uptime_seconds, 1),
        "models_loaded": app_state["models_loaded"],
        "database": {
            "connected": db_ok,
            "tables": db_tables,
        },
        "websocket_clients": {
            "prices": connection_manager.get_connection_count("prices"),
            "signals": connection_manager.get_connection_count("signals"),
        },
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



