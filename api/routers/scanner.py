"""
api/routers/scanner.py — Background scanner control endpoints.

The scanner uses a file-based pause flag (`data/SCANNER_PAUSED`) read by
`_background_scanner()` in `api/main.py`. These endpoints expose the
flag to the frontend so the operator can pause/resume from the UI
(Cmd+K palette → "Pause scanner") without dropping into a shell.

Distinct from `risk.halt/resume` which kills *trading*; pausing the
scanner only stops *new entries* — open positions still resolve and
the dashboard keeps refreshing.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from src.core.logger import logger

router = APIRouter()

# Pause flag file — must match the path in api/main.py:_background_scanner
_PAUSE_FLAG = os.path.join("data", "SCANNER_PAUSED")


def _read_flag_state() -> dict:
    """Single source of truth for current pause state."""
    if not os.path.exists(_PAUSE_FLAG):
        return {"paused": False, "reason": None, "since": None}
    reason = None
    since = None
    try:
        with open(_PAUSE_FLAG, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            reason = raw or None
        st = os.stat(_PAUSE_FLAG)
        since = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
    except Exception as e:
        logger.warning(f"[scanner] could not read pause flag content: {e}")
    return {"paused": True, "reason": reason, "since": since}


@router.get(
    "/status",
    summary="Scanner pause status",
    description="Returns whether the background scanner is paused and the reason.",
)
async def scanner_status():
    return _read_flag_state()


@router.post(
    "/pause",
    summary="Pause the background scanner",
    description=(
        "Creates `data/SCANNER_PAUSED`. The background loop will skip cycles "
        "until the flag is removed. Open trade resolution and dashboard "
        "fetches continue — only new entries are blocked."
    ),
)
async def scanner_pause(reason: str | None = Body(default=None, embed=True)):
    text = reason or "manual pause via API"
    try:
        os.makedirs(os.path.dirname(_PAUSE_FLAG), exist_ok=True)
        with open(_PAUSE_FLAG, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception as e:
        logger.error(f"[scanner] pause failed: {e}")
        raise HTTPException(status_code=500, detail=f"could not create pause flag: {e}")
    logger.warning(f"📡 [scanner] PAUSED via API — reason: {text}")
    return {"ok": True, **_read_flag_state()}


@router.post(
    "/resume",
    summary="Resume the background scanner",
    description="Deletes `data/SCANNER_PAUSED`. No-op if the flag is absent.",
)
async def scanner_resume():
    if not os.path.exists(_PAUSE_FLAG):
        return {"ok": True, "was_paused": False, **_read_flag_state()}
    try:
        os.remove(_PAUSE_FLAG)
    except Exception as e:
        logger.error(f"[scanner] resume failed: {e}")
        raise HTTPException(status_code=500, detail=f"could not remove pause flag: {e}")
    logger.info("📡 [scanner] RESUMED via API — pause flag removed")
    return {"ok": True, "was_paused": True, **_read_flag_state()}
