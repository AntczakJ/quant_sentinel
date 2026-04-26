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
