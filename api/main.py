"""
api/main.py - FastAPI application main entry point
"""

import sys
import os
import hashlib
import time as _time
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import asyncio
import json as _json
import logging
from typing import Optional

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── ERROR TRACKING (Sentry) ──────────────────────────────────────────
# Soft-enabled — only ships when SENTRY_DSN is set. Captures uncaught
# exceptions everywhere, slow transactions, and lets us emit cron
# heartbeats from the BG scanner so we get paged if the loop dies.
try:
    import sentry_sdk as _sentry
    _sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
    if _sentry_dsn:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        _sentry.init(
            dsn=_sentry_dsn,
            release=os.environ.get("SENTRY_RELEASE") or "quant-sentinel@4.0.0",
            environment=os.environ.get("SENTRY_ENV", "production"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.05")),
            profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_RATE", "0.0")),
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                HttpxIntegration(),
                AsyncioIntegration(),
            ],
            # Don't ship request bodies — they contain account state.
            send_default_pii=False,
        )
        _SENTRY_OK = True
        print(f"[sentry] enabled, env={os.environ.get('SENTRY_ENV', 'production')}", flush=True)
    else:
        _SENTRY_OK = False
except Exception as _se:  # pragma: no cover
    print(f"[sentry] disabled: {_se}", flush=True)

    class _SentryStub:
        def __getattr__(self, _name):
            def _noop(*_a, **_k):
                return None
            return _noop

    _sentry = _SentryStub()  # type: ignore
    _SENTRY_OK = False


# ── OBSERVABILITY (Logfire) ──────────────────────────────────────────
# Soft-enabled: configures unconditionally, but only ships traces when
# LOGFIRE_TOKEN is set. Without a token Logfire is a near-noop (no
# network, no overhead beyond span object creation). Run `logfire auth`
# once to populate ~/.logfire/credentials and start sending.
try:
    import logfire as _logfire
    _logfire.configure(
        send_to_logfire="if-token-present",
        service_name="quant-sentinel",
        service_version="4.0.0",
        console=False,  # set True locally to debug spans on stdout
    )
    _logfire.instrument_httpx()
    # NB: `instrument_sqlite3()` is intentionally NOT enabled — it wraps
    # every connection in a TracedConnectionProxy, and `Connection.backup()`
    # in src/core/database.py rejects proxies with TypeError. Custom spans
    # below cover the only DB hot paths we care about (scanner cycle).
    _LOGFIRE_OK = True
except Exception as _logfire_err:  # pragma: no cover
    # Logfire missing or misconfigured must never block the API. Fall back
    # to a stub that turns logfire calls into no-ops.
    print(f"[logfire] disabled: {_logfire_err}", flush=True)

    class _LogfireStub:
        def __getattr__(self, _name):
            def _noop(*_a, **_k):
                # span() returns a context manager; mimic that.
                from contextlib import nullcontext
                return nullcontext()
            return _noop

    _logfire = _LogfireStub()  # type: ignore
    _LOGFIRE_OK = False

# ── PRODUCTION HARDENING ──────────────────────────────────────────────
# Explicitly clear any backtest-mode env vars that might have leaked from
# a shell session. Production API must NEVER apply relaxed filters.
# Runs before any src.* imports.
_LEAKED_BT_FLAGS: list = []
for _bt_flag in ("QUANT_BACKTEST_MODE", "QUANT_BACKTEST_RELAX"):
    if os.environ.get(_bt_flag):
        _LEAKED_BT_FLAGS.append(_bt_flag)
        print(f"[PRODUCTION API] CRITICAL: {_bt_flag} was set, clearing for safety", flush=True)
    os.environ.pop(_bt_flag, None)
# Also clear the live SCANNER_PAUSED auto-flag if it has stale content (safety
# noop — only logs, doesn't delete; operator deletes manually).

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

    # Env-vars OK/missing report — quick visual that observability + data
    # providers are wired up. Runs once per uvicorn boot, log-only (never
    # raises). Mirrors the keys documented in .env.example.
    _env_groups: list[tuple[str, list[str]]] = [
        ("data providers", ["TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_KEY", "FRED_API_KEY", "FINNHUB_API_KEY"]),
        ("auth/security",  ["API_SECRET_KEY"]),
        ("observability",  ["LOGFIRE_TOKEN", "SENTRY_DSN"]),
        ("turso (cloud DB)", ["TURSO_URL", "TURSO_TOKEN"]),
        ("ml flags",       ["ONNX_FORCE_CPU", "DISABLE_TRAILING", "MAX_LOT_CAP"]),
    ]
    logger.info("[ENV] startup status:")
    for group_name, keys in _env_groups:
        present = [k for k in keys if os.environ.get(k, "").strip()]
        missing = [k for k in keys if not os.environ.get(k, "").strip()]
        ok_str = ", ".join(present) if present else "—"
        miss_str = ", ".join(missing) if missing else "—"
        logger.info(f"  [{group_name:18s}] OK: {ok_str:60s}  MISSING: {miss_str}")

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
    # 2026-04-25: Shadow predictor (Phase 6.1). Logs v2 ensemble decisions
    # alongside production v1 without affecting trading. Dormant until v2
    # models are trained (models/v2/xau_*_xgb_v2.json).
    shadow_task = asyncio.create_task(_shadow_scanner())
    # Health monitor (Telegram alerts on degraded state, 10-min cadence)
    try:
        from src.ops.health_monitor import health_monitor_task
        health_task = asyncio.create_task(health_monitor_task())
    except Exception as _hm_err:
        logger.warning(f"Health monitor disabled: {_hm_err}")
        health_task = None

    # Dynamic-params drift watchdog (30-min cadence). Logs writer-without-
    # reader and reader-without-writer keys so the next #95569f7-style
    # silent rename gets caught early. Always-on, very cheap.
    drift_task = asyncio.create_task(_dynamic_params_drift_watchdog())

    # Macro-snapshot persister (5-min cadence). Decoupled from trade
    # evaluation so historical regime data is captured even on scan-paused
    # cycles. Cost: ~3 TwelveData credits per cycle (XAU 1h + USDJPY 1h
    # + macro proxies via cached path) — well inside the 55/min budget.
    # Why we built it: 2026-04-27 audit found B7 efficacy can only be
    # verified by checking macro_regime at trade time, but regime was
    # never persisted. SHORT #200 forensics relied on inferring regime
    # from factors-dict presence — fragile and indirect. With snapshots
    # we get direct ground truth.
    macro_snapshot_task = asyncio.create_task(_persist_macro_snapshots())

    # Daily rejection replay. Resolves `would_have_won` on rejected_setups
    # rows that have accumulated since the last replay, using forward
    # bars from the local 5-min warehouse parquet. Zero API hits, ~15s
    # per 9k rows. Cheap, observability-only, never touches live trade
    # path. Why we built it: 2026-04-27 audit found 9k+ rejection rows
    # sitting unresolved (no resolver had been built). With this cron,
    # future factor audits get rich rejection-side data automatically.
    # Caveat: rejection within ~2 days of "now" can't be resolved until
    # the warehouse is refreshed past their hold-cap window — those
    # rows just stay NULL and get picked up on a later night.
    replay_task = asyncio.create_task(_replay_rejections_daily())

    logger.info("Background tasks started (scanner 5min | prices 5s | resolver 5min | "
                "monitor 1h | retention 24h | health 10min | params-drift 30min | "
                "macro-snapshot 5min | replay 24h)")

    yield

    # ── Graceful shutdown with drain period ──
    logger.info("Shutdown initiated — draining pending operations (30s timeout)...")

    # 1. Close all WebSocket connections gracefully
    try:
        await connection_manager.close_all()
    except Exception:
        pass

    # 2. Cancel background tasks with drain timeout
    tasks = [model_task, scanner_task, prices_task, resolver_task, monitor_task, retention_task, macro_snapshot_task, replay_task]
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


async def _persist_macro_snapshots():
    """Persist macro_regime + USDJPY z-score every 5 min into
    `macro_snapshots`. Independent of trade evaluation so historical
    regime is preserved even when no trades fire.

    All exceptions swallowed — observability must never break live.
    Cadence matches scanner (5 min) so each cycle has matching macro
    state. Initial 60s delay lets the API finish startup first.
    """
    await asyncio.sleep(60)
    while True:
        try:
            from src.core.database import NewsDB
            from src.data.data_sources import get_provider
            from src.trading.smc_engine import (
                calculate_atr, get_macro_regime, get_macro_quotes,
            )
            from src.analysis.regime import classify_regime

            provider = get_provider()
            xau_df = await asyncio.to_thread(provider.get_candles, "XAU/USD", "1h", 200)
            uj_df = await asyncio.to_thread(provider.get_candles, "USD/JPY", "1h", 100)

            usdjpy_zscore = None
            usdjpy_price = None
            macro_regime = None
            atr_ratio = None
            market_regime = None
            signals = None

            if uj_df is not None and len(uj_df) >= 20:
                uj_close = uj_df["close"].astype(float).tolist()
                usdjpy_price = float(uj_close[-1])
                # Use the same z-score window as the scanner — 20 bars.
                import numpy as _np
                window = uj_close[-20:]
                mean = float(_np.mean(window))
                std = float(_np.std(window))
                usdjpy_zscore = (usdjpy_price - mean) / std if std > 0 else 0.0

            if xau_df is not None and len(xau_df) >= 30 and uj_df is not None and len(uj_df) >= 20:
                # ATR ratio (current ATR / 20-bar mean of TR) for vol regime
                _df = xau_df.copy()
                atr = calculate_atr(_df, length=14)
                atr_mean = float(_df["tr"].rolling(20).mean().iloc[-1]) if "tr" in _df.columns else atr
                atr_ratio = (atr / atr_mean) if atr_mean else None

                regime_dict = await asyncio.to_thread(
                    get_macro_regime,
                    uj_df["close"].astype(float).tolist(),
                    usdjpy_price,
                    atr,
                    atr_mean,
                )
                if isinstance(regime_dict, dict):
                    macro_regime = regime_dict.get("regime")
                    signals = regime_dict.get("signals")

                # Market regime (squeeze / trending / ranging) from BBW + ADX
                try:
                    market_regime = str(classify_regime(xau_df))
                except Exception:
                    pass

            quotes = await asyncio.to_thread(get_macro_quotes)

            db = NewsDB()
            db.write_macro_snapshot(
                macro_regime=macro_regime,
                usdjpy_zscore=usdjpy_zscore,
                usdjpy_price=usdjpy_price,
                atr_ratio=atr_ratio,
                uup=quotes.get("uup") if quotes else None,
                tlt=quotes.get("tlt") if quotes else None,
                vixy=quotes.get("vixy") if quotes else None,
                market_regime=market_regime,
                signals=signals,
            )
        except Exception as _e:
            logger.debug(f"[macro-snapshot] tick failed: {_e}")
        await asyncio.sleep(300)  # every 5 min


async def _replay_rejections_daily():
    """Run the rejection replay script once per 24h to resolve any
    rejected_setups rows that have ground truth available in the local
    warehouse parquet.

    Uses subprocess (same pattern as walk_forward → run_production_backtest)
    so the heavy script imports happen in a child process and don't bloat
    this API process. Result is logged at INFO level; failures at DEBUG so
    they don't spam the operator log if warehouse is briefly missing.

    First run delayed 30 min after boot — gives scanner time to settle and
    avoids hitting the DB during the open-trade resolver's busy window.
    """
    import subprocess
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "replay_directional_alignment.py"
    venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
    py_exec = str(venv_py) if venv_py.exists() else sys.executable

    await asyncio.sleep(1800)   # 30-min initial delay
    while True:
        try:
            cmd = [py_exec, str(script)]
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            # Run in a thread so the asyncio loop isn't blocked for the
            # ~15-30 s the script needs.
            def _run() -> tuple[int, str, str]:
                r = subprocess.run(
                    cmd, capture_output=True, text=True, env=env,
                    cwd=str(repo_root), timeout=600,
                    encoding="utf-8", errors="replace",
                )
                return (r.returncode, r.stdout or "", r.stderr or "")
            rc, out, err = await asyncio.to_thread(_run)
            # Parse the headline "DB updated: N rows" if it landed in stdout.
            n_updated = "?"
            for line in out.splitlines():
                if "DB updated:" in line:
                    # e.g. "[replay] DB updated: 8,450 rows"
                    n_updated = line.split("DB updated:")[-1].strip().split()[0]
                    break
            if rc == 0:
                logger.info(f"[replay] daily run done — {n_updated} rows resolved")
            else:
                logger.warning(f"[replay] daily run rc={rc}; stderr tail: "
                               f"{(err or '').splitlines()[-1] if err else '<empty>'}")
        except Exception as _e:
            logger.debug(f"[replay] daily run failed: {_e}")
        # 24h until next run
        await asyncio.sleep(86400)


async def _dynamic_params_drift_watchdog():
    """
    Periodic logger of `dynamic_params` writer/reader drift.

    Catches the bug class behind #95569f7 (`target_rr` written, production
    reading `tp_to_sl_ratio`) by surfacing keys that are written within the
    last cycle but have *no* readers. Soft signal — a freshly introduced
    key may legitimately have no consumer yet, so this never raises.
    """
    # First sleep — let the scanner / queries run a few cycles so we have a
    # baseline of read activity before judging anything.
    await asyncio.sleep(900)
    while True:
        try:
            from src.core.dynamic_params_schema import find_drifts
            drifts = find_drifts(write_only_grace_s=1800.0)
            if drifts:
                # Group concise log
                wo = [d["name"] for d in drifts if d["kind"] == "write_only"]
                ro = [d["name"] for d in drifts if d["kind"] == "read_only"]
                dw = [d["name"] for d in drifts if d["kind"] == "dead_write"]
                if wo:
                    logger.warning(
                        f"🔍 [params-drift] {len(wo)} write-only keys (no reader since boot): "
                        f"{', '.join(sorted(wo)[:8])}{'…' if len(wo) > 8 else ''}"
                    )
                if dw:
                    logger.warning(
                        f"🔍 [params-drift] {len(dw)} dead-write keys (recently written, no recent read): "
                        f"{', '.join(sorted(dw)[:8])}"
                    )
                if ro and len(ro) > 0:
                    logger.info(
                        f"🔍 [params-drift] {len(ro)} read-only keys (no writer): "
                        f"{', '.join(sorted(ro)[:8])}{'…' if len(ro) > 8 else ''}"
                    )
            else:
                logger.debug("[params-drift] no drifts detected")
        except Exception as _e:
            logger.debug(f"[params-drift] watchdog tick failed: {_e}")
        await asyncio.sleep(1800)  # every 30 min


async def _background_scanner():
    """
    Background scanner: cascading multi-timeframe SMC scan every 5 minutes.
    Scalp-first cascade: 5m → 15m → 30m → 1h → 4h. Places a trade on the
    first TF with a valid setup. Lower TFs have relaxed filters (Stable
    allowed, confluence=1); H1/4h remain strict (premium SMC setups only).

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

    # Kill-switch: file-based pause. Create `data/SCANNER_PAUSED` to halt
    # trade entries without killing API. Dashboard, data fetches, and
    # open-trade resolution continue; only new entries are blocked.
    import os as _os
    _PAUSE_FLAG = _os.path.join("data", "SCANNER_PAUSED")
    # 2026-04-26: 5 → 8 after loosened-B1B4 backtest showed max-consec-losses
    # 16 over 30 days as natural variance with current scoring. Threshold 5
    # would over-pause the scanner during normal drawdowns; 8 still catches
    # genuine blow-ups but tolerates routine streaks. Recency window unchanged.
    _STREAK_THRESHOLD = 8   # auto-pause after N consecutive losses

    while True:
        if _os.path.exists(_PAUSE_FLAG):
            logger.warning(f"📡 [BG Scanner] PAUSED (flag {_PAUSE_FLAG} exists) — skipping cycle")
            await asyncio.sleep(_SCAN_INTERVAL_SEC)
            continue

        # --- Streak auto-pause (2026-04-22) ---
        # Check last N resolved trades; if >= _STREAK_THRESHOLD consecutive
        # LOSS at the head AND the oldest of those losses is within the
        # recency window, create the pause flag + Telegram alert.
        #
        # Recency window avoids re-triggering on stale pre-existing streaks
        # after a manual pause → unpause cycle. First iteration (no window)
        # re-paused immediately after unpause because the prior streak's 5
        # losses were still the newest resolved trades. 6h = intraday bleed
        # detection; an operator reviewing and unpausing won't be ambushed
        # by losses that happened before the pause.
        _STREAK_RECENCY_HOURS = 6
        try:
            import datetime as _dt
            from src.core.database import NewsDB as _StreakDB
            _sdb = _StreakDB()
            _recent = _sdb._query(
                "SELECT id, status, timestamp FROM trades WHERE status IN ('WIN','LOSS') "
                "ORDER BY id DESC LIMIT ?",
                (_STREAK_THRESHOLD,)
            )
            if _recent and len(_recent) >= _STREAK_THRESHOLD and all(
                r[1] == 'LOSS' for r in _recent
            ):
                # Check recency: oldest of the 5 losses must be within window
                _oldest_ts_str = _recent[-1][2]
                _streak_is_fresh = False
                try:
                    _oldest_ts = _dt.datetime.strptime(_oldest_ts_str, "%Y-%m-%d %H:%M:%S")
                    _age_h = (_dt.datetime.now() - _oldest_ts).total_seconds() / 3600
                    _streak_is_fresh = _age_h <= _STREAK_RECENCY_HOURS
                except (ValueError, TypeError):
                    _streak_is_fresh = False

                if _streak_is_fresh:
                    _ids = [r[0] for r in _recent]
                    _reason = (f"auto-pause {_STREAK_THRESHOLD}L streak in "
                               f"{_age_h:.1f}h (trades #{_ids[-1]}–{_ids[0]})")
                    with open(_PAUSE_FLAG, 'w') as _pf:
                        _pf.write(_reason + "\n")
                    logger.error(f"🛑 [BG Scanner] {_reason} — SCANNER_PAUSED flag created")
                    try:
                        from src.trading.scanner import send_telegram_alert as _tg
                        _tg(f"🛑 Scanner auto-paused: {_reason}. Unpause by deleting data/SCANNER_PAUSED after reviewing.")
                    except Exception as _tge:
                        logger.debug(f"Telegram alert on auto-pause failed: {_tge}")
                    await asyncio.sleep(_SCAN_INTERVAL_SEC)
                    continue
                else:
                    logger.info(
                        f"[BG Scanner] {_STREAK_THRESHOLD}L streak exists but oldest is "
                        f"{_age_h:.1f}h old (> {_STREAK_RECENCY_HOURS}h window) — treating as stale, not pausing"
                    )
        except Exception as _stk:
            logger.debug(f"Streak check failed: {_stk}")

        # ── Sentry cron heartbeat ─────────────────────────────────
        # Soft-noop without DSN. Sentry expects an in-progress check-in
        # at cycle start and a follow-up OK/ERROR with the same id at
        # cycle end. We only emit when _SENTRY_OK is True so this stays
        # zero-cost without a token.
        _sentry_checkin_id = None
        if _SENTRY_OK:
            try:
                _sentry_checkin_id = _sentry.capture_checkin(
                    monitor_slug="bg-scanner",
                    status="in_progress",
                    monitor_config={
                        "schedule": {"type": "interval", "value": 5, "unit": "minute"},
                        "checkin_margin": 2,
                        "max_runtime": 5,
                        "timezone": "UTC",
                    },
                )
            except Exception as _ce:
                logger.debug(f"sentry checkin start failed: {_ce}")

        # Metrics instrumentation — _background_scanner is the LIVE scanner
        # entry point (legacy scan_market_task is no longer wired in). Without
        # this, scan_count / scan_last_ts / scan_duration stayed at 0 even
        # though scans ran fine, breaking /api/metrics observability.
        _scan_timer_ctx = None
        try:
            from src.ops.metrics import (
                scan_duration as _sd,
                scan_last_ts as _slts,
                TimerContext as _TC,
            )
            _slts.set(_time.time())
            _scan_timer_ctx = _TC(_sd)
            _scan_timer_ctx.__enter__()
        except Exception:
            _scan_timer_ctx = None

        try:
            from src.core.database import NewsDB
            from src.api_optimizer import get_rate_limiter as _get_rl

            logger.info("📡 [BG Scanner] Starting multi-TF cascade scan (5m→15m→30m→1h→4h)...")

            # Global credit pre-check — need at least 2 credits for the first TF
            _can, _ = _get_rl().can_use_credits(2)
            if not _can:
                logger.info("📡 [BG Scanner] Credits low — skipping this cycle")
                if _scan_timer_ctx:
                    _scan_timer_ctx.__exit__(None, None, None)
                await asyncio.sleep(_SCAN_INTERVAL_SEC)
                continue

            # Prefetch all timeframes to warm cache (reduces per-TF API calls in cascade)
            with _logfire.span("scanner.prefetch_tfs", symbol="XAU/USD"):
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
                with _logfire.span(
                    "scanner.cascade_mtf",
                    portfolio_balance=portfolio_balance,
                    currency=portfolio_currency,
                ) as _cascade_span:
                    trade = await asyncio.wait_for(
                        asyncio.to_thread(cascade_mtf_scan, db, portfolio_balance, portfolio_currency),
                        timeout=120.0,  # generous — cascade may check up to 4 TFs
                    )
                    if hasattr(_cascade_span, "set_attribute"):
                        _cascade_span.set_attribute("trade_found", bool(trade))
                        if trade:
                            _cascade_span.set_attribute("tf", trade.get("tf_label", "?"))
                            _cascade_span.set_attribute("direction", trade.get("direction", "?"))
            except asyncio.TimeoutError:
                logger.warning("📡 [BG Scanner] MTF cascade timed out (120s)")
                try:
                    from src.ops.metrics import scan_errors_total as _set
                    _set.inc()
                except Exception:
                    pass
                if _scan_timer_ctx:
                    _scan_timer_ctx.__exit__(None, None, None)
                    _scan_timer_ctx = None
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
                    # Backfill setup_grade + score (was always None before)
                    sq = trade.get('setup_quality')
                    if sq and sq.get('grade'):
                        try:
                            latest = db._query_one(
                                "SELECT id FROM trades ORDER BY id DESC LIMIT 1"
                            )
                            if latest:
                                db.update_trade_setup_grade(
                                    latest[0], sq['grade'], sq.get('score', 0)
                                )
                        except Exception:
                            pass

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
            if _scan_timer_ctx:
                _scan_timer_ctx.__exit__(None, None, None)
            # Don't emit Sentry checkin on cancel — it's a clean shutdown.
            return
        except Exception as e:
            # Log ERROR with traceback so silent death is visible. Loop keeps
            # running — one bad cycle shouldn't kill the whole scanner.
            logger.error(f"📡 [BG Scanner] Error in cycle: {e}", exc_info=True)
            try:
                from src.ops.metrics import scan_errors_total as _set
                _set.inc()
            except Exception:
                pass
            # Sentry: cycle-end checkin = ERROR. Captures the exception too.
            if _SENTRY_OK and _sentry_checkin_id:
                try:
                    _sentry.capture_checkin(
                        monitor_slug="bg-scanner",
                        status="error",
                        check_in_id=_sentry_checkin_id,
                    )
                    _sentry.capture_exception(e)
                except Exception:
                    pass
        else:
            # Sentry: clean cycle end → OK checkin closes the in-progress one.
            if _SENTRY_OK and _sentry_checkin_id:
                try:
                    _sentry.capture_checkin(
                        monitor_slug="bg-scanner",
                        status="ok",
                        check_in_id=_sentry_checkin_id,
                    )
                except Exception:
                    pass

        # Close timer for this cycle (populates scan_duration histogram →
        # drives scan_count, scan_avg_ms, scan_p95_ms metrics).
        if _scan_timer_ctx:
            try:
                _scan_timer_ctx.__exit__(None, None, None)
            except Exception:
                pass

        # Wait until next scan cycle
        await asyncio.sleep(_SCAN_INTERVAL_SEC)


async def _shadow_scanner():
    """
    Shadow ensemble — logs v2 predictions next to live v1 trading.

    Runs every 5 minutes (same cadence as production scanner). Fetches
    its own data so it doesn't share state with the production scanner.
    Writes to data/shadow_predictions.jsonl. Dormant until v2 models
    exist in models/v2/.
    """
    import os as _os
    SHADOW_INTERVAL_SEC = 300
    # Wait 60s after startup so production scanner gets first run
    await asyncio.sleep(60)
    logger.info("📡 [Shadow Scanner] starting (every 300s)")
    while True:
        try:
            # Skip if v2 models not yet trained (avoid wasted data fetches)
            if not _os.path.exists("models/v2/xau_long_xgb_v2.json") \
               and not _os.path.exists("models/v2/xau_short_xgb_v2.json"):
                # Slow polling when dormant
                await asyncio.sleep(SHADOW_INTERVAL_SEC * 4)
                continue

            from src.data.data_provider import DataProvider
            dp = DataProvider()
            df = dp.fetch_ohlcv("XAU/USD", interval="5m", limit=200)
            if df is None or len(df) < 50:
                await asyncio.sleep(SHADOW_INTERVAL_SEC)
                continue

            from src.learning.shadow_predictor import shadow_predict
            shadow_predict(df, tf="5m", v1_signal="UNKNOWN")
        except asyncio.CancelledError:
            logger.info("📡 [Shadow Scanner] cancelled")
            return
        except Exception as e:
            logger.debug(f"[Shadow Scanner] non-fatal error: {e}")
        await asyncio.sleep(SHADOW_INTERVAL_SEC)


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


def _apply_voter_attribution(db, trade_id, status, direction):
    """Update ensemble voter weights based on the resolved trade outcome.

    Extracted from the SL/TP branch (D.1, commit 6fa1bd5) so all three
    resolution paths (SL/TP, time-exit, pre-weekend close) share one
    weight-update mechanism. Without this, time-exit and pre-weekend
    closes silently skipped the self-learning loop — biased voter
    weights toward whatever resolves via SL/TP.

    `long_was_winning` translates outcome to "did the LONG bet succeed"
    so voter raw P(LONG wins) predictions can be compared:
        correct iff (pred > 0.5) == long_was_winning
    """
    try:
        from src.ml.ensemble_models import update_ensemble_weights
        pred_row = db._query_one(
            "SELECT lstm_pred, xgb_pred, smc_pred, "
            "attention_pred, deeptrans_pred, v2_xgb_pred, dqn_action "
            "FROM ml_predictions WHERE trade_id=? "
            "ORDER BY id DESC LIMIT 1",
            (trade_id,),
        )
        if not pred_row:
            return  # no prediction matched — early prod trades, missing data
        long_was_winning = (
            (status == "WIN" and direction == "LONG")
            or (status == "LOSS" and direction == "SHORT")
        )
        # Probabilistic voters (value > 0.5 = LONG vote)
        prob_voters = ("lstm", "xgb", "smc", "attention", "deeptrans", "v2_xgb")
        correct, incorrect = [], []
        for name, pval in zip(prob_voters, pred_row[:6]):
            if pval is None:
                continue
            voted_long = float(pval) > 0.5
            (correct if voted_long == long_was_winning else incorrect).append(name)
        # DQN: integer action 0=HOLD, 1=BUY/LONG, 2=SELL/SHORT.
        # Only attribute when DQN actually voted (skip HOLD).
        # 2026-05-02 audit fix: DQN was previously frozen at init weight
        # because it was excluded from the voters tuple — same root-cause
        # as muted-voter persistence bug (commit 1a253cf).
        dqn_action = pred_row[6] if len(pred_row) > 6 else None
        if dqn_action is not None:
            try:
                action_int = int(dqn_action)
            except (ValueError, TypeError):
                action_int = 0
            if action_int == 1:    # BUY → LONG vote
                voted_long = True
                voted = True
            elif action_int == 2:  # SELL → SHORT vote
                voted_long = False
                voted = True
            else:                  # HOLD → no vote, no attribution
                voted = False
            if voted:
                (correct if voted_long == long_was_winning else incorrect).append("dqn")
        if correct or incorrect:
            update_ensemble_weights(
                correct_models=correct,
                incorrect_models=incorrect,
                learning_rate=0.02,
            )
            logger.debug(
                f"[Resolver] #{trade_id} voter weight update — "
                f"correct={correct} incorrect={incorrect}"
            )
    except Exception as _w_err:
        logger.debug(
            f"[Resolver] ensemble weight update skipped for #{trade_id}: {_w_err}"
        )


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

            # Weekend guard — XAU/USD is closed Fri 22:00 UTC through
            # Sun 22:00 UTC. Skip entire resolution cycle during that
            # window to save data-provider credits. Open trades just
            # wait; Monday open will resolve them on the first tick.
            import datetime as _dt
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            wday = now_utc.weekday()  # Mon=0 .. Sun=6
            hour = now_utc.hour
            is_weekend = (
                (wday == 4 and hour >= 22) or      # Fri >= 22:00 UTC
                (wday == 5) or                     # all Sat
                (wday == 6 and hour < 22)          # Sun < 22:00 UTC
            )
            if is_weekend:
                logger.debug("[Resolver] weekend — skipping cycle")
                await asyncio.sleep(1800)  # 30 min sleep during weekend
                continue

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
                "SELECT id, direction, entry, sl, tp, trailing_sl, lot FROM trades WHERE status IN ('PROPOSED', 'OPEN')"
            )

            resolved = 0
            for row in open_trades:
                trade_id, direction, entry, sl, tp, trailing_sl, lot = row
                # Apply 5-level trailing stop BEFORE checking SL/TP hit. Without
                # this, trades got pure binary outcomes (full SL distance lost
                # on every reversal). Now: 1.0R → BE, 1.5R → lock 0.75R,
                # 2.0R → lock 1.25R, 2.5R+ → ATR trail. Updates trailing_sl
                # column; subsequent SL hit check uses the trailed level.
                #
                # 2026-04-26: gated behind DISABLE_TRAILING env var. Backtest
                # showed trailing was cutting LONG winners at BE before TP
                # (LONG pnl flipped −$14 → +$7 with trailing off, PF +0.13).
                # Set DISABLE_TRAILING=1 in .env to skip trailing entirely
                # — trades exit only at TP/SL or via time-exit. Reversible.
                if os.environ.get("DISABLE_TRAILING") != "1":
                    try:
                        from src.trading.scanner import apply_trailing_stop
                        if apply_trailing_stop(db, (trade_id, direction, entry, sl, tp, trailing_sl),
                                               current_price):
                            # Reload SL after trailing update
                            new_sl_row = db._query_one(
                                "SELECT trailing_sl, sl FROM trades WHERE id=?", (trade_id,)
                            )
                            if new_sl_row:
                                sl = new_sl_row[0] or new_sl_row[1] or sl
                    except Exception as _trail_err:
                        logger.debug(f"[Resolver] trailing skipped for #{trade_id}: {_trail_err}")

                try:
                    entry_f = float(entry or 0)
                    sl_f = float(sl or 0)
                    tp_f = float(tp or 0)
                    lot_f = float(lot or 0.01)

                    # ── Pre-weekend close: close all positions 30min before
                    #    weekend close (Friday 20:00 UTC / 22:00 CEST) to avoid
                    #    gap risk. Gold Sunday opens can gap 0.5-2%.
                    try:
                        from datetime import datetime as _dt_wk, timezone as _tz_wk
                        _now_wk = _dt_wk.now(_tz_wk.utc)
                        # Friday = weekday 4. Close window: Friday 19:30-20:00 UTC
                        if _now_wk.weekday() == 4 and _now_wk.hour >= 19 and _now_wk.minute >= 30:
                            OZ_WK = 100.0
                            lot_wk = float(lot or 0.01)
                            if direction and "LONG" in str(direction).upper():
                                pnl_wk = round((current_price - entry_f) * OZ_WK * lot_wk, 2)
                            else:
                                pnl_wk = round((entry_f - current_price) * OZ_WK * lot_wk, 2)
                            status_wk = "WIN" if pnl_wk > 0 else "LOSS"
                            db._execute(
                                "UPDATE trades SET status=?, profit=? WHERE id=?",
                                (status_wk, pnl_wk, trade_id),
                            )
                            logger.info(
                                f"🏁 [Resolver] #{trade_id} PRE-WEEKEND CLOSE "
                                f"→ {status_wk} {pnl_wk:+.2f} (Friday 19:30+ UTC)"
                            )
                            try:
                                cur_bal = float(db.get_param("portfolio_balance") or 10000)
                                db.set_param("portfolio_balance", round(cur_bal + pnl_wk, 2))
                                db.set_param("portfolio_equity", round(cur_bal + pnl_wk, 2))
                            except Exception:
                                pass
                            # D.1 extension: also update voter weights on
                            # pre-weekend closes. Without this, weekend
                            # resolutions silently skip self-learning.
                            _apply_voter_attribution(db, trade_id, status_wk, direction)
                            resolved += 1
                            continue
                    except Exception as _wk_err:
                        logger.debug(f"[Resolver] weekend check skipped: {_wk_err}")

                    # ── Time-based exit: scalp trades (5m/15m/30m) that hold
                    #    longer than MAX_SCALP_HOLD_HOURS get closed at market.
                    #    Trade #161 held 13h → LOSS on a "scalp" — capital was
                    #    locked when it should have exited at breakeven or small
                    #    loss hours earlier. H1/4h trades get longer leash.
                    MAX_SCALP_HOLD_HOURS = 4.0
                    MAX_SWING_HOLD_HOURS = 48.0
                    try:
                        from datetime import datetime as _dt_cls, timezone as _tz
                        trade_row = db._query_one(
                            "SELECT timestamp, pattern FROM trades WHERE id=?",
                            (trade_id,),
                        )
                        if trade_row and trade_row[0]:
                            opened = _dt_cls.strptime(trade_row[0], "%Y-%m-%d %H:%M:%S")
                            opened = opened.replace(tzinfo=_tz.utc)
                            age_h = (_dt_cls.now(_tz.utc) - opened).total_seconds() / 3600
                            pat = str(trade_row[1] or "")
                            is_scalp_tf = any(t in pat for t in ("[M5]", "[M15]", "[M30]"))
                            max_hold = MAX_SCALP_HOLD_HOURS if is_scalp_tf else MAX_SWING_HOLD_HOURS
                            if age_h > max_hold:
                                OZ = 100.0
                                if direction and "LONG" in str(direction).upper():
                                    pnl = round((current_price - entry_f) * OZ * lot_f, 2)
                                else:
                                    pnl = round((entry_f - current_price) * OZ * lot_f, 2)
                                status_label = "WIN" if pnl > 0 else "LOSS"
                                db._execute(
                                    "UPDATE trades SET status=?, profit=? WHERE id=?",
                                    (status_label, pnl, trade_id),
                                )
                                logger.info(
                                    f"⏰ [Resolver] #{trade_id} TIME EXIT after {age_h:.1f}h "
                                    f"(max {max_hold}h for {'scalp' if is_scalp_tf else 'swing'}) "
                                    f"→ {status_label} {pnl:+.2f}"
                                )
                                try:
                                    cur_bal = float(db.get_param("portfolio_balance") or 10000)
                                    cur_pnl = float(db.get_param("portfolio_pnl") or 0)
                                    db.set_param("portfolio_balance", round(cur_bal + pnl, 2))
                                    db.set_param("portfolio_equity", round(cur_bal + pnl, 2))
                                    db.set_param("portfolio_pnl", round(cur_pnl + pnl, 2))
                                except Exception:
                                    pass
                                # D.1 extension: voter weight update on
                                # time-exit closes (was silently skipped).
                                _apply_voter_attribution(db, trade_id, status_label, direction)
                                resolved += 1
                                continue
                    except Exception as _time_err:
                        logger.debug(f"[Resolver] time-exit check skipped for #{trade_id}: {_time_err}")

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
                        # XAU contract: standard lot = 100 oz, so $ PnL per
                        # trade = price_move * 100 * lot. Without the lot
                        # multiplier, a 1.0 lot win of $30 price move would
                        # record as $30 instead of $3000. Micro-lots happen
                        # to match because lot=0.01 * 100 = 1.
                        lot_f = float(lot or 0.01)
                        OZ_PER_STANDARD_LOT = 100.0
                        if hit_tp:
                            pnl = round(abs(tp_f - entry_f) * OZ_PER_STANDARD_LOT * lot_f, 2)
                        else:
                            pnl = round(-abs(entry_f - sl_f) * OZ_PER_STANDARD_LOT * lot_f, 2)
                        if entry_f <= 0:
                            pnl = 0
                        db._execute(
                            "UPDATE trades SET status=?, profit=? WHERE id=?",
                            (status, pnl, trade_id),
                        )

                        # Auto-update portfolio aggregates so sizing adapts to
                        # drawdown/profit over time (previously balance stayed
                        # at $10000 forever, scanner sized based on stale value).
                        try:
                            import json as _json
                            from datetime import datetime as _dt, timezone as _tz
                            cur_balance = float(db.get_param("portfolio_balance") or 10000)
                            cur_pnl = float(db.get_param("portfolio_pnl") or 0)
                            new_balance = round(cur_balance + pnl, 2)
                            new_pnl = round(cur_pnl + pnl, 2)
                            db.set_param("portfolio_balance", new_balance)
                            db.set_param("portfolio_equity", new_balance)
                            db.set_param("portfolio_pnl", new_pnl)
                            # Balance milestone alerts via Telegram
                            initial_bal = float(db.get_param("portfolio_initial_balance") or 10000)
                            if initial_bal > 0:
                                pnl_pct = (new_balance - initial_bal) / initial_bal * 100
                                milestones = [(-10, "DD -10%"), (-5, "DD -5%"),
                                              (5, "+5%"), (10, "+10%"), (20, "+20%")]
                                prev_pct = (cur_balance - initial_bal) / initial_bal * 100
                                for threshold, label in milestones:
                                    crossed = (prev_pct < threshold <= pnl_pct) or \
                                              (prev_pct > threshold >= pnl_pct)
                                    if crossed:
                                        try:
                                            from src.trading.scanner import send_telegram_alert
                                            send_telegram_alert(
                                                f"{'🟢' if threshold > 0 else '🔴'} *MILESTONE: {label}*\n"
                                                f"Balance: ${new_balance:,.2f}\n"
                                                f"PnL: {pnl_pct:+.1f}% from ${initial_bal:,.0f}"
                                            )
                                        except Exception:
                                            pass
                            # Append to portfolio_history (JSON in param_text).
                            # Keeps last 500 datapoints so the equity curve
                            # widget has real data. Each point = {ts, balance,
                            # pnl, trade_id, delta}.
                            try:
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
                                    "ts": _dt.now(_tz.utc).isoformat(),
                                    "balance": new_balance,
                                    "pnl": new_pnl,
                                    "trade_id": trade_id,
                                    "delta": pnl,
                                })
                                # Cap to 500 entries (~1-2 years of trades)
                                if len(hist) > 500:
                                    hist = hist[-500:]
                                db.set_param("portfolio_history", _json.dumps(hist))
                            except Exception as _hist_err:
                                logger.debug(f"[Resolver] history append skipped for #{trade_id}: {_hist_err}")
                        except Exception as _pfu:
                            logger.debug(f"[Resolver] portfolio update skipped for #{trade_id}: {_pfu}")

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

                        # Wire ensemble voter weights to the resolver event
                        # (P1.5 + D.1 extension 2026-04-30). Helper lives at
                        # module level so all 3 resolve paths (SL/TP,
                        # time-exit, pre-weekend) share it.
                        _apply_voter_attribution(db, trade_id, status, direction)

                        icon = "✅" if hit_tp else "❌"
                        target = f"TP:{tp_f}" if hit_tp else f"SL:{sl_f}"
                        logger.info(f"{icon} [Resolver] Trade #{trade_id} {status} @ ${current_price:.2f} ({target})")
                except Exception as e:
                    logger.debug(f"[Resolver] Trade #{trade_id} error: {e}")

            if resolved > 0:
                logger.info(f"📊 [Resolver] Resolved {resolved}/{len(open_trades)} trades @ ${current_price:.2f}")

            # Logfire structured event so the resolver loop is searchable
            # by the operator alongside scanner spans. Attrs end up as
            # filterable columns in the dashboard.
            try:
                _logfire.info(
                    "resolver.cycle.done",
                    open_count=len(open_trades),
                    trades_resolved=resolved,
                    spot_price=float(current_price),
                )
            except Exception:
                pass

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[Resolver] Error: {e}")
            try:
                _logfire.exception("resolver.cycle.failed")
            except Exception:
                pass

        await asyncio.sleep(300)  # Every 5 minutes


# Create FastAPI app
app = FastAPI(
    title="QUANT SENTINEL Trading API",
    description="Professional trading platform API with ML models",
    version="2.1.0",
    lifespan=lifespan
)

# Wire Logfire request/response auto-traces. Excluded URLs keep the
# trace stream readable — health and SSE generate massive noise.
if _LOGFIRE_OK:
    try:
        _logfire.instrument_fastapi(
            app,
            capture_headers=False,
            excluded_urls=r"/api/health|/api/sse/.*",
        )
    except Exception as _le:
        logging.getLogger("logfire").warning(f"FastAPI instrumentation failed: {_le}")

# Middleware — custom auth/rate use pure ASGI wrappers that bypass WebSocket
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.jwt_auth import JwtAuthMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.middleware.slow_request import SlowRequestMiddleware
app.add_middleware(JwtAuthMiddleware)
app.add_middleware(RateLimitMiddleware)
# Slow-request observer — logs a WARN on requests over SLOW_REQUEST_MS.
# Sits BEFORE Request ID so its log line still has the id.
app.add_middleware(SlowRequestMiddleware)
# Request ID — must be outermost so IDs are on every response
app.add_middleware(RequestIDMiddleware)
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
from api.routers import scanner as _scanner_router
app.include_router(_scanner_router.router, prefix="/api/scanner", tags=["Scanner Control"])
from api.routers import params as _params_router
app.include_router(_params_router.router, prefix="/api/params", tags=["Dynamic Params"])
from api.routers import grid as _grid_router
app.include_router(_grid_router.router, prefix="/api/grid", tags=["Grid Backtest"])
from api.routers import system as _system_router
app.include_router(_system_router.router, prefix="/api/system", tags=["System Info"])


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


# NOTE: a second `/api/health/detailed` definition was registered here
# (2026-04-24 dead-code audit removed it). FastAPI silently picks the
# first registration, so the inline version at this location was dead
# code. The canonical definition at line ~1160 delegates to
# `src.ops.monitoring.get_system_health()` which is the more
# comprehensive check. If you need the inline fields (websocket_clients,
# database table count), add them to `get_system_health()` instead.


@app.get("/metrics", tags=["System"], response_class=Response)
async def prometheus_metrics():
    """Prometheus text exposition format. Scrape from /metrics.

    Compatible with:
      - Prometheus (scrape_configs jobs)
      - Grafana Cloud Agent
      - Uptime Kuma
      - VictoriaMetrics
    """
    from src.ops.metrics import to_prometheus_text
    return Response(content=to_prometheus_text(), media_type="text/plain; version=0.0.4")


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


@app.get("/api/backtest/grids", tags=["System"])
async def backtest_grids(limit: int = 20):
    """List available grid-sweep result files.

    Grid sweeps are produced by run_backtest_grid.py and saved as JSON
    arrays of {params, stats} entries. Each file represents a single
    systematic parameter search — this endpoint surfaces metadata so the UI
    can offer them in a selector without loading full payloads.
    """
    import os as _os
    import glob as _glob
    import json as _json

    files = sorted(
        _glob.glob("reports/*grid*.json"),
        key=lambda f: _os.path.getmtime(f),
        reverse=True,
    )[:limit]

    grids = []
    for path in files:
        try:
            data = _json.loads(open(path, "r", encoding="utf-8").read())
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        ranked = [e for e in data if isinstance(e, dict) and "stats" in e]
        grids.append({
            "path": path,
            "name": _os.path.basename(path).replace(".json", ""),
            "mtime": _os.path.getmtime(path),
            "combos": len(ranked),
            "best_sharpe": max((e["stats"].get("sharpe") or 0 for e in ranked), default=0),
        })
    return {"count": len(grids), "grids": grids}


@app.get("/api/backtest/grid", tags=["System"])
async def backtest_grid(name: str):
    """Full grid data for a named file. Path-traversal safe (basename only)."""
    import os as _os
    import json as _json
    from fastapi import HTTPException

    safe_name = _os.path.basename(name).replace(".json", "")
    path = f"reports/{safe_name}.json"
    if not _os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Grid '{safe_name}' not found")
    try:
        data = _json.loads(open(path, "r", encoding="utf-8").read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read failed: {e}")
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Not a grid-format file")
    return {"path": path, "mtime": _os.path.getmtime(path), "entries": data}


_VOTER_ACCURACY_CACHE: dict = {}
_VOTER_ACCURACY_TTL_SEC = 600  # 10-min cache; yfinance fetch is expensive


_REPLAY_CACHE: dict = {}
_REPLAY_TTL_SEC = 600


@app.get("/api/replay-analyzer", tags=["System"])
async def replay_analyzer_endpoint(hours: int = 24, horizon_bars: int = 24,
                                   target_pct: float = 0.1):
    """Runs the offline replay_analyzer.py logic and returns per-filter
    'what-if' verdict JSON for the dashboard. Cached 10min server-side.
    Answers: which filters are rejecting trades that would have been
    profitable?
    """
    import time as _time
    from collections import Counter, defaultdict
    import pandas as pd

    cache_key = (int(hours), int(horizon_bars), round(float(target_pct), 3))
    now = _time.time()
    cached = _REPLAY_CACHE.get(cache_key)
    if cached and (now - cached["ts"]) < _REPLAY_TTL_SEC:
        payload = dict(cached["payload"])
        payload["cached"] = True
        payload["cache_age_sec"] = round(now - cached["ts"], 1)
        return payload

    from src.core.database import NewsDB
    from src.data.data_sources import get_provider
    db = NewsDB()
    try:
        df = get_provider().get_candles("XAU/USD", "5m", 2016)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"live fetch failed: {e}")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="no candle data")
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.columns = [str(c).lower() for c in df.columns]

    since = f"-{int(hours)} hours"
    rows = db._query(
        "SELECT timestamp, timeframe, direction, price, rejection_reason, filter_name "
        "FROM rejected_setups WHERE timestamp >= datetime('now', ?) ORDER BY timestamp",
        (since,),
    )
    by_filter: dict = defaultdict(lambda: Counter())
    outcomes: dict = defaultdict(
        lambda: {"win": 0, "loss": 0, "flat": 0, "n": 0, "total_pnl_pct": 0.0}
    )

    for row in rows:
        ts_str, _tf, direction, price, _reason, fname = row
        by_filter[fname]["total"] += 1
        if not price or not direction:
            continue
        ts = pd.Timestamp(ts_str)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        mask = df.index >= ts
        if not mask.any():
            continue
        idx_from = df.index[mask][0]
        future = df.index[df.index > idx_from][:horizon_bars]
        if len(future) < horizon_bars:
            continue
        try:
            entry = float(price)
            high = float(df.loc[future, "high"].max())
            low = float(df.loc[future, "low"].min())
        except Exception:
            continue
        if direction == "LONG":
            max_gain = (high - entry) / entry * 100
            max_loss = (low - entry) / entry * 100
        else:
            max_gain = (entry - low) / entry * 100
            max_loss = (entry - high) / entry * 100
        outcomes[fname]["n"] += 1
        if max_gain >= target_pct:
            outcomes[fname]["win"] += 1
            outcomes[fname]["total_pnl_pct"] += target_pct
        elif max_loss <= -target_pct:
            outcomes[fname]["loss"] += 1
            outcomes[fname]["total_pnl_pct"] -= target_pct
        else:
            outcomes[fname]["flat"] += 1

    total = sum(c["total"] for c in by_filter.values())
    filters = []
    for fname, ct in sorted(by_filter.items(), key=lambda x: -x[1]["total"]):
        n = ct["total"]
        out = outcomes.get(fname, {"n": 0, "win": 0, "total_pnl_pct": 0})
        n_outcome = out["n"]
        if n_outcome > 0:
            wr = out["win"] / n_outcome * 100
            expectancy = out["total_pnl_pct"] / n_outcome
            verdict = ("should_accept" if wr > 55 and expectancy > 0
                       else "borderline" if wr > 45
                       else "correct_reject")
            filters.append({
                "name": fname,
                "rejected": n,
                "share_pct": round(n / total * 100, 1) if total else 0,
                "hypothetical_wr_pct": round(wr, 1),
                "expectancy_pct": round(expectancy, 3),
                "sample_size": n_outcome,
                "verdict": verdict,
            })
        else:
            filters.append({
                "name": fname,
                "rejected": n,
                "share_pct": round(n / total * 100, 1) if total else 0,
                "hypothetical_wr_pct": None,
                "expectancy_pct": None,
                "sample_size": 0,
                "verdict": "insufficient",
            })

    payload = {
        "hours": hours,
        "horizon_bars": horizon_bars,
        "horizon_label": f"{horizon_bars * 5}min",
        "target_pct": target_pct,
        "total_rejected": total,
        "filters": filters,
        "cached": False,
        "cache_age_sec": 0,
    }
    _REPLAY_CACHE[cache_key] = {"ts": now, "payload": payload}
    return payload


@app.get("/api/trades/per-tf", tags=["System"])
async def trades_per_tf():
    """Win rate and P&L breakdown by timeframe (M5/M15/M30/H1/H4)."""
    from src.core.database import NewsDB
    db = NewsDB()
    rows = db._query("""SELECT
        CASE
            WHEN pattern LIKE '[M5]%' THEN 'M5'
            WHEN pattern LIKE '[M15]%' THEN 'M15'
            WHEN pattern LIKE '[M30]%' THEN 'M30'
            WHEN pattern LIKE '[H1]%' THEN 'H1'
            WHEN pattern LIKE '[H4]%' THEN 'H4'
            ELSE 'other'
        END AS tf,
        COUNT(*), SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN profit<0 THEN 1 ELSE 0 END),
        ROUND(SUM(profit), 2), ROUND(AVG(profit), 2)
    FROM trades WHERE status IN ('WIN','LOSS','PROFIT','CLOSED')
        AND profit IS NOT NULL
    GROUP BY tf ORDER BY COUNT(*) DESC""")
    return {
        "timeframes": [
            {
                "tf": r[0], "trades": r[1], "wins": r[2], "losses": r[3],
                "win_rate_pct": round(r[2] / r[1] * 100, 1) if r[1] else 0,
                "net_pnl": r[4], "avg_pnl": r[5],
            }
            for r in (rows or [])
        ]
    }


@app.get("/api/trades/recent-streak", tags=["System"])
async def trades_recent_streak(n: int = 10):
    """Last N resolved trades as win/loss streak with PnL deltas."""
    from src.core.database import NewsDB
    db = NewsDB()
    rows = db._query(
        "SELECT id, timestamp, direction, entry, status, profit, pattern "
        "FROM trades WHERE status IN ('WIN','LOSS','PROFIT','CLOSED') "
        "AND profit IS NOT NULL ORDER BY id DESC LIMIT ?",
        (int(n),),
    )
    trades = []
    for r in (rows or []):
        trades.append({
            "id": r[0], "timestamp": r[1], "direction": r[2],
            "entry": r[3], "outcome": "win" if float(r[5] or 0) > 0 else "loss",
            "profit": r[5], "pattern": r[6],
        })
    trades.reverse()
    streak = 0
    for t in reversed(trades):
        if t["outcome"] == ("win" if streak >= 0 else "loss"):
            streak += 1 if t["outcome"] == "win" else -1
        else:
            break
    return {
        "trades": trades,
        "current_streak": streak,
        "streak_label": f"{abs(streak)}{'W' if streak > 0 else 'L'}" if streak else "0",
    }


@app.get("/api/trades/per-session", tags=["System"])
async def trades_per_session():
    """Win rate and P&L breakdown by trading session."""
    from src.core.database import NewsDB
    db = NewsDB()
    rows = db._query("""SELECT
        COALESCE(session, 'unknown') AS sess,
        COUNT(*), SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN profit<0 THEN 1 ELSE 0 END),
        ROUND(SUM(profit), 2), ROUND(AVG(profit), 2)
    FROM trades WHERE status IN ('WIN','LOSS','PROFIT','CLOSED')
        AND profit IS NOT NULL
    GROUP BY sess ORDER BY COUNT(*) DESC""")
    return {
        "sessions": [
            {
                "session": r[0], "trades": r[1], "wins": r[2], "losses": r[3],
                "win_rate_pct": round(r[2] / r[1] * 100, 1) if r[1] else 0,
                "net_pnl": r[4], "avg_pnl": r[5],
            }
            for r in (rows or [])
        ]
    }


@app.get("/api/daily-digest", tags=["System"])
async def daily_digest_preview(hours: int = 24):
    """Lightweight in-process digest (same content as scripts/daily_digest.py
    but returned as JSON for the dashboard widget)."""
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from scripts.daily_digest import build_digest
    try:
        text = build_digest(hours=int(hours))
        return {"text": text, "hours": hours}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/voter-live-accuracy", tags=["System"])
async def voter_live_accuracy(hours: int = 72, horizon_candles: int = 12):
    """Live forward-move accuracy per ensemble voter.

    For each ml_predictions row within the last `hours`, joins its
    timestamp to a 5m yfinance candle, then compares the prediction
    to the actual close `horizon_candles` ahead (default 12 = 1h).
    Returns per-voter accuracy among decisive predictions.

    Motivation: 2026-04-16 discovered the live LSTM was an anti-signal
    (25% accuracy) despite passing sweep validation. This endpoint is
    the runtime early-warning: anything below 45% fires a warning.
    """
    import pandas as pd
    import time as _time
    from collections import Counter
    from src.core.database import NewsDB

    # Cache hit check: same params + fresh
    cache_key = (int(hours), int(horizon_candles))
    now = _time.time()
    cached = _VOTER_ACCURACY_CACHE.get(cache_key)
    if cached and (now - cached["ts"]) < _VOTER_ACCURACY_TTL_SEC:
        payload = dict(cached["payload"])
        payload["cache_age_sec"] = round(now - cached["ts"], 1)
        payload["cached"] = True
        return payload

    db = NewsDB()

    # Use the same live data provider the scanner uses (cached, fast)
    # rather than yfinance (slow external fetch every cache miss).
    try:
        from src.data.data_sources import get_provider
        provider = get_provider()
        df = provider.get_candles("XAU/USD", "5m", 2016)  # ~7d of 5m bars
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"live data fetch failed: {e}")
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="no live candle data available")

    # Normalize to expected shape
    if "timestamp" in df.columns:
        df = df.set_index("timestamp")
    df.columns = [c.lower() if isinstance(c, str) else str(c).lower() for c in df.columns]
    if df.index.tz is None:
        df.index = pd.to_datetime(df.index).tz_localize("UTC")
    if "close" not in df.columns:
        raise HTTPException(status_code=500, detail=f"provider returned unexpected columns: {list(df.columns)}")

    since = f"-{int(hours)} hours"

    def _eval(col, high_thr, low_thr, is_action=False):
        cats = Counter()
        rows = db._query(
            f"SELECT timestamp, {col} FROM ml_predictions "
            f"WHERE {col} IS NOT NULL AND timestamp >= datetime('now', ?) "
            f"ORDER BY timestamp",
            (since,),
        )
        for ts_str, raw in rows:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            ts = pd.Timestamp(ts_str)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            mask = df.index >= ts
            if not mask.any():
                continue
            idx = df.index[mask][0]
            future = df.index[df.index > idx][:horizon_candles]
            if len(future) < horizon_candles:
                continue
            entry = float(df.loc[idx, "close"])
            end = float(df.loc[future[-1], "close"])
            move = (end - entry) / entry * 100
            up = move > 0.1
            down = move < -0.1
            if is_action:
                # DQN: 1=BUY, 2=SELL, 0=HOLD
                if val == 1:
                    cats["bull_correct" if up else "bull_wrong" if down else "bull_flat"] += 1
                elif val == 2:
                    cats["bear_correct" if down else "bear_wrong" if up else "bear_flat"] += 1
            else:
                if val > high_thr:
                    cats["bull_correct" if up else "bull_wrong" if down else "bull_flat"] += 1
                elif val < low_thr:
                    cats["bear_correct" if down else "bear_wrong" if up else "bear_flat"] += 1
        bc, bw = cats.get("bull_correct", 0), cats.get("bull_wrong", 0)
        sc, sw = cats.get("bear_correct", 0), cats.get("bear_wrong", 0)
        total_c, total_w = bc + sc, bw + sw
        acc = (total_c / (total_c + total_w) * 100) if (total_c + total_w) else None
        bull_acc = (bc / (bc + bw) * 100) if (bc + bw) else None
        bear_acc = (sc / (sc + sw) * 100) if (sc + sw) else None
        status = "insufficient" if (total_c + total_w) < 10 else (
            "good" if acc and acc >= 55 else "weak" if acc and acc >= 45 else "anti_signal"
        )
        return {
            "decisive_samples": total_c + total_w,
            "combined_accuracy_pct": round(acc, 1) if acc is not None else None,
            "bullish_accuracy_pct": round(bull_acc, 1) if bull_acc is not None else None,
            "bearish_accuracy_pct": round(bear_acc, 1) if bear_acc is not None else None,
            "status": status,
        }

    voters = {
        "smc": _eval("smc_pred", 0.7, 0.3),
        "lstm": _eval("lstm_pred", 0.7, 0.3),
        "xgb": _eval("xgb_pred", 0.7, 0.3),
        "attention": _eval("attention_pred", 0.7, 0.3),
        "dqn": _eval("dqn_action", 0.5, -0.5, is_action=True),
        "ensemble": _eval("ensemble_score", 0.7, 0.3),
    }

    alerts = [name for name, v in voters.items()
              if v["status"] == "anti_signal"]
    warnings = [name for name, v in voters.items()
                if v["status"] == "weak"]

    payload = {
        "hours_window": hours,
        "horizon_candles": horizon_candles,
        "horizon_label": f"{horizon_candles * 5}min",
        "voters": voters,
        "alerts": alerts,
        "warnings": warnings,
        "verdict": "critical" if alerts else "warn" if warnings else "ok",
        "cached": False,
        "cache_age_sec": 0,
    }
    _VOTER_ACCURACY_CACHE[cache_key] = {"ts": now, "payload": payload}
    return payload


@app.get("/api/system-health", tags=["System"])
async def system_health_summary():
    """Aggregated at-a-glance system health for the dashboard summary widget.

    Single-call replacement for 6 separate widget queries: LSTM verdict,
    drift alerts, open positions, portfolio heat, signal age, realized PnL.
    """
    import time as _time
    from src.core.database import NewsDB
    db = NewsDB()
    now = _time.time()

    # LSTM verdict (reuse existing logic inline)
    try:
        from api.routers.models import _hist_stats, LSTM_SWAP_TS
        post_rows = db._query(
            "SELECT lstm_pred FROM ml_predictions WHERE timestamp >= ? AND lstm_pred IS NOT NULL",
            (LSTM_SWAP_TS,),
        )
        vals = [float(r[0]) for r in post_rows if r[0] is not None]
        post_stats = _hist_stats(vals)
        if post_stats["n"] >= 20:
            if (post_stats["extreme_frac"] or 0) > 0.7 and (post_stats["middle_frac"] or 0) < 0.15:
                lstm_verdict = "degenerate"
            else:
                lstm_verdict = "healthy"
        else:
            lstm_verdict = "insufficient_data"
    except Exception:
        lstm_verdict = "unknown"
        post_stats = {"n": 0}

    # Drift alerts
    try:
        drifts = db._query(
            "SELECT severity, COUNT(*) FROM model_alerts WHERE resolved = 0 GROUP BY severity"
        )
        drift_by_sev = {r[0]: r[1] for r in drifts}
    except Exception:
        drift_by_sev = {}

    # Open trades + heat + per-trade details
    open_trades_detail = []
    try:
        open_rows = db._query(
            "SELECT id, direction, entry, sl, tp, lot, timestamp, pattern "
            "FROM trades WHERE status='OPEN' ORDER BY timestamp DESC LIMIT 5"
        )
        open_count = len(open_rows)
        total_risk = 0.0
        for r in open_rows:
            try:
                _id, direction, entry, sl, tp, lot, ts, pattern = r
                e, s, l = float(entry or 0), float(sl or 0), float(lot or 0)
                tp_f = float(tp or 0)
                risk_usd = abs(e - s) * 100.0 * l if (e > 0 and s > 0 and l > 0) else 0.0
                total_risk += risk_usd
                open_trades_detail.append({
                    "id": _id,
                    "direction": direction,
                    "entry": e,
                    "sl": s,
                    "tp": tp_f,
                    "lot": l,
                    "risk_usd": round(risk_usd, 2),
                    "pattern": pattern,
                    "timestamp": ts,
                })
            except (ValueError, TypeError):
                continue
        balance = float(db.get_param("portfolio_balance") or 10000)
        heat_pct = (total_risk / balance * 100) if balance > 0 else 0.0
    except Exception:
        open_count = 0
        heat_pct = 0.0
        total_risk = 0.0
        balance = 10000.0

    # Last scanner signal / rejection age
    def _age_seconds(sql):
        try:
            row = db._query_one(sql)
            if row and row[0]:
                from datetime import datetime
                t = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=__import__("datetime").timezone.utc)
                return (now - t.timestamp())
        except Exception:
            pass
        return None

    last_signal_age = _age_seconds("SELECT MAX(timestamp) FROM scanner_signals")
    last_rejection_age = _age_seconds("SELECT MAX(timestamp) FROM rejected_setups")

    # Realized PnL last 24h + 7d
    try:
        r24 = db._query_one(
            "SELECT COALESCE(SUM(profit), 0), COUNT(*) FROM trades "
            "WHERE status IN ('WIN','LOSS','PROFIT') AND profit IS NOT NULL "
            "AND julianday('now') - julianday(timestamp) < 1"
        )
        r7 = db._query_one(
            "SELECT COALESCE(SUM(profit), 0), COUNT(*) FROM trades "
            "WHERE status IN ('WIN','LOSS','PROFIT') AND profit IS NOT NULL "
            "AND julianday('now') - julianday(timestamp) < 7"
        )
        pnl_24h, trades_24h = float(r24[0] or 0), int(r24[1] or 0)
        pnl_7d, trades_7d = float(r7[0] or 0), int(r7[1] or 0)
    except Exception:
        pnl_24h = pnl_7d = 0.0
        trades_24h = trades_7d = 0

    # Overall verdict
    issues = []
    if lstm_verdict == "degenerate":
        issues.append("LSTM degenerate")
    if drift_by_sev.get("alert", 0) > 10:
        issues.append(f"{drift_by_sev['alert']} drift alerts")
    if heat_pct > 6.0:
        issues.append(f"heat {heat_pct:.1f}%")
    if last_signal_age is None or (last_signal_age and last_signal_age > 48 * 3600):
        issues.append("scanner silent")

    return {
        "overall": "issues" if issues else "healthy",
        "issues": issues,
        "lstm": {
            "verdict": lstm_verdict,
            "n_predictions": post_stats.get("n"),
            "extreme_frac": post_stats.get("extreme_frac"),
            "middle_frac": post_stats.get("middle_frac"),
        },
        "drift_alerts": {
            "alert": drift_by_sev.get("alert", 0),
            "warn": drift_by_sev.get("warn", 0),
            "total": sum(drift_by_sev.values()),
        },
        "trades": {
            "open": open_count,
            "total_risk_usd": round(total_risk, 2),
            "heat_pct": round(heat_pct, 2),
            "pnl_24h": round(pnl_24h, 2),
            "trades_24h": trades_24h,
            "pnl_7d": round(pnl_7d, 2),
            "trades_7d": trades_7d,
            "open_detail": open_trades_detail,
        },
        "scanner": {
            "last_signal_age_sec": last_signal_age,
            "last_rejection_age_sec": last_rejection_age,
        },
        "portfolio_balance": balance,
    }


@app.get("/api/backtest/wf-grid-live", tags=["System"])
async def backtest_wf_grid_live(name: str = "prod_v1", stage: str = "A", top: int = 5):
    """Live leaderboard for an in-flight walk-forward grid.

    Reads per-cell JSONs from reports/wf_grid_<name>_<stage>/cell_*.json,
    ranks by composite = 0.4*sharpe + 0.3*calmar + 0.3*PF (same formula as
    run_backtest_grid.py), returns top-N + pareto count + progress. Safe to
    call while grid is still running — cells appear as they finish.
    """
    import os as _os
    import glob as _glob
    import json as _json
    from fastapi import HTTPException

    safe_name = _os.path.basename(name)
    safe_stage = stage.upper() if stage.upper() in ("A", "B") else "A"
    grid_dir = f"reports/wf_grid_{safe_name}_{safe_stage}"
    if not _os.path.isdir(grid_dir):
        raise HTTPException(status_code=404, detail=f"Grid dir '{grid_dir}' not found")

    cells = []
    for fp in sorted(_glob.glob(f"{grid_dir}/cell_*.json")):
        try:
            cells.append(_json.loads(open(fp, "r", encoding="utf-8").read()))
        except Exception:
            continue

    def _composite(agg):
        s, c, pf = agg.get("sharpe_mean"), agg.get("calmar_mean"), agg.get("profit_factor_mean")
        if s is None or c is None or pf is None: return None
        try: return round(0.4 * float(s) + 0.3 * float(c) + 0.3 * float(pf), 4)
        except (TypeError, ValueError): return None

    def _pareto_front(items):
        pts = []
        for c in items:
            a = c.get("agg", {})
            s, dd = a.get("sharpe_mean"), a.get("max_drawdown_pct_mean")
            if s is None or dd is None: continue
            pts.append((c, float(s), float(dd)))
        front = []
        for c, s, dd in pts:
            dominated = any(s2 > s and dd2 > dd for _, s2, dd2 in pts if (s2, dd2) != (s, dd))
            if not dominated: front.append(c.get("params", {}).get("cell_hash"))
        return front

    ranked = sorted(cells, key=lambda c: _composite(c.get("agg", {})) or -1e18, reverse=True)
    front = set(_pareto_front(cells))

    top_entries = []
    for c in ranked[:top]:
        p, a = c.get("params", {}), c.get("agg", {})
        top_entries.append({
            "cell_hash": p.get("cell_hash"),
            "params": {k: p.get(k) for k in ("min_confidence", "sl_atr_mult", "target_rr", "partial_close", "risk_percent")},
            "composite": _composite(a),
            "sharpe": a.get("sharpe_mean"),
            "calmar": a.get("calmar_mean"),
            "profit_factor": a.get("profit_factor_mean"),
            "return_pct": a.get("return_pct_mean"),
            "max_drawdown_pct": a.get("max_drawdown_pct_mean"),
            "win_rate_pct": a.get("win_rate_pct_mean"),
            "total_trades": a.get("total_trades_mean"),
            "on_pareto_front": p.get("cell_hash") in front,
            "elapsed_sec": c.get("elapsed_sec"),
        })

    # Stage A has 96 cells target (hardcoded in build_grid for full mode)
    total_expected = 96 if safe_stage == "A" else None
    return {
        "name": safe_name,
        "stage": safe_stage,
        "completed": len(cells),
        "expected_total": total_expected,
        "pareto_front_count": len(front),
        "top": top_entries,
    }


@app.get("/api/backtest/run", tags=["System"])
async def backtest_run(name: str):
    """Full JSON for a specific run by name (e.g. 'bt_final'). 404 if not found.
    Read-only, path-traversal safe (basename only)."""
    import os as _os
    import json as _json
    from fastapi import HTTPException

    safe_name = _os.path.basename(name).replace(".json", "")
    for path in [f"reports/{safe_name}.json", f"data/{safe_name}.json"]:
        if _os.path.exists(path):
            try:
                data = _json.loads(open(path, "r", encoding="utf-8").read())
                return {"path": path, "mtime": _os.path.getmtime(path), "data": data}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Read failed: {e}")
    raise HTTPException(status_code=404, detail=f"Run '{safe_name}' not found")


@app.get("/api/backtest/chart", tags=["System"])
async def backtest_chart(name: str):
    """Serve a PNG chart for a backtest run. `name` = filename without ext.
    Looks up reports/{name}.png or reports/{name}_equity.png.
    Read-only — serves pre-generated PNGs only.
    """
    import os as _os
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    # Sanitize — only basename, no path traversal
    safe_name = _os.path.basename(name).replace(".png", "").replace(".json", "")
    candidates = [
        f"reports/{safe_name}.png",
        f"reports/{safe_name}_equity.png",
        f"data/{safe_name}.png",
        f"data/{safe_name}_equity.png",
    ]
    for path in candidates:
        if _os.path.exists(path) and path.endswith(".png"):
            return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=404, detail=f"No chart found for '{safe_name}'")


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


@app.get("/api/training/active", tags=["System"])
async def training_active():
    """Live snapshot of the currently-running RL training (if any).

    Reads data/training_heartbeat.json, written by train_rl.py on every
    episode. If the heartbeat is older than 90s we consider training dead
    and return status=idle — the UI hides the live widget in that case.
    """
    import os as _os
    import json as _json
    import time as _time

    path = "data/training_heartbeat.json"
    if not _os.path.exists(path):
        return {"status": "idle"}
    try:
        data = _json.loads(open(path, "r", encoding="utf-8").read())
    except Exception:
        return {"status": "idle"}

    updated_at = data.get("updated_at", 0)
    age = _time.time() - updated_at
    # 90s grace: per-episode time can be 30-60s on CPU, so we allow generous
    # window before declaring the heartbeat stale.
    if age > 90:
        return {"status": "idle", "last_seen_sec_ago": age}

    return {
        "status": "running",
        "current_episode": data.get("current_episode"),
        "total_episodes": data.get("total_episodes"),
        "last_reward": data.get("last_reward"),
        "avg_reward_20": data.get("avg_reward_20"),
        "balance": data.get("balance"),
        "win_rate_pct": data.get("win_rate_pct"),
        "epsilon": data.get("epsilon"),
        "elapsed_sec": data.get("elapsed_sec"),
        "eta_sec": data.get("eta_sec"),
        "age_sec": age,
    }


@app.get("/api/sweep/active", tags=["System"])
async def sweep_active():
    """Live snapshot of the Optuna RL hyperparameter sweep (if running).

    Reads data/sweep_heartbeat.json, written by tune_rl.py at every val
    checkpoint + at trial completion. The sweep cadence is coarser than
    per-episode RL training (heartbeat refreshes roughly every 100-300s),
    so we use a more generous 300s staleness grace before declaring idle.
    """
    import os as _os
    import json as _json
    import time as _time

    path = "data/sweep_heartbeat.json"
    if not _os.path.exists(path):
        return {"status": "idle"}
    try:
        data = _json.loads(open(path, "r", encoding="utf-8").read())
    except Exception:
        return {"status": "idle"}

    updated_at = data.get("updated_at", 0)
    age = _time.time() - updated_at
    # 600s grace — between trials the sweep refetches data (yfinance) and
    # builds a fresh TF graph, which can eat 2-5 minutes on CPU. 300s
    # tripped false-idle at the trial boundary; 600s covers the worst case
    # without letting a truly-dead sweep look alive for too long.
    if age > 600:
        return {"status": "idle", "last_seen_sec_ago": age,
                "study_name": data.get("study_name")}

    completed = data.get("completed_trials", 0) or 0
    pruned = data.get("pruned_trials", 0) or 0
    target = data.get("n_trials_target", 0) or 0
    started_at = data.get("started_at", 0) or 0
    elapsed_total = max(0.0, _time.time() - started_at) if started_at else None
    trials_done = completed + pruned
    per_trial_sec = (elapsed_total / trials_done) if trials_done > 0 and elapsed_total else None
    eta_sec = (per_trial_sec * (target - trials_done)) if per_trial_sec and target else None

    return {
        "status": data.get("status", "running"),
        "study_name": data.get("study_name"),
        "n_trials_target": target,
        "completed_trials": completed,
        "pruned_trials": pruned,
        "trial_number": data.get("trial_number"),
        "current_episode": data.get("current_episode"),
        "total_episodes": data.get("total_episodes") or data.get("episodes_per_trial"),
        "current_val_return": data.get("current_val_return"),
        "current_trial_best": data.get("current_trial_best"),
        "current_trial_elapsed_sec": data.get("current_trial_elapsed_sec"),
        "best_val_so_far": data.get("best_val_so_far"),
        "last_trial_state": data.get("last_trial_state"),
        "elapsed_total_sec": elapsed_total,
        "eta_sec": eta_sec,
        "age_sec": age,
    }


def _artifact_info(path: str) -> dict:
    """Return {exists, size_bytes, mtime_iso, age_hours} for a model artifact."""
    import os as _os
    import datetime as _dt
    if not _os.path.exists(path):
        return {"exists": False, "path": path}
    st = _os.stat(path)
    return {
        "exists": True,
        "path": path,
        "size_bytes": st.st_size,
        "mtime_iso": _dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "age_hours": round((_dt.datetime.now().timestamp() - st.st_mtime) / 3600, 2),
    }


@app.get("/api/models/voter-attribution", tags=["System"])
async def voter_attribution(days: int = 30):
    """Per-voter empirical accuracy over the last N days.

    Joins ml_predictions rows (one per ensemble call that produced a
    signal) with trades rows via trade_id, compares each voter's vote
    against the outcome's implied 'correct' direction (LONG trade that
    won ⇒ LONG was right; LONG trade that lost ⇒ SHORT would have been
    right), and buckets rows into correct / incorrect / abstained.

    Uses the new per-voter columns added in 43859f5. Legacy rows that
    pre-date the migration have NULL values in the voter columns and
    count as abstains (no penalty, no credit) — accurate given we simply
    don't know what that voter said.
    """
    import sqlite3 as _sqlite
    import os as _os

    db_path = _os.environ.get("DATABASE_URL", "data/sentinel.db")
    if not _os.path.exists(db_path):
        return {"status": "no_db", "voters": {}, "n_trades": 0}

    # Timestamp-based match: ml_predictions.trade_id is historically
    # never set by _persist_prediction, so the JOIN ... ON trade_id would
    # return zero rows. Instead we pick the most recent prediction within
    # 60 minutes BEFORE each trade's timestamp — the scanner runs every
    # 15 min, so 60 min is a comfortable window for clock skew / bar gaps.
    sql = f"""
        SELECT t.direction, t.status,
               mp.smc_pred, mp.attention_pred, mp.dpformer_pred,
               mp.deeptrans_pred, mp.lstm_pred, mp.xgb_pred, mp.dqn_action
        FROM trades t
        LEFT JOIN ml_predictions mp ON mp.id = (
            SELECT id FROM ml_predictions
            WHERE timestamp <= t.timestamp
              AND timestamp >= datetime(t.timestamp, '-60 minutes')
            ORDER BY timestamp DESC LIMIT 1
        )
        WHERE t.status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN')
          AND t.timestamp >= datetime('now', '-{int(days)} days')
    """
    conn = _sqlite.connect(db_path)
    try:
        rows = conn.execute(sql).fetchall()
    except _sqlite.OperationalError as e:
        # Most likely: columns don't exist yet on this DB (migration not run).
        return {"status": "schema_error", "error": str(e)[:200],
                "voters": {}, "n_trades": 0}
    finally:
        conn.close()

    voters = ("smc", "attention", "dpformer", "deeptrans", "lstm", "xgb", "dqn")
    result: dict = {v: {"correct": 0, "incorrect": 0, "abstain": 0,
                        "n_voted": 0, "accuracy": None} for v in voters}
    total_trades = 0

    for row in rows:
        direction, status, smc, attn, dp, deeptrans, lstm, xgb, dqn_action = row
        if status == "BREAKEVEN":
            # Neutral outcome — no "correct" direction, skip entirely.
            continue
        total_trades += 1
        is_win = status in ("WIN", "PROFIT")
        dir_upper = str(direction or "").upper()
        # The "correct" direction: winning trades confirm the direction;
        # losing trades imply the opposite would have been right.
        if "LONG" in dir_upper or dir_upper in ("BUY", "B"):
            trade_dir = "LONG"
        elif "SHORT" in dir_upper or dir_upper in ("SELL", "S"):
            trade_dir = "SHORT"
        else:
            continue  # unknown direction — shouldn't happen but defensive
        correct_dir = trade_dir if is_win else ("SHORT" if trade_dir == "LONG" else "LONG")

        def _bucket(voter: str, vote_dir: str | None) -> None:
            if vote_dir is None:
                result[voter]["abstain"] += 1
                return
            result[voter]["n_voted"] += 1
            if vote_dir == correct_dir:
                result[voter]["correct"] += 1
            else:
                result[voter]["incorrect"] += 1

        for voter, val in (("smc", smc), ("attention", attn),
                          ("dpformer", dp), ("deeptrans", deeptrans),
                          ("lstm", lstm), ("xgb", xgb)):
            if val is None:
                _bucket(voter, None)
            else:
                _bucket(voter, "LONG" if float(val) > 0.5 else "SHORT")

        # DQN uses discrete action: 0=HOLD (abstain), 1=BUY=LONG, 2=SELL=SHORT
        if dqn_action is None or int(dqn_action) == 0:
            _bucket("dqn", None)
        else:
            _bucket("dqn", "LONG" if int(dqn_action) == 1 else "SHORT")

    for v in voters:
        n = result[v]["n_voted"]
        if n > 0:
            result[v]["accuracy"] = round(result[v]["correct"] / n, 4)

    # Sort by accuracy desc (None-last) for the UI's convenience.
    ordered = sorted(result.items(),
                     key=lambda kv: (kv[1]["accuracy"] if kv[1]["accuracy"] is not None else -1),
                     reverse=True)

    return {
        "status": "ok",
        "days": days,
        "n_trades": total_trades,
        "voters": dict(ordered),
    }


@app.get("/api/sweep/winner-info", tags=["System"])
async def sweep_winner_info():
    """Side-by-side info on the sweep winner and the live production RL
    model. Used by the UI to render a 'Promote winner to production'
    panel without actually taking any action — this endpoint is pure
    filesystem stat, no copy / no db write."""
    prod = _artifact_info("models/rl_agent.keras")
    winner = _artifact_info("models/rl_sweep_winner.keras")
    prod_params = _artifact_info("models/rl_agent.keras.params")
    winner_params = _artifact_info("models/rl_sweep_winner.keras.params")
    prod_onnx = _artifact_info("models/rl_agent.onnx")
    winner_onnx = _artifact_info("models/rl_sweep_winner.onnx")

    last_promote_ts = None
    last_promote_backup = None
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        last_promote_ts = db.get_param("rl_last_promote_ts", None)
        last_promote_backup = db.get_param("rl_last_promote_backup", None)
    except Exception:
        pass

    return {
        "production": {"model": prod, "params": prod_params, "onnx": prod_onnx},
        "winner": {"model": winner, "params": winner_params, "onnx": winner_onnx},
        "winner_available": winner.get("exists", False) and winner_params.get("exists", False),
        "last_promote_ts": last_promote_ts,
        "last_promote_backup": last_promote_backup,
    }


@app.post("/api/sweep/promote", tags=["System"])
async def sweep_promote(confirm: bool = False, force: bool = False):
    """Copy the sweep winner over the production RL model.

    **Irreversible unless the backup is kept.** The endpoint:
      1. Refuses to run without ?confirm=true (deliberate friction — UI
         must show operator what they're replacing before calling this).
      2. Creates a timestamped backup of the current production model.
      3. Atomically copies winner .keras / .params / .onnx files into
         the production slots.
      4. Writes audit params (rl_last_promote_ts, rl_last_promote_backup).

    Returns the backup path so the UI can display it for rollback.
    """
    import datetime as _dt
    import os as _os
    import shutil

    if not confirm:
        return {"status": "rejected", "reason": "confirm=true required"}

    winner_keras = "models/rl_sweep_winner.keras"
    winner_params = "models/rl_sweep_winner.keras.params"
    winner_onnx = "models/rl_sweep_winner.onnx"  # optional
    prod_keras = "models/rl_agent.keras"
    prod_params = "models/rl_agent.keras.params"
    prod_onnx = "models/rl_agent.onnx"  # optional

    if not _os.path.exists(winner_keras) or not _os.path.exists(winner_params):
        return {"status": "error",
                "reason": f"winner artifacts missing ({winner_keras} or its .params)"}

    # 1. Backup current production, timestamped.
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_keras = f"models/rl_agent.pre_promote_{ts}.keras"
    backup_params = backup_keras + ".params"
    backup_onnx = f"models/rl_agent.pre_promote_{ts}.onnx"

    prod_existed = _os.path.exists(prod_keras)
    if prod_existed:
        if not force and not _os.path.exists(prod_params):
            return {"status": "error",
                    "reason": "prod .params missing — refusing to promote "
                              "without a complete backup (pass force=true to override)"}
        try:
            shutil.copy2(prod_keras, backup_keras)
            if _os.path.exists(prod_params):
                shutil.copy2(prod_params, backup_params)
            if _os.path.exists(prod_onnx):
                shutil.copy2(prod_onnx, backup_onnx)
        except Exception as e:
            return {"status": "error", "reason": f"backup failed: {e}"}

    # 2. Atomic-ish copy: write to .tmp first, then replace.
    try:
        for src, dst in ((winner_keras, prod_keras),
                         (winner_params, prod_params)):
            tmp = dst + ".tmp"
            shutil.copy2(src, tmp)
            _os.replace(tmp, dst)
        if _os.path.exists(winner_onnx):
            tmp = prod_onnx + ".tmp"
            shutil.copy2(winner_onnx, tmp)
            _os.replace(tmp, prod_onnx)
    except Exception as e:
        return {"status": "error", "reason": f"promote copy failed: {e}",
                "backup": backup_keras if prod_existed else None}

    # 3. Audit.
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("rl_last_promote_ts", _dt.datetime.now().isoformat(timespec="seconds"))
        db.set_param("rl_last_promote_backup", backup_keras if prod_existed else "")
    except Exception as e:
        # Do NOT fail the promote — the copy already succeeded. Surface via log.
        print(f"[promote] audit write failed: {e}")

    return {
        "status": "ok",
        "promoted_from": winner_keras,
        "promoted_to": prod_keras,
        "backup": backup_keras if prod_existed else None,
        "backup_params": backup_params if prod_existed and _os.path.exists(backup_params) else None,
        "backup_onnx": backup_onnx if prod_existed and _os.path.exists(backup_onnx) else None,
        "timestamp": ts,
    }


@app.get("/api/sweep/leaderboard", tags=["System"])
async def sweep_leaderboard(
    study_name: str = "rl_sweep_v1",
    top: int = 15,
    include_pruned: bool = False,
):
    """Top trials from an Optuna sweep study.

    Reads data/optuna_rl.db read-only via Optuna's own load_study so we
    don't need to track its schema. Returns rows sorted by value descending
    for direction=maximize (which the RL sweep uses). Pruned trials have
    no final value and are only included when explicitly requested.

    Intended use: the SweepLeaderboard widget on ModelsPage polls this to
    show which region of hyperparameter space TPE is converging on,
    without waiting for the whole sweep to finish.
    """
    import os as _os
    db_path = "data/optuna_rl.db"
    if not _os.path.exists(db_path):
        return {"status": "no_study", "study_name": study_name,
                "trials": [], "n_trials": 0}

    try:
        import optuna
        study = optuna.load_study(
            study_name=study_name,
            storage=f"sqlite:///{db_path}",
        )
    except Exception as e:
        # Most common cause: study name does not match the DB. Return the
        # empty-but-valid shape rather than 500 — the widget handles it.
        return {"status": "error", "study_name": study_name,
                "error": str(e)[:200], "trials": [], "n_trials": 0}

    trials = study.trials
    completed = [t for t in trials
                 if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in trials
              if t.state == optuna.trial.TrialState.PRUNED]
    running = [t for t in trials
               if t.state == optuna.trial.TrialState.RUNNING]

    # Rank completed trials; append pruned at the end with value=None when
    # requested. Maximize direction means higher value = better rank.
    ranked = sorted(completed, key=lambda t: (t.value if t.value is not None else float("-inf")),
                    reverse=(study.direction.name == "MAXIMIZE"))
    if include_pruned:
        ranked = ranked + pruned

    def _payload(t):
        duration = None
        if t.datetime_start and t.datetime_complete:
            duration = (t.datetime_complete - t.datetime_start).total_seconds()
        elif t.datetime_start:
            # Running / pruned-without-complete — compute against now.
            import datetime as _dt
            duration = (_dt.datetime.now(t.datetime_start.tzinfo or _dt.timezone.utc)
                        - t.datetime_start).total_seconds()
        return {
            "number": t.number,
            "state": t.state.name,
            "value": round(t.value, 4) if t.value is not None else None,
            "params": t.params,
            "duration_sec": round(duration, 1) if duration is not None else None,
        }

    return {
        "status": "ok",
        "study_name": study_name,
        "direction": study.direction.name,
        "n_trials": len(trials),
        "n_completed": len(completed),
        "n_pruned": len(pruned),
        "n_running": len(running),
        "best_value": round(study.best_value, 4) if completed else None,
        "best_trial_number": study.best_trial.number if completed else None,
        "trials": [_payload(t) for t in ranked[:max(1, top)]],
    }


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


@app.get("/api/health/orb", tags=["System"])
async def orb_health():
    """Asia Session Opening Range Breakout status for the dashboard.

    Returns current Asia window H/L, whether the London-open trading window
    is active or stale, and any live ORB signal (direction + reason). The
    widget uses this to show operators whether the ORB voter is in its
    2-hour firing window right now.
    """
    import datetime as _dt
    try:
        from src.trading.asia_orb import detect_orb_signal, get_asia_range
        from src.data.data_sources import get_provider
        import pandas_ta as _ta

        provider = get_provider()
        xau_df = provider.get_candles('XAU/USD', '1h', 60)
        if xau_df is None or len(xau_df) < 10:
            return {"status": "no_data", "detail": "XAU 1h candles unavailable"}

        # Make sure df has a DatetimeIndex (detect_orb_signal expects it)
        if not isinstance(xau_df.index, getattr(__import__('pandas'), 'DatetimeIndex', type(None))):
            if 'timestamp' in xau_df.columns:
                import pandas as _pd
                xau_df = xau_df.set_index(_pd.DatetimeIndex(xau_df['timestamp']))

        now_utc = _dt.datetime.now(_dt.timezone.utc)
        asia = get_asia_range(xau_df, reference_utc=now_utc)

        # HTF EMA200 for filter
        ema200 = None
        try:
            _e = _ta.ema(xau_df['close'], 200)
            if _e is not None and len(_e) > 0 and _e.iloc[-1] == _e.iloc[-1]:  # not NaN
                ema200 = float(_e.iloc[-1])
        except Exception:
            pass

        signal = detect_orb_signal(xau_df, htf_ema200=ema200, reference_utc=now_utc)

        # Window status: active if we're in 07:00-09:00 UTC, else stale
        in_window = (now_utc.hour == 7) or (now_utc.hour == 8) or (
            now_utc.hour == 9 and now_utc.minute == 0
        )
        minutes_to_next_open = (
            (24 - now_utc.hour) * 60 + (60 - now_utc.minute) if now_utc.hour >= 9
            else (7 - now_utc.hour) * 60 + (0 - now_utc.minute) if now_utc.hour < 7
            else 0
        )

        return {
            "status": "ok",
            "asia": asia,
            "window_active": bool(in_window),
            "minutes_to_next_london_open": max(0, minutes_to_next_open),
            "ema200_filter": ema200,
            "signal": signal,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/macro/snapshots", tags=["System"])
async def macro_snapshots(limit: int = 200):
    """Recent macro_regime snapshots (per-cycle persistence, see
    `_persist_macro_snapshots`). Returns id, timestamp, macro_regime,
    usdjpy_zscore, usdjpy_price, atr_ratio, market_regime — newest
    first. Caller can ?limit=N (cap 1000) for longer history."""
    try:
        from src.core.database import NewsDB
        rows = NewsDB().get_recent_macro_snapshots(limit=min(int(limit), 1000))
        return {
            "items": [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "macro_regime": r[2],
                    "usdjpy_zscore": r[3],
                    "usdjpy_price": r[4],
                    "atr_ratio": r[5],
                    "market_regime": r[6],
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        logger.error(f"/api/macro/snapshots failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/replay/stats", tags=["System"])
async def replay_stats(filter_name: Optional[str] = None,
                       direction: Optional[str] = None):
    """Per-filter rejection-replay verdicts from `rejected_setups`.

    Returns WR_strict (TP / TP+SL — the actionable metric, comparable
    to the ~33.7% R=1.96 breakeven), WR_loose (any-positive-close),
    and the four outcome counts (TP / SL / time-win / time-loss).
    Filter via `?filter_name=rsi_extreme` and / or `?direction=SHORT`.

    Built on top of the daily replay cron (`_replay_rejections_daily`).
    Each row in `rejected_setups` with a non-NULL `would_have_won`
    contributes here. NULL rows = either the rejection happened too
    recently for forward bars to exist in the warehouse, or atr/price
    were missing.
    """
    try:
        from src.core.database import NewsDB
        # Build the SQL with optional WHERE clauses
        where = ["would_have_won IS NOT NULL"]
        args: list = []
        if filter_name:
            where.append("filter_name = ?")
            args.append(filter_name)
        if direction:
            where.append("direction = ?")
            args.append(direction.upper())
        sql_per_filter = f"""
            SELECT filter_name,
                   COUNT(*) AS n,
                   SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) AS tp,
                   SUM(CASE WHEN would_have_won = 0 THEN 1 ELSE 0 END) AS sl,
                   SUM(CASE WHEN would_have_won = 2 THEN 1 ELSE 0 END) AS time_win,
                   SUM(CASE WHEN would_have_won = 3 THEN 1 ELSE 0 END) AS time_loss
            FROM rejected_setups
            WHERE {' AND '.join(where)}
            GROUP BY filter_name
            ORDER BY n DESC
        """
        db = NewsDB()
        rows = db.cursor.execute(sql_per_filter, args).fetchall()

        # Same R=1.96 breakeven the audit uses — kept as a constant in
        # the response so callers don't have to recompute. If the live
        # target_rr is ever changed, update here too.
        breakeven_r = 1.963
        breakeven_wr_strict = 1.0 / (1.0 + breakeven_r)

        items = []
        for filter_name_, n, tp, sl, tw, tl in rows:
            n_lvl = (tp or 0) + (sl or 0)
            wr_strict = (tp / n_lvl) if n_lvl else None
            wr_loose = ((tp or 0) + (tw or 0)) / n if n else None
            items.append({
                "filter_name": filter_name_,
                "n_rejected": n,
                "n_resolved_at_level": n_lvl,
                "tp": tp or 0, "sl": sl or 0,
                "time_win": tw or 0, "time_loss": tl or 0,
                "wr_strict": wr_strict,
                "wr_loose": wr_loose,
                "delta_vs_breakeven_pp": (
                    (wr_strict - breakeven_wr_strict) * 100
                    if wr_strict is not None else None
                ),
            })
        # Aggregate across the filtered set
        total_n = sum(i["n_rejected"] for i in items)
        total_tp = sum(i["tp"] for i in items)
        total_sl = sum(i["sl"] for i in items)
        total_tw = sum(i["time_win"] for i in items)
        total_n_lvl = total_tp + total_sl

        return {
            "items": items,
            "aggregate": {
                "n_rejected": total_n,
                "n_resolved_at_level": total_n_lvl,
                "tp": total_tp, "sl": total_sl, "time_win": total_tw,
                "wr_strict": (total_tp / total_n_lvl) if total_n_lvl else None,
                "wr_loose": ((total_tp + total_tw) / total_n) if total_n else None,
            },
            "breakeven_wr_strict": breakeven_wr_strict,
            "breakeven_R": breakeven_r,
            "filter_name": filter_name,
            "direction": direction.upper() if direction else None,
        }
    except Exception as e:
        logger.error(f"/api/replay/stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/macro/context", tags=["System"])
async def macro_context():
    """Compact macro context for the chart overview strip.

    Returns:
      - USDJPY spot + z-score (USD strength signal)
      - XAU-USDJPY rolling correlation (regime health — should be negative)
      - macro_regime flag (zielony/czerwony/neutralny — aggregates
        UUP/TLT/VIXY/USDJPY/ATR)
      - market_regime (2026-04-24) — rule-based regime from BBW+ADX+ATR:
        squeeze / trending_high_vol / trending_low_vol / ranging
    """
    result = {
        "usdjpy": None, "usdjpy_zscore": None, "xau_usdjpy_corr": None,
        "macro_regime": None, "uup": None, "tlt": None, "vixy": None,
        "market_regime": None, "regime_diag": None,
    }
    try:
        from src.trading.smc_engine import get_smc_analysis
        analysis = get_smc_analysis("1h")
        if analysis:
            result.update({
                "usdjpy": analysis.get("usdjpy"),
                "usdjpy_zscore": analysis.get("usdjpy_zscore"),
                "xau_usdjpy_corr": analysis.get("xau_usdjpy_corr"),
                "macro_regime": analysis.get("macro_regime"),
                "uup": analysis.get("uup"),
                "tlt": analysis.get("tlt"),
                "vixy": analysis.get("vixy"),
            })
    except Exception as e:
        result["error"] = str(e)

    # Market regime classification — independent of SMC analysis, reads
    # XAU candles directly.
    try:
        from src.analysis.regime import regime_diagnostics
        from src.data.data_sources import get_provider
        import pandas as _pd
        provider = get_provider()
        xau_df = provider.get_candles('XAU/USD', '1h', 100)
        if xau_df is not None and len(xau_df) >= 50:
            # compute_features adds atr/adx which regime_diagnostics uses
            try:
                from src.analysis.compute import compute_features
                feat = compute_features(xau_df.copy(), use_cache=False)
                diag = regime_diagnostics(feat)
            except Exception:
                diag = regime_diagnostics(xau_df)
            result["market_regime"] = diag.get("regime")
            result["regime_diag"] = diag
    except Exception as e:
        result["regime_error"] = str(e)

    return result


@app.get("/api/scanner/factors-attribution", tags=["System"])
async def scanner_factors_attribution(window_days: int = 30, last_n: int = 20):
    """Per-factor attribution + recent-trades breakdown.

    For each factor present in trades.factors JSON over the lookback window:
    counts wins/losses where the factor fired, computes win rate, and attaches
    the cumulative pnl. Lets the operator see which scoring boosters
    (asia_orb, vwap_confluence, post_news_2nd_rotation, grab_mss, etc.)
    actually correlate with WIN vs LOSS post-deployment.

    Also returns the most recent N resolved trades with their factor list,
    grade, and pnl — for the dashboard "last trades" mini-panel.
    """
    from src.core.database import NewsDB
    import json as _json
    from collections import defaultdict
    db = NewsDB()

    cutoff = f"-{int(window_days)} days"
    rows = db._query(
        "SELECT id, direction, status, profit, timestamp, factors, "
        "       setup_grade, setup_score, pattern, structure "
        "FROM trades "
        "WHERE status IN ('WIN','LOSS') "
        "  AND timestamp >= datetime('now', ?) "
        "ORDER BY id DESC",
        (cutoff,),
    )

    # Per-factor aggregate
    agg: dict = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "n": 0})
    for r in rows:
        try:
            factors = _json.loads(r[5]) if r[5] else {}
        except (TypeError, ValueError):
            factors = {}
        if not isinstance(factors, dict):
            continue
        is_win = r[2] == "WIN"
        pnl = float(r[3] or 0.0)
        for fname, fval in factors.items():
            # fval may be int (factor weight), bool, or other — count any presence
            if not fval:
                continue
            a = agg[fname]
            a["n"] += 1
            a["wins"] += int(is_win)
            a["losses"] += int(not is_win)
            a["pnl"] += pnl

    factors_summary = []
    for fname, a in sorted(agg.items(), key=lambda x: -x[1]["n"]):
        wr = round(a["wins"] / a["n"] * 100, 1) if a["n"] else 0
        factors_summary.append({
            "factor": fname,
            "n": a["n"],
            "wins": a["wins"],
            "losses": a["losses"],
            "win_rate_pct": wr,
            "pnl_total": round(a["pnl"], 2),
            "pnl_per_trade": round(a["pnl"] / a["n"], 2) if a["n"] else 0,
        })

    # Recent N trades — full breakdown including factors
    recent = []
    for r in rows[:last_n]:
        try:
            factors = _json.loads(r[5]) if r[5] else {}
        except (TypeError, ValueError):
            factors = {}
        recent.append({
            "id": r[0],
            "direction": r[1],
            "status": r[2],
            "profit": float(r[3] or 0.0),
            "timestamp": r[4],
            "factors": factors if isinstance(factors, dict) else {},
            "setup_grade": r[6],
            "setup_score": r[7],
            "pattern": r[8],
            "structure": r[9],
        })

    return {
        "window_days": window_days,
        "total_resolved": len(rows),
        "factors_summary": factors_summary,
        "recent_trades": recent,
    }


@app.get("/api/scanner/insight", tags=["System"])
async def scanner_insight(hours: int = 24):
    """Scanner insight panel data — explains why scanner is/isn't trading.

    Returns:
      - rejections: top 10 filter_name counts last N hours + total
      - toxic_patterns: current pattern_stats with block status vs threshold n>=20
      - streak: current consecutive-loss count + age of oldest in streak
      - kelly: reset_ts + post-reset trade count + current default risk
      - pause_flag: SCANNER_PAUSED file existence + reason string
    """
    from src.core.database import NewsDB
    import os as _os
    from collections import Counter
    db = NewsDB()

    since = f"-{int(hours)} hours"

    # 1. Rejection breakdown
    reject_rows = db._query(
        "SELECT filter_name FROM rejected_setups WHERE timestamp >= datetime('now', ?)",
        (since,),
    )
    reject_counter = Counter(r[0] for r in reject_rows if r[0])
    rejections_top = [
        {"filter": name, "count": n}
        for name, n in reject_counter.most_common(10)
    ]
    rejections_total = sum(reject_counter.values())

    # 2. Toxic pattern status
    pattern_rows = db._query(
        "SELECT pattern, count, wins, losses, win_rate FROM pattern_stats "
        "WHERE count > 0 ORDER BY count DESC"
    )
    TOXIC_N_THRESHOLD = 20
    TOXIC_WR_THRESHOLD = 0.30
    toxic_patterns = []
    for p, n, w, l, wr in pattern_rows:
        blocked = bool(n >= TOXIC_N_THRESHOLD and wr < TOXIC_WR_THRESHOLD)
        will_block = n >= TOXIC_N_THRESHOLD  # threshold reached but may be above WR cut
        toxic_patterns.append({
            "pattern": p,
            "n": int(n),
            "wins": int(w),
            "losses": int(l),
            "win_rate": round(float(wr or 0), 3),
            "n_threshold": TOXIC_N_THRESHOLD,
            "wr_threshold": TOXIC_WR_THRESHOLD,
            "blocked": blocked,
            "until_re_evaluate": max(0, TOXIC_N_THRESHOLD - int(n)),
        })

    # 3. Streak
    streak_rows = db._query(
        "SELECT id, status, timestamp FROM trades "
        "WHERE status IN ('WIN', 'LOSS') ORDER BY id DESC LIMIT 10"
    )
    consecutive_losses = 0
    oldest_loss_ts = None
    for r in streak_rows:
        if r[1] == 'LOSS':
            consecutive_losses += 1
            oldest_loss_ts = r[2]
        else:
            break
    oldest_age_hours = None
    if oldest_loss_ts:
        try:
            import datetime as _dt
            ts = _dt.datetime.strptime(str(oldest_loss_ts), "%Y-%m-%d %H:%M:%S")
            oldest_age_hours = round((_dt.datetime.now() - ts).total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    # 4. Kelly state
    kelly_reset_row = db._query_one(
        "SELECT param_text FROM dynamic_params WHERE param_name = 'kelly_reset_ts'"
    )
    kelly_reset_ts = kelly_reset_row[0] if kelly_reset_row else None
    post_reset_n = 0
    if kelly_reset_ts:
        post_reset_row = db._query_one(
            "SELECT COUNT(*) FROM trades WHERE status IN ('WIN','LOSS') AND timestamp > ?",
            (str(kelly_reset_ts),)
        )
        post_reset_n = int(post_reset_row[0]) if post_reset_row else 0

    # 5. Pause flag
    pause_flag_path = _os.path.join("data", "SCANNER_PAUSED")
    pause_reason = None
    is_paused = _os.path.exists(pause_flag_path)
    if is_paused:
        try:
            with open(pause_flag_path, 'r') as _f:
                pause_reason = _f.read().strip()
        except (OSError, IOError):
            pause_reason = "(could not read flag)"

    return {
        "hours_window": hours,
        "rejections": {
            "total": rejections_total,
            "top": rejections_top,
        },
        "toxic_patterns": toxic_patterns,
        "streak": {
            "consecutive_losses": consecutive_losses,
            "threshold": 5,
            "recency_hours": 6,
            "oldest_loss_age_hours": oldest_age_hours,
            "would_auto_pause": (
                consecutive_losses >= 5
                and oldest_age_hours is not None
                and oldest_age_hours <= 6
            ),
        },
        "kelly": {
            "reset_ts": kelly_reset_ts,
            "post_reset_trades": post_reset_n,
            "min_sample": 20,  # KELLY_MIN_TRADES
            "using_default_risk": post_reset_n < 20,
        },
        "paused": is_paused,
        "pause_reason": pause_reason,
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



