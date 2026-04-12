"""
api/main.py - FastAPI application main entry point
"""

import sys
import os
import hashlib
import time as _time
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import asyncio
import json as _json
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── PRODUCTION HARDENING ──────────────────────────────────────────────
# Explicitly clear any backtest-mode env vars that might have leaked from
# a shell session. Production API must NEVER apply relaxed filters.
# Runs before any src.* imports.
for _bt_flag in ("QUANT_BACKTEST_MODE", "QUANT_BACKTEST_RELAX"):
    if os.environ.get(_bt_flag):
        print(f"[PRODUCTION API] WARNING: {_bt_flag} was set, clearing for safety", flush=True)
    os.environ.pop(_bt_flag, None)

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

from src.core.logger import logger
from api.websocket.manager import ConnectionManager

# Initialize global objects
connection_manager = ConnectionManager()

# ── SSE (Server-Sent Events) — replaces WebSocket for price/signal push ──
# Each subscriber gets an asyncio.Queue; broadcast pushes to all queues.
_sse_subscribers: dict[str, set[asyncio.Queue]] = {"prices": set(), "signals": set()}
_sse_lock = asyncio.Lock()

async def sse_subscribe(channel: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=10)
    async with _sse_lock:
        _sse_subscribers.setdefault(channel, set()).add(q)
    return q

async def sse_unsubscribe(channel: str, q: asyncio.Queue):
    async with _sse_lock:
        _sse_subscribers.get(channel, set()).discard(q)

async def sse_broadcast(channel: str, data: dict):
    async with _sse_lock:
        dead = []
        for q in _sse_subscribers.get(channel, set()):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _sse_subscribers[channel].discard(q)
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
    # Startup — validate config, then start
    logger.info("Starting QUANT SENTINEL API...")
    try:
        from src.core.config import validate_startup_config
        validate_startup_config()
    except (ImportError, AttributeError):
        pass

    # Database: enable WAL mode + startup backup + users table
    try:
        from src.ops.db_backup import enable_wal_mode, create_backup
        enable_wal_mode()
        create_backup(reason="startup")
    except (ImportError, AttributeError):
        pass
    try:
        from src.core.auth import create_users_table
        create_users_table()
    except (ImportError, AttributeError):
        pass

    async def _load_models():
        """Load ML models off the event-loop thread (import + init + load)."""
        def _sync_load():
            """Runs entirely in a worker thread — keeps the event loop free."""
            from src.ml.rl_agent import DQNAgent  # triggers TF/Keras import
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
        from src.core.database import NewsDB
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
    monitor_task = asyncio.create_task(_monitoring_loop())
    retention_task = asyncio.create_task(_daily_retention_cleanup())
    logger.info("Background tasks started (scanner 5min | prices 5s | resolver 5min | monitor 1h | retention 24h)")

    yield

    # ── Graceful shutdown with drain period ──
    logger.info("Shutdown initiated — draining pending operations (30s timeout)...")

    # 1. Close all WebSocket connections gracefully
    try:
        await connection_manager.close_all()
    except Exception:
        pass

    # 2. Cancel background tasks with drain timeout
    tasks = [model_task, scanner_task, prices_task, resolver_task, monitor_task, retention_task]
    for task in tasks:
        task.cancel()

    # Wait up to 30s for tasks to finish current work
    done, pending = await asyncio.wait(tasks, timeout=30.0, return_when=asyncio.ALL_COMPLETED)
    if pending:
        logger.warning(f"{len(pending)} task(s) did not finish within 30s — force cancelling")
        for task in pending:
            task.cancel()

    # 3. Flush database
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.conn.commit()
    except Exception:
        pass

    logger.info("QUANT SENTINEL API shutdown complete")


async def _background_scanner():
    """
    Background scanner: cascading multi-timeframe SMC scan every 5 minutes.
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

    # Scanner cadence (seconds). 300 = 5 min = 4x more opportunities than
    # old 900/15min setup. Credit cost: ~8 credits per cascade → 1.6/min
    # avg usage on a 55/min budget = well within limits.
    _SCAN_INTERVAL_SEC = 300

    while True:
        try:
            from src.core.database import NewsDB
            from src.api_optimizer import get_rate_limiter as _get_rl

            logger.info("📡 [BG Scanner] Starting multi-TF cascade scan (4h→1h→15m→5m)...")

            # Global credit pre-check — need at least 2 credits for the first TF
            _can, _ = _get_rl().can_use_credits(2)
            if not _can:
                logger.info("📡 [BG Scanner] Credits low — skipping this cycle")
                await asyncio.sleep(_SCAN_INTERVAL_SEC)
                continue

            # Prefetch all timeframes to warm cache (reduces per-TF API calls in cascade)
            try:
                from src.data.data_sources import get_provider as _gp
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
                curr = db.get_param("portfolio_currency_text")
                if curr:
                    portfolio_currency = str(curr)
            except Exception:
                pass

            # Run cascade scan in thread pool (all SMC + finance calls are blocking)
            try:
                from src.trading.scanner import cascade_mtf_scan
                trade = await asyncio.wait_for(
                    asyncio.to_thread(cascade_mtf_scan, db, portfolio_balance, portfolio_currency),
                    timeout=120.0,  # generous — cascade may check up to 4 TFs
                )
            except asyncio.TimeoutError:
                logger.warning("📡 [BG Scanner] MTF cascade timed out (120s)")
                await asyncio.sleep(_SCAN_INTERVAL_SEC)
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
                    factors = trade.get('factors')
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
                        factors=factors,
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

        # Wait until next scan cycle
        await asyncio.sleep(_SCAN_INTERVAL_SEC)


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
                    from src.data.data_sources import get_provider
                    provider = get_provider()
                    ticker = await asyncio.to_thread(provider.get_current_price, "XAU/USD")

                if ticker:
                    msg = {
                        "type": "price",
                        "symbol": "XAU/USD",
                        "price": float(ticker.get("price", 0)),
                        "change": float(ticker.get("change", 0)),
                        "change_pct": float(ticker.get("change_pct", 0)),
                        "high_24h": float(ticker["high_24h"]) if ticker.get("high_24h") else None,
                        "low_24h": float(ticker["low_24h"]) if ticker.get("low_24h") else None,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                    # Push to both SSE subscribers and legacy WebSocket
                    await sse_broadcast("prices", msg)
                    await connection_manager.broadcast(msg, "prices")
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
            from src.core.database import NewsDB

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
                from src.data.data_sources import get_provider
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

                    if hit_tp or hit_sl:
                        status = "WIN" if hit_tp else "LOSS"
                        pnl = round(abs(tp_f - entry_f), 2) if hit_tp else round(-abs(entry_f - sl_f), 2)
                        if entry_f <= 0:
                            pnl = 0
                        db._execute(
                            "UPDATE trades SET status=?, profit=? WHERE id=?",
                            (status, pnl, trade_id),
                        )

                        # Fill failure_reason + condition for LOSS trades
                        if hit_sl:
                            reason = (
                                f"Cena dotknela SL (${sl_f:.2f}). "
                                f"Wejscie: ${entry_f:.2f}, kierunek: {direction}."
                            )
                            db._execute(
                                "UPDATE trades SET failure_reason=?, condition_at_loss=? WHERE id=?",
                                (reason, f"Cena: ${current_price:.2f}", trade_id),
                            )

                        resolved += 1

                        # Update pattern/session stats (same as scanner resolver)
                        try:
                            trow = db._query_one("SELECT pattern, session FROM trades WHERE id=?", (trade_id,))
                            if trow and trow[0]:
                                db.update_pattern_stats(trow[0], status)
                                if trow[1]:
                                    db.update_session_stats(trow[0], trow[1], status)
                        except Exception:
                            pass

                        # Update factor weights for self-learning
                        try:
                            from src.learning.self_learning import update_factor_weights
                            update_factor_weights(trade_id, status)
                        except Exception:
                            pass

                        icon = "✅" if hit_tp else "❌"
                        target = f"TP:{tp_f}" if hit_tp else f"SL:{sl_f}"
                        logger.info(f"{icon} [Resolver] Trade #{trade_id} {status} @ ${current_price:.2f} ({target})")
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

# Middleware — custom auth/rate use pure ASGI wrappers that bypass WebSocket
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.jwt_auth import JwtAuthMiddleware
app.add_middleware(JwtAuthMiddleware)
app.add_middleware(RateLimitMiddleware)
# CORS — only needed when frontend runs on different port (vite dev server)
# When serving from same origin (:8000), CORS is not needed.
# Using custom ASGI wrapper to avoid CORSMiddleware blocking WebSocket.

class _CorsHeaderMiddleware:
    """Minimal CORS that doesn't touch WebSocket."""
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            async def send_with_cors(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    extra = [
                        (b"access-control-allow-origin", b"*"),
                        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE, OPTIONS"),
                        (b"access-control-allow-headers", b"*"),
                    ]
                    message["headers"] = list(message.get("headers", [])) + extra
                await send(message)
            await self.app(scope, receive, send_with_cors)
        else:
            await self.app(scope, receive, send)

app.add_middleware(_CorsHeaderMiddleware)


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

async def _monitoring_loop():
    """
    Background monitoring: drift checks, daily summaries, health alerts.
    Runs every hour. Daily summary at 22:00 UTC (end of NY session).
    """
    await asyncio.sleep(120)  # 2 min initial delay (let other tasks warm up)
    last_daily_date = None
    last_weekly_weekday = None

    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)

            # Daily summary + report at 22:00 UTC (once per day)
            if now.hour == 22 and last_daily_date != now.date():
                try:
                    from src.ops.monitoring import send_daily_summary
                    await asyncio.to_thread(send_daily_summary)
                    last_daily_date = now.date()
                except (ImportError, AttributeError) as e:
                    logger.debug(f"Daily summary skipped: {e}")

                # Generate persistent daily report
                try:
                    from src.ops.compliance import generate_daily_report
                    await asyncio.to_thread(generate_daily_report)
                except (ImportError, AttributeError):
                    pass

                # Data retention (monthly, on 1st of month)
                if now.day == 1:
                    try:
                        from src.ops.compliance import archive_old_data
                        await asyncio.to_thread(archive_old_data)
                    except (ImportError, AttributeError):
                        pass

            # Weekly report on Sunday
            if now.weekday() == 6 and now.hour == 20 and last_weekly_weekday != now.isocalendar()[1]:
                try:
                    from src.ops.monitoring import send_weekly_report
                    await asyncio.to_thread(send_weekly_report)
                    last_weekly_weekday = now.isocalendar()[1]
                except (ImportError, AttributeError) as e:
                    logger.debug(f"Weekly report skipped: {e}")

            # Model drift check every 6 hours
            if now.hour % 6 == 0 and now.minute < 5:
                try:
                    from src.ops.monitoring import check_and_alert_drift
                    await asyncio.to_thread(check_and_alert_drift)
                except (ImportError, AttributeError) as e:
                    logger.debug(f"Drift check skipped: {e}")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"Monitoring loop error: {e}")

        await asyncio.sleep(3600)  # check every hour


async def _daily_retention_cleanup():
    """
    Daily data retention: archive old trades, purge stale news/predictions.
    Runs once per day at 03:00 UTC (low-activity period).
    """
    await asyncio.sleep(300)  # 5 min initial delay
    last_run_date = None

    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)

            # Run once per day at 03:00 UTC
            if now.hour == 3 and last_run_date != now.date():
                try:
                    from src.core.database import NewsDB
                    db = NewsDB()
                    summary = await asyncio.to_thread(db.run_retention_cleanup)
                    last_run_date = now.date()
                    total = sum(summary.values())
                    if total > 0:
                        logger.info(f"[RETENTION] Daily cleanup: {summary}")
                except Exception as e:
                    logger.warning(f"[RETENTION] Daily cleanup failed: {e}")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[RETENTION] Loop error: {e}")

        await asyncio.sleep(3600)  # Check every hour


import datetime

# Include routers
from api.routers import market, signals, portfolio, models, training, analysis, agent, risk, export, auth

app.include_router(market.router, prefix="/api/market", tags=["Market Data"])
app.include_router(signals.router, prefix="/api/signals", tags=["Trading Signals"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(models.router, prefix="/api/models", tags=["ML Models"])
app.include_router(training.router, prefix="/api/training", tags=["Training"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis & Bot Features"])
app.include_router(agent.router, prefix="/api/agent", tags=["AI Agent"])
app.include_router(risk.router, prefix="/api/risk", tags=["Risk Management"])
app.include_router(export.router, prefix="/api/export", tags=["Data Export"])
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])


@app.get("/api/metrics", tags=["System"])
async def get_metrics():
    """System metrics: trades, latency, portfolio, model health."""
    try:
        from src.ops.metrics import get_all_metrics
        return get_all_metrics()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/news/similar", tags=["System"])
async def find_similar(headline: str = ""):
    """Find similar historical headlines and their gold impact."""
    if not headline:
        return {"error": "Provide ?headline=your+headline+here"}
    try:
        from src.data.news_similarity import find_similar_news
        return await asyncio.to_thread(find_similar_news, headline)
    except Exception as e:
        return {"error": str(e), "signal": 0}


@app.get("/api/events", tags=["System"])
async def get_events():
    """Historical gold reaction to CPI, FOMC, NFP events."""
    try:
        from src.data.event_reactions import get_all_event_biases
        return await asyncio.to_thread(get_all_event_biases)
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/news", tags=["System"])
async def get_news():
    """Gold-relevant news with sentiment classification."""
    try:
        from src.data.news_feed import get_gold_news_signal
        return await asyncio.to_thread(get_gold_news_signal)
    except Exception as e:
        return {"error": str(e), "signal": 0}


@app.get("/api/macro", tags=["System"])
async def get_macro():
    """Full macro signal: FRED real yields, retail sentiment, seasonality, COT."""
    try:
        from src.data.macro_data import get_full_macro_signal
        return await asyncio.to_thread(get_full_macro_signal)
    except Exception as e:
        return {"error": str(e), "composite_signal": 0}


@app.post("/api/webhook/tradingview", tags=["Webhooks"])
async def tradingview_webhook(request: Request):
    """TradingView alert webhook — forwards alerts to Telegram."""
    import requests as _requests
    data = await request.json()
    if not data:
        return Response(content="No Data", status_code=400)
    try:
        from src.core.config import TOKEN, CHAT_ID
    except ImportError:
        return Response(content="Config unavailable", status_code=500)
    ticker = data.get("ticker", "GOLD")
    action = data.get("action", "SIGNAL")
    price = data.get("price", "???")
    alert_msg = (
        f"\U0001f514 *ALERT TRADINGVIEW: {ticker}*\n"
        f"\U0001f680 Akcja: *{action}*\n"
        f"\U0001f4b0 Cena: `{price}`"
    )
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    _requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": alert_msg,
        "parse_mode": "Markdown"
    })
    return Response(content="OK", status_code=200)


@app.get("/api/health/detailed", tags=["System"])
async def get_detailed_health():
    """Comprehensive health check: database, models, risk manager, data provider."""
    try:
        from src.ops.monitoring import get_system_health
        return await asyncio.to_thread(get_system_health)
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── SSE endpoints — modern replacement for WebSocket (auto-reconnect built-in) ──

@app.get("/api/sse/prices", include_in_schema=False)
async def sse_prices(request: Request):
    """Server-Sent Events stream for live price updates."""
    q = await sse_subscribe("prices")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=35)
                    yield f"data: {_json.dumps(data, default=str)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive comment to prevent connection timeout
                    yield ": heartbeat\n\n"
        finally:
            await sse_unsubscribe("prices", q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/sse/signals", include_in_schema=False)
async def sse_signals(request: Request):
    """Server-Sent Events stream for live signal updates."""
    q = await sse_subscribe("signals")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=35)
                    yield f"data: {_json.dumps(data, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            await sse_unsubscribe("signals", q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Legacy WebSocket endpoints (kept for backwards compatibility)
@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
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
async def websocket_signals(websocket: WebSocket):
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
    uptime_s = _time.monotonic() - _start_time
    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "models_loaded": app_state["models_loaded"],
        "uptime_seconds": round(uptime_s),
        "uptime": f"{int(uptime_s // 3600)}h {int((uptime_s % 3600) // 60)}m",
    }


@app.get("/api/health/detailed")
async def health_check_detailed():
    """
    Detailed health check — returns uptime, DB status, background task state.
    Used by frontend ConnectionStatus component.
    """
    uptime_seconds = _time.monotonic() - _start_time

    # DB check (compatible with both SQLite and Turso/libsql)
    db_ok = False
    db_tables = 0
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        # Use a known table instead of sqlite_master (Turso-safe)
        row = db._query_one("SELECT COUNT(*) FROM trades")
        db_ok = row is not None
        db_tables = row[0] if row else 0
    except Exception:
        pass

    # Format uptime
    hours, remainder = divmod(int(uptime_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return {
        "status": "healthy",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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


@app.get("/api/backtest/runs", tags=["System"])
async def backtest_runs(limit: int = 20):
    """List recent backtest run JSON files with summary metadata.

    Reads from reports/*.json and data/bt_*.json. Returns descending by mtime.
    This is READ-ONLY — never touches backtest.db or sentinel.db.
    """
    import os as _os
    import glob as _glob
    import json as _json

    patterns = ["reports/*.json", "data/bt_*.json"]
    files = []
    for p in patterns:
        files.extend(_glob.glob(p))
    # Unique + sort by mtime desc
    files = sorted(set(files), key=lambda f: _os.path.getmtime(f), reverse=True)[:limit]

    runs = []
    for path in files:
        try:
            data = _json.loads(open(path, "r", encoding="utf-8").read())
        except Exception:
            continue
        runs.append({
            "path": path,
            "name": _os.path.basename(path).replace(".json", ""),
            "mtime": _os.path.getmtime(path),
            "trades": data.get("total_trades", 0),
            "wins": data.get("wins", 0),
            "losses": data.get("losses", 0),
            "breakevens": data.get("breakevens", 0),
            "win_rate_pct": data.get("win_rate_pct", 0),
            "profit_factor": data.get("profit_factor", "—"),
            "return_pct": data.get("return_pct", 0),
            "max_drawdown_pct": data.get("max_drawdown_pct", 0),
            "max_consec_losses": data.get("max_consec_losses", 0),
            "cycles_total": data.get("cycles_total", 0),
            "alpha_vs_bh_pct": data.get("alpha_vs_bh_pct"),
            "sharpe": data.get("analytics", {}).get("risk_adjusted", {}).get("sharpe"),
            "sortino": data.get("analytics", {}).get("risk_adjusted", {}).get("sortino"),
            "expectancy": data.get("analytics", {}).get("expectancy", {}).get("expectancy_per_trade_usd"),
        })
    return {"count": len(runs), "runs": runs}


@app.get("/api/backtest/latest", tags=["System"])
async def backtest_latest():
    """Latest backtest run — full JSON of the most recent result.

    Returns 404 if no runs found.
    """
    import os as _os
    import glob as _glob
    import json as _json

    patterns = ["reports/*.json", "data/bt_*.json"]
    files = []
    for p in patterns:
        files.extend(_glob.glob(p))
    if not files:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No backtest runs found")
    latest = max(files, key=lambda f: _os.path.getmtime(f))
    try:
        data = _json.loads(open(latest, "r", encoding="utf-8").read())
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to read {latest}: {e}")
    return {"path": latest, "mtime": _os.path.getmtime(latest), "data": data}


@app.get("/api/training/history", tags=["System"])
async def training_history(limit: int = 20, model_type: Optional[str] = None):
    """Recent training runs from models/training_history.jsonl.

    Returns list of {model_type, timestamp, metrics, git_commit, hyperparams}
    ordered newest-first.
    """
    try:
        from src.ml.training_registry import list_runs
        runs = list_runs(model_type=model_type, limit=limit)
        # Slim down payload (artifacts, full hyperparams can be large)
        return {
            "count": len(runs),
            "runs": [
                {
                    "model_type": r.get("model_type"),
                    "timestamp": r.get("timestamp"),
                    "git_commit": r.get("git_commit"),
                    "git_dirty": r.get("git_dirty"),
                    "metrics": r.get("metrics", {}),
                    "notes": r.get("notes"),
                    "artifact_size_kb": round(
                        r.get("artifact", {}).get("size_bytes", 0) / 1024, 1
                    ) if r.get("artifact") else None,
                }
                for r in runs
            ],
        }
    except Exception as e:
        return {"count": 0, "runs": [], "error": str(e)}


@app.get("/api/health/models", tags=["System"])
async def health_models():
    """Model artifact health — file ages + staleness warnings.

    Status per model:
      - "fresh": <14 days old
      - "stale": >=14 days (warning — consider retraining)
      - "missing": file not found
    """
    import os
    models = {
        "rl_agent": "models/rl_agent.keras",
        "lstm": "models/lstm.keras",
        "xgb": "models/xgb.pkl",
        "attention": "models/attention.keras",
        "decompose": "models/decompose.keras",
    }
    now_ts = _time.time()
    results = {}
    any_stale = False
    any_missing = False
    for name, path in models.items():
        if not os.path.exists(path):
            results[name] = {"status": "missing", "path": path}
            any_missing = True
            continue
        age_s = now_ts - os.path.getmtime(path)
        age_days = age_s / 86400
        stale = age_days >= 14
        if stale:
            any_stale = True
        results[name] = {
            "status": "stale" if stale else "fresh",
            "path": path,
            "size_kb": round(os.path.getsize(path) / 1024, 1),
            "age_days": round(age_days, 1),
            "mtime": datetime.datetime.fromtimestamp(
                os.path.getmtime(path), tz=datetime.timezone.utc
            ).isoformat(),
        }
    overall = "degraded" if any_missing else ("stale" if any_stale else "fresh")
    return {
        "status": overall,
        "models": results,
        "threshold_days": 14,
    }


@app.get("/api/health/scanner", tags=["System"])
async def health_scanner():
    """Scanner health — timing, error rate, last run timestamp.

    Status:
      - "healthy": ran in last 20 min AND error_rate < 10%
      - "stale": no run in last 20 min
      - "degraded": error_rate >= 10%
    """
    from src.ops.metrics import scan_duration, scan_errors_total, scan_last_ts, data_fetch_failures
    now_ts = _time.time()
    last = scan_last_ts.value
    seconds_since = (now_ts - last) if last > 0 else None
    count = scan_duration.count
    err_rate = (scan_errors_total.value / count) if count > 0 else 0.0

    if count == 0:
        status = "no_data"
    elif seconds_since is not None and seconds_since > 20 * 60:
        status = "stale"
    elif err_rate >= 0.1:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "scans_total": count,
        "errors_total": scan_errors_total.value,
        "error_rate": round(err_rate, 3),
        "avg_duration_ms": round(scan_duration.avg * 1000, 1),
        "p95_duration_ms": round(scan_duration.p95 * 1000, 1),
        "last_run_seconds_ago": round(seconds_since, 1) if seconds_since is not None else None,
        "data_fetch_failures": data_fetch_failures.value,
    }


# ── Serve frontend static files (production: built SPA from frontend/dist) ──
_frontend_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    from fastapi.responses import FileResponse

    # Serve static assets via explicit handler (mounts block WebSocket in Starlette 1.0)
    _assets_dir = os.path.join(_frontend_dist, "assets")
    _chunks_dir = os.path.join(_frontend_dist, "chunks")

    # Serve SPA: explicit routes for known pages + root-level static files
    _index_html = os.path.join(_frontend_dist, "index.html")

    @app.get("/", include_in_schema=False)
    async def _spa_root():
        return FileResponse(_index_html)

    # Client-side routes (React Router)
    for _r in ["analysis", "trades", "models", "news", "agent", "settings"]:
        def _make_handler(p=_r):
            async def _h():
                return FileResponse(_index_html)
            _h.__name__ = f"spa_{p}"
            return _h
        app.get(f"/{_r}", include_in_schema=False)(_make_handler())

    # Serve ALL static files via single catch-all handler
    # Uses explicit GET route — does NOT block WebSocket (which uses WS protocol)
    import mimetypes as _mt

    @app.get("/assets/{filepath:path}", include_in_schema=False)
    async def _serve_asset(filepath: str):
        fp = os.path.join(_assets_dir, filepath)
        if os.path.isfile(fp):
            ct = _mt.guess_type(filepath)[0] or "application/octet-stream"
            return FileResponse(fp, media_type=ct)
        return FileResponse(_index_html)

    @app.get("/chunks/{filepath:path}", include_in_schema=False)
    async def _serve_chunk(filepath: str):
        fp = os.path.join(_chunks_dir, filepath)
        if os.path.isfile(fp):
            ct = _mt.guess_type(filepath)[0] or "application/javascript"
            return FileResponse(fp, media_type=ct)
        return FileResponse(_index_html)

    # Root-level files (manifest, sw, logo, registerSW)
    @app.get("/{filename}", include_in_schema=False)
    async def _serve_root_file(filename: str):
        fp = os.path.join(_frontend_dist, filename)
        if os.path.isfile(fp):
            ct = _mt.guess_type(filename)[0] or "application/octet-stream"
            return FileResponse(fp, media_type=ct)
        return FileResponse(_index_html)

    logger.info(f"Frontend SPA served from {_frontend_dist}")
else:
    @app.get("/")
    async def root():
        return {"name": "QUANT SENTINEL Trading API", "version": "2.1.0", "docs": "/docs"}


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



