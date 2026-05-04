"""
src/core/queries/params.py — dynamic_params helpers.

Extracted from NewsDB god module 2026-05-04. Use these instead of
NewsDB().get_param / set_param in new code.

The schema validation + drift watchdog (set_param mirror logic) stays
inside NewsDB.set_param for now — these are simple read helpers.
"""
from __future__ import annotations

from typing import Optional


def _get_db():
    from src.core.database import NewsDB
    return NewsDB()


def get(name: str, default=None):
    """Get a single dynamic_params value."""
    return _get_db().get_param(name, default)


def get_float(name: str, default: float = 0.0) -> float:
    """Get param coerced to float."""
    val = _get_db().get_param(name, default)
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_bool(name: str, default: bool = False) -> bool:
    """Get param as boolean (0/1, '0'/'1', 'true'/'false', '' empty)."""
    val = _get_db().get_param(name, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return default


def set_(name: str, value) -> None:
    """Set a single dynamic_params value (with schema validation)."""
    _get_db().set_param(name, value)


def get_many(names: list[str], defaults: Optional[dict] = None) -> dict:
    """Batch read — single-trip if backend supports, else N round-trips."""
    db = _get_db()
    out = {}
    defaults = defaults or {}
    for n in names:
        out[n] = db.get_param(n, defaults.get(n))
    return out


def get_all_with_prefix(prefix: str) -> dict:
    """All params whose name starts with `prefix`. Useful for `weight_*`,
    `factor_alpha_*`, `daily_report_*` enumeration."""
    db = _get_db()
    rows = db._query(
        "SELECT param_name, param_value FROM dynamic_params WHERE param_name LIKE ?",
        (f"{prefix}%",)
    ) or []
    return {r[0]: r[1] for r in rows}
