"""
api/routers/system.py — diagnostic snapshot of the running Python +
runtime + ML stack.

Used by the Settings page System widget to give Janek a quick read on
what's actually loaded right now, without dropping into a shell.

Endpoint: GET /api/system/info
"""
from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.core.logger import logger

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = ROOT / "models"


def _safe_version(import_name: str) -> str | None:
    """Return `<pkg>.__version__` (or `.VERSION`) if importable, else None.

    sentry_sdk in particular exposes `VERSION` rather than `__version__`,
    so we fall back to that as a second probe before giving up.
    """
    try:
        mod = __import__(import_name)
        return getattr(mod, "__version__", None) or getattr(mod, "VERSION", None)
    except Exception:
        return None


def _git_info() -> dict:
    """Best-effort short SHA + branch + dirty flag. Soft-fallback if git
    isn't installed or the project isn't a repo (production deploy)."""
    try:
        import subprocess
        kwargs = dict(cwd=str(ROOT), capture_output=True, text=True, timeout=2)
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], **kwargs)
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], **kwargs)
        status = subprocess.run(["git", "status", "--porcelain"], **kwargs)
        return {
            "sha":    sha.stdout.strip() or None,
            "branch": branch.stdout.strip() or None,
            "dirty":  bool(status.stdout.strip()),
        }
    except Exception as e:
        return {"sha": None, "branch": None, "dirty": None, "error": str(e)}


def _model_files() -> list[dict]:
    """Walk models/ for the most relevant artifacts and report size + mtime."""
    if not MODELS_DIR.exists():
        return []
    interesting = (
        "xgb.pkl", "xgb.onnx", "xgb_treelite.dll", "xgb_treelite.so",
        "lstm.keras", "rl_agent.keras", "rl_agent.onnx",
        "attention.keras", "deeptrans.keras", "decompose.keras",
    )
    out = []
    for name in interesting:
        p = MODELS_DIR / name
        if p.exists():
            st = p.stat()
            out.append({
                "name": name,
                "size_kb": round(st.st_size / 1024, 1),
                "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
                "age_hours": round((time.time() - st.st_mtime) / 3600, 1),
            })
    return out


def _process_info() -> dict:
    """Coarse memory / cpu reading. Soft fallback when psutil missing."""
    try:
        import psutil  # type: ignore
        proc = psutil.Process()
        mem = proc.memory_info()
        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "num_threads": proc.num_threads(),
            "cpu_percent": proc.cpu_percent(interval=0.0),
            "uptime_s": round(time.time() - proc.create_time(), 0),
        }
    except Exception as e:
        return {"error": str(e)}


def _integrations_status() -> dict:
    """High-level boolean status of external services for the Settings widget.
    More forgiving than `_env_status` — Logfire stores its token in
    `.logfire/logfire_credentials.json` (not env), Modal in `~/.modal.toml`."""
    home = Path.home()
    return {
        "logfire": {
            "active": bool(os.environ.get("LOGFIRE_TOKEN", "").strip())
                      or (ROOT / ".logfire" / "logfire_credentials.json").exists()
                      or (home / ".logfire" / "default.toml").exists(),
            "url": "https://logfire-eu.pydantic.dev/antczak-j/quant-sentinel",
            "what": "Live request spans + scanner traces. 10M spans/mc free.",
        },
        "sentry": {
            "active": bool(os.environ.get("SENTRY_DSN", "").strip()),
            "url": "https://sentry.io/issues/?project=4511289079169104",
            "what": "Captured exceptions + bg-scanner cron heartbeats. 5k events/mc free.",
        },
        "modal": {
            # `~/.modal.toml` is the canonical token location after `modal token new`
            "active": (home / ".modal.toml").exists(),
            "url": "https://modal.com/apps/antczakj/main/deployed/quant-sentinel-train",
            "what": "Weekly Sun 03:00 UTC retrain on T4 GPU. ~$0.30-0.60 per fire.",
        },
    }


def _gpu_info() -> dict:
    """Lazy GPU probe via the existing helper. Cached at first call upstream."""
    try:
        from src.analysis.compute import detect_gpu
        info = detect_gpu()
        # detect_gpu returns a dict-like; pick a stable subset.
        keys = ("onnx_directml", "cuda_available", "device", "provider")
        return {k: info.get(k) for k in keys if k in info}
    except Exception as e:
        return {"error": str(e)}


def _disk_info() -> dict:
    """Free space on the data partition."""
    try:
        import shutil
        usage = shutil.disk_usage(str(ROOT))
        return {
            "total_gb": round(usage.total / 1024**3, 1),
            "used_gb":  round(usage.used  / 1024**3, 1),
            "free_gb":  round(usage.free  / 1024**3, 1),
            "free_pct": round(usage.free  / usage.total * 100, 1),
        }
    except Exception as e:
        return {"error": str(e)}


def _xgb_loader_info() -> dict:
    """Which XGB voter path is currently active in the cache."""
    try:
        from src.ml.ensemble_models import _models_cache, _models_loaded
        if not _models_loaded.get("xgb"):
            return {"status": "not loaded"}
        kind, _model = _models_cache["xgb"]
        return {"status": "loaded", "path": kind}
    except Exception as e:
        return {"error": str(e)}


@router.get("/health/deep", summary="Detailed health probe — DB / models / GPU / scanner / trades")
async def health_deep():
    """
    Per-subsystem health probe. Each section reports `ok` (bool) plus a
    short context string. The top-level `all_ok` is true iff every check
    passed. This is meant for the Settings → System diagnostic widget
    and for ad-hoc curl debugging — `/api/health` stays the canonical
    fast liveness probe.
    """
    checks: dict[str, dict] = {}

    # ── DB connectivity ─────────────────────────────────────────────
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        row = db._query_one("SELECT COUNT(*) FROM trades")
        checks["db"] = {
            "ok": True,
            "message": f"sentinel.db reachable, {int(row[0]) if row else 0} trades",
        }
    except Exception as e:
        checks["db"] = {"ok": False, "message": f"DB query failed: {e}"}

    # ── Models loaded ───────────────────────────────────────────────
    try:
        from src.ml.ensemble_models import _models_loaded
        loaded = {k: bool(v) for k, v in _models_loaded.items()}
        any_loaded = any(loaded.values())
        checks["models"] = {
            "ok": True,
            "loaded": loaded,
            "message": f"{sum(loaded.values())}/{len(loaded)} voters cached"
                       + (" (lazy — first scan will trigger)" if not any_loaded else ""),
        }
    except Exception as e:
        checks["models"] = {"ok": False, "message": f"Model status probe failed: {e}"}

    # ── GPU ────────────────────────────────────────────────────────
    try:
        from src.analysis.compute import detect_gpu
        gpu = detect_gpu()
        any_gpu = bool(gpu.get("onnx_directml") or gpu.get("cuda_available"))
        checks["gpu"] = {
            "ok": True,
            "message": "DirectML" if gpu.get("onnx_directml") else (
                "CUDA" if gpu.get("cuda_available") else "CPU only"
            ),
            "any_gpu": any_gpu,
        }
    except Exception as e:
        checks["gpu"] = {"ok": False, "message": f"GPU probe failed: {e}"}

    # ── Scanner state ──────────────────────────────────────────────
    try:
        import time as _time
        from src.ops.metrics import scan_last_ts as _slts
        last_ts = _slts.get() if hasattr(_slts, "get") else 0
        # Pause flag presence (file flag — same logic as scanner.py router)
        pause_flag = ROOT / "data" / "SCANNER_PAUSED"
        is_paused = pause_flag.exists()
        age_s = (_time.time() - last_ts) if last_ts > 0 else None
        # Healthy when not paused AND last cycle within 10 min (5-min interval × 2)
        healthy = (not is_paused) and (age_s is not None) and (age_s < 600)
        checks["scanner"] = {
            "ok": healthy or is_paused,  # paused is OK by intent
            "paused": is_paused,
            "last_cycle_s_ago": round(age_s, 1) if age_s is not None else None,
            "message": (
                "paused (manual or auto-streak)" if is_paused
                else (f"last cycle {age_s:.0f}s ago" if age_s is not None else "no cycle yet")
            ),
        }
    except Exception as e:
        checks["scanner"] = {"ok": False, "message": f"Scanner probe failed: {e}"}

    # ── Trades / open positions ────────────────────────────────────
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        last_trade = db._query_one(
            "SELECT timestamp, status FROM trades ORDER BY id DESC LIMIT 1"
        )
        open_count = db._query_one(
            "SELECT COUNT(*) FROM trades WHERE status IN ('OPEN','PROPOSED')"
        )
        checks["trades"] = {
            "ok": True,
            "last_timestamp": str(last_trade[0]) if last_trade else None,
            "last_status":    str(last_trade[1]) if last_trade else None,
            "open_count":     int(open_count[0]) if open_count else 0,
        }
    except Exception as e:
        checks["trades"] = {"ok": False, "message": f"Trade probe failed: {e}"}

    # ── Aggregate ──────────────────────────────────────────────────
    all_ok = all(c.get("ok", False) for c in checks.values())
    return {
        "all_ok": all_ok,
        "checks": checks,
    }


@router.get(
    "/recommendations",
    summary="Heuristic next-step suggestions (missing tokens, stale models, etc.)",
)
async def recommendations():
    """Walks a small set of soft-checks and returns a list of suggestions
    sorted by severity. Each item: {title, severity, detail, action_url?}.
    Severities: 'info' (FYI), 'warn' (should look at), 'error' (broken)."""
    items: list[dict] = []
    integ = _integrations_status()
    env = {k: bool(os.environ.get(k, "").strip()) for k in (
        "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_KEY", "FRED_API_KEY", "FINNHUB_API_KEY",
        "API_SECRET_KEY",
    )}

    # --- External integrations ---
    if not integ["logfire"]["active"]:
        items.append({
            "id": "logfire-missing",
            "severity": "warn",
            "title": "Logfire not configured",
            "detail": "Run `.venv/Scripts/logfire auth` then `logfire projects new --default-org quant-sentinel`. Free 10M spans/mc.",
            "action_url": "https://logfire-eu.pydantic.dev/",
        })
    if not integ["sentry"]["active"]:
        items.append({
            "id": "sentry-missing",
            "severity": "warn",
            "title": "Sentry DSN not set",
            "detail": "Create a Python project at sentry.io, paste the DSN into .env as SENTRY_DSN. Free 5k events/mc.",
            "action_url": "https://sentry.io/signup/",
        })
    if not integ["modal"]["active"]:
        items.append({
            "id": "modal-missing",
            "severity": "info",
            "title": "Modal token absent",
            "detail": "Run `.venv/Scripts/modal token new` to enable cloud GPU offload (weekly retrain).",
            "action_url": "https://modal.com/",
        })

    # --- Data provider keys ---
    if not env["TWELVE_DATA_API_KEY"]:
        items.append({
            "id": "twelvedata-missing",
            "severity": "warn",
            "title": "TwelveData API key missing",
            "detail": "Live price + candle source. Without it the scanner falls back to yfinance which has rate caps.",
        })
    if not env["FRED_API_KEY"]:
        items.append({
            "id": "fred-missing",
            "severity": "info",
            "title": "FRED API key missing",
            "detail": "Macro snapshots (UUP, TLT, VIXY proxies) won't populate without it.",
        })

    # --- Auth ---
    if not env["API_SECRET_KEY"]:
        items.append({
            "id": "api-secret-missing",
            "severity": "warn",
            "title": "API_SECRET_KEY not set",
            "detail": "Write endpoints (POST/PUT/DELETE) currently accept anonymous calls. Set it in .env to require auth.",
        })

    # --- Model freshness ---
    try:
        files = _model_files()
        # xgb.pkl + lstm.keras are the live voters; flag if older than 7 days
        for m in files:
            if m["name"] in ("xgb.pkl", "lstm.keras") and m["age_hours"] > 24 * 7:
                items.append({
                    "id": f"model-stale-{m['name']}",
                    "severity": "info",
                    "title": f"{m['name']} is {int(m['age_hours']/24)} days old",
                    "detail": "Consider a retrain. Modal cron fires Sun 03:00 UTC if configured; otherwise run `python train_all.py` locally.",
                })
    except Exception:
        pass

    # --- Disk pressure ---
    try:
        disk = _disk_info()
        free_gb = float(disk.get("free_gb") or 0)
        if 0 < free_gb < 5:
            items.append({
                "id": "disk-low",
                "severity": "error",
                "title": f"Disk free {free_gb} GB",
                "detail": "Drive is critically full. Clean data/backups (auto-pruned but check), node_modules, dist/.",
            })
        elif 0 < free_gb < 20:
            items.append({
                "id": "disk-warn",
                "severity": "warn",
                "title": f"Disk free {free_gb} GB",
                "detail": "Below 20 GB — consider cleaning data/backups and old training artifacts.",
            })
    except Exception:
        pass

    # --- Scanner pause flag ---
    try:
        pause_flag = ROOT / "data" / "SCANNER_PAUSED"
        if pause_flag.exists():
            import time as _time
            age_h = (_time.time() - pause_flag.stat().st_mtime) / 3600
            sev = "error" if age_h > 24 else "warn"
            items.append({
                "id": "scanner-paused",
                "severity": sev,
                "title": f"Scanner paused for {age_h:.1f}h",
                "detail": "Background scanner is skipping new entries. Resume via Cmd+K → 'Resume scanner' or delete data/SCANNER_PAUSED.",
            })
    except Exception:
        pass

    # --- Open trades sanity ---
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        row = db._query_one(
            "SELECT COUNT(*) FROM trades WHERE status IN ('OPEN','PROPOSED')"
        )
        n_open = int(row[0] or 0) if row else 0
        if n_open >= 5:
            items.append({
                "id": "open-trades-many",
                "severity": "warn",
                "title": f"{n_open} open positions",
                "detail": "Multiple concurrent positions — check risk_manager halt thresholds didn't get bypassed.",
            })
    except Exception:
        pass

    # --- Sort by severity ---
    sev_rank = {"error": 0, "warn": 1, "info": 2}
    items.sort(key=lambda x: sev_rank.get(x.get("severity"), 99))
    return {
        "count": len(items),
        "by_severity": {
            "error": sum(1 for i in items if i["severity"] == "error"),
            "warn":  sum(1 for i in items if i["severity"] == "warn"),
            "info":  sum(1 for i in items if i["severity"] == "info"),
        },
        "items": items,
    }


@router.get("/db-timing", summary="Latency probe — common SELECT queries on sentinel.db")
async def db_timing(repeats: int = 5):
    """Time a handful of representative SELECTs and return per-query
    median / min / max in milliseconds. Useful for catching SQLite
    latency creep (lock contention, WAL bloat, missing index regression)
    before it shows up as a scanner-cycle slowdown."""
    import time as _t
    from src.core.database import NewsDB
    db = NewsDB()
    queries = {
        "select_1": "SELECT 1",
        "count_trades": "SELECT COUNT(*) FROM trades",
        "count_open_trades": "SELECT COUNT(*) FROM trades WHERE status IN ('OPEN','PROPOSED')",
        "count_resolved_today": (
            "SELECT COUNT(*) FROM trades "
            "WHERE status IN ('WIN','LOSS','PROFIT','LOSE','CLOSED') "
            "AND timestamp >= datetime('now','-24 hours')"
        ),
        "count_rejections_24h": (
            "SELECT COUNT(*) FROM rejected_setups "
            "WHERE timestamp >= datetime('now','-24 hours')"
        ),
        "latest_dynamic_params": "SELECT param_name FROM dynamic_params ORDER BY last_updated DESC LIMIT 5",
        "scanner_signals_recent": (
            "SELECT id FROM scanner_signals ORDER BY id DESC LIMIT 50"
        ),
        "ml_predictions_recent": (
            "SELECT id FROM ml_predictions ORDER BY id DESC LIMIT 50"
        ),
    }

    def _run(sql: str) -> tuple[float, int]:
        ts = []
        rows_seen = 0
        for _ in range(max(1, repeats)):
            t0 = _t.perf_counter()
            try:
                rows = db._query(sql)
                rows_seen = len(rows) if rows else 0
            except Exception:
                rows_seen = -1
                ts.append(float("nan"))
                continue
            ts.append((_t.perf_counter() - t0) * 1000.0)
        return ts, rows_seen

    out: dict[str, dict] = {}
    all_medians: list[float] = []
    for name, sql in queries.items():
        ts, n = _run(sql)
        clean = [x for x in ts if x == x]  # drop NaN
        if not clean:
            out[name] = {"error": "all probes failed", "sql": sql}
            continue
        clean_sorted = sorted(clean)
        median = clean_sorted[len(clean_sorted) // 2]
        out[name] = {
            "median_ms": round(median, 3),
            "min_ms":    round(min(clean), 3),
            "max_ms":    round(max(clean), 3),
            "rows":      n,
            "repeats":   len(clean),
        }
        all_medians.append(median)

    # Aggregate health verdict
    summary = {
        "total_queries": len(queries),
        "ok_queries":    len(all_medians),
        "median_of_medians_ms": round(sorted(all_medians)[len(all_medians) // 2], 3) if all_medians else None,
        "max_median_ms":        round(max(all_medians), 3) if all_medians else None,
        "verdict": (
            "fast"     if all_medians and max(all_medians) < 5
            else "ok"  if all_medians and max(all_medians) < 50
            else "slow" if all_medians and max(all_medians) < 250
            else "concerning"
        ),
    }
    return {"queries": out, "summary": summary}


@router.get("/db-stats", summary="Counts + file size for sentinel.db tables")
async def db_stats():
    """Quick counts of the tables the operator usually wants to see —
    trades by status, rejected_setups, scanner_signals, model_alerts —
    plus the on-disk file size."""
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        # Trade buckets
        def _scalar(sql: str, args: tuple = ()) -> int:
            row = db._query_one(sql, args)
            return int(row[0] or 0) if row else 0

        trades_total = _scalar("SELECT COUNT(*) FROM trades")
        trades_open = _scalar(
            "SELECT COUNT(*) FROM trades WHERE status IN ('OPEN','PROPOSED')"
        )
        trades_closed = _scalar(
            "SELECT COUNT(*) FROM trades WHERE status IN ('WIN','LOSS','PROFIT','LOSE','CLOSED')"
        )
        trades_wins = _scalar(
            "SELECT COUNT(*) FROM trades WHERE status IN ('WIN','PROFIT')"
        )

        # Aux tables — wrap individually so a missing one doesn't kill the whole report.
        def _safe_count(table: str) -> int | None:
            try:
                return _scalar(f"SELECT COUNT(*) FROM {table}")
            except Exception:
                return None

        rejected_setups   = _safe_count("rejected_setups")
        scanner_signals   = _safe_count("scanner_signals")
        model_alerts      = _safe_count("model_alerts")
        ml_predictions    = _safe_count("ml_predictions")
        dynamic_params_n  = _safe_count("dynamic_params")
        pattern_stats_n   = _safe_count("pattern_stats")

        # File size
        db_path = ROOT / "data" / "sentinel.db"
        size_kb = round(db_path.stat().st_size / 1024, 1) if db_path.exists() else None

        return {
            "trades": {
                "total": trades_total,
                "open": trades_open,
                "closed": trades_closed,
                "wins": trades_wins,
                "losses": trades_closed - trades_wins,
                "win_rate_pct": round(trades_wins / trades_closed * 100, 1) if trades_closed else None,
            },
            "tables": {
                "rejected_setups": rejected_setups,
                "scanner_signals": scanner_signals,
                "model_alerts": model_alerts,
                "ml_predictions": ml_predictions,
                "dynamic_params": dynamic_params_n,
                "pattern_stats": pattern_stats_n,
            },
            "file": {
                "path": "data/sentinel.db",
                "size_kb": size_kb,
            },
        }
    except Exception as e:
        logger.error(f"system/db-stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-trace", summary="Smoke-test Logfire (emits a span)")
async def system_test_trace():
    """Invoke this once after `logfire auth` to confirm spans are reaching
    the Logfire dashboard. Soft-noop when Logfire is disabled — never
    raises. Writes one structured info span and one INFO log line."""
    import logging as _logging
    try:
        import logfire as _lf
        with _lf.span("system.test_trace", marker="manual_smoke"):
            _lf.info("Logfire smoke test", source="api/system/test-trace")
        return {"ok": True, "message": "Span emitted (visible in Logfire if token configured)"}
    except Exception as e:
        _logging.getLogger("logfire").debug(f"test-trace soft-fail: {e}")
        return {"ok": False, "message": "Logfire not configured", "detail": str(e)}


@router.post("/test-error", summary="Smoke-test Sentry (raises a captured exception)")
async def system_test_error():
    """Triggers a captured ZeroDivisionError so Janek can verify Sentry
    receives the event after pasting SENTRY_DSN. Returns 500 if Sentry
    is on (the captured exception bubbles), or 200 with `disabled: true`
    when no DSN is set."""
    if not os.environ.get("SENTRY_DSN", "").strip():
        return {"ok": False, "disabled": True, "message": "SENTRY_DSN not set — skipping the raise"}
    # When Sentry IS configured, deliberately raise so the SDK captures it.
    1 / 0  # noqa: B018 — intentional


@router.get("/rate-limit", summary="API rate-limiter status")
async def rate_limit_status():
    """Snapshot of the TwelveData credit bucket — what's available right
    now, what's been spent in the last minute, and the configured caps."""
    try:
        from src.api_optimizer import get_rate_limiter
        return get_rate_limiter().get_stats()
    except Exception as e:
        logger.error(f"system/rate-limit error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info", summary="System / runtime / ML stack diagnostic")
async def system_info():
    try:
        env_keys = ("LOGFIRE_TOKEN", "SENTRY_DSN", "TWELVE_DATA_API_KEY",
                    "FRED_API_KEY", "FINNHUB_API_KEY", "ONNX_FORCE_CPU",
                    "DISABLE_TRAILING", "MAX_LOT_CAP")
        env_status = {k: bool(os.environ.get(k, "").strip()) for k in env_keys}

        return {
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "git": _git_info(),
            "versions": {
                "fastapi":   _safe_version("fastapi"),
                "uvicorn":   _safe_version("uvicorn"),
                "pydantic":  _safe_version("pydantic"),
                "pandas":    _safe_version("pandas"),
                "polars":    _safe_version("polars"),
                "numpy":     _safe_version("numpy"),
                "numba":     _safe_version("numba"),
                "xgboost":   _safe_version("xgboost"),
                "torch":     _safe_version("torch"),
                "tensorflow": _safe_version("tensorflow"),
                "treelite":  _safe_version("treelite"),
                "tl2cgen":   _safe_version("tl2cgen"),
                "duckdb":    _safe_version("duckdb"),
                "logfire":   _safe_version("logfire"),
                "sentry_sdk": _safe_version("sentry_sdk"),
            },
            "models": _model_files(),
            "xgb_loader": _xgb_loader_info(),
            "process": _process_info(),
            "gpu": _gpu_info(),
            "disk": _disk_info(),
            "env": env_status,
            "integrations": _integrations_status(),
        }
    except Exception as e:
        logger.error(f"system/info error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
