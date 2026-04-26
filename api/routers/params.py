"""
api/routers/params.py — read-only inspection of dynamic_params usage + drift.

Exposes the in-process usage map from
`src.core.dynamic_params_schema` so the operator can spot writer/reader
drift live (the same kind of bug as #95569f7 — `target_rr` written but
production reading `tp_to_sl_ratio`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.core.logger import logger

router = APIRouter()


@router.get(
    "/usage",
    summary="dynamic_params usage map",
    description=(
        "Returns the in-process counters: per-key (n_writes, n_reads, "
        "last_write_ts, last_read_ts, last_value_repr). Counters reset on "
        "API restart — they describe the current uvicorn process only."
    ),
)
async def params_usage():
    try:
        from src.core.dynamic_params_schema import (
            get_usage_snapshot,
            known_keys,
            known_prefixes,
            mirror_targets,
        )
        return {
            "usage": get_usage_snapshot(),
            "known_keys": known_keys(),
            "known_prefixes": known_prefixes(),
            "mirrors": mirror_targets(),
        }
    except Exception as e:
        logger.error(f"params/usage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/drifts",
    summary="dynamic_params writer/reader drift detector",
    description=(
        "Lists keys that look suspicious: written-but-never-read, "
        "read-but-never-written, or last-written-but-not-read-recently. "
        "Soft signal — a key recently introduced may legitimately have no "
        "reader yet. Compare against `known_keys` to filter unknowns."
    ),
)
async def params_drifts(grace_s: float = 600.0):
    try:
        from src.core.dynamic_params_schema import find_drifts

        drifts = find_drifts(write_only_grace_s=grace_s)
        # Group for easier consumption
        by_kind: dict[str, list] = {}
        for d in drifts:
            by_kind.setdefault(d["kind"], []).append(d)
        return {
            "drifts": drifts,
            "by_kind": by_kind,
            "grace_s": grace_s,
            "total": len(drifts),
        }
    except Exception as e:
        logger.error(f"params/drifts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
