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
    """Return `<pkg>.__version__` if importable, else None."""
    try:
        mod = __import__(import_name)
        return getattr(mod, "__version__", None)
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
        env_keys = ("LOGFIRE_TOKEN", "SENTRY_DSN", "TWELVEDATA_KEY",
                    "FRED_API_KEY", "FINNHUB_KEY", "ONNX_FORCE_CPU",
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
        }
    except Exception as e:
        logger.error(f"system/info error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
