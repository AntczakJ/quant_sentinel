"""
api/routers/grid.py — surface the grid-backtest winner-apply flow over HTTP.

Reuses the helpers in `scripts/apply_grid_winner.py` via importlib so we
keep a single source of truth (the script remains the canonical CLI).

Endpoints:
  GET  /api/grid/list                   — all grid reports under reports/
  GET  /api/grid/preview?grid=<name>    — top cells + diff against current
  POST /api/grid/apply                  — write winner to dynamic_params + backup
  GET  /api/grid/backups                — list param-backup snapshots
  POST /api/grid/rollback               — restore a backup snapshot

Safety: APPLY and ROLLBACK both require explicit `confirm: true` in the
JSON body. Without it the call is a noop preview.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from src.core.logger import logger

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "apply_grid_winner.py"


def _load_script_module():
    """Lazy-load the standalone CLI module so its private helpers are reusable here."""
    if "apply_grid_winner_module" in sys.modules:
        return sys.modules["apply_grid_winner_module"]
    spec = importlib.util.spec_from_file_location("apply_grid_winner_module", str(SCRIPT))
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load grid script at {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["apply_grid_winner_module"] = module
    spec.loader.exec_module(module)
    return module


def _list_grid_names() -> list[dict[str, Any]]:
    """Scan reports/ for `wf_grid_<name>_{A,B}` directories."""
    reports = ROOT / "reports"
    if not reports.exists():
        return []
    names: dict[str, dict[str, Any]] = {}
    for d in reports.iterdir():
        if not d.is_dir() or not d.name.startswith("wf_grid_"):
            continue
        # wf_grid_<name>_A or wf_grid_<name>_B
        suffix = d.name.rsplit("_", 1)[-1]
        if suffix not in ("A", "B"):
            continue
        name = d.name[len("wf_grid_") : -2]
        record = names.setdefault(name, {"name": name, "stages": []})
        json_path = d / f"stage_{suffix}.json"
        if json_path.exists():
            try:
                rep = json.loads(json_path.read_text(encoding="utf-8"))
                cells = rep.get("cells", [])
                record["stages"].append({
                    "stage": suffix,
                    "n_cells": len(cells),
                    "best_composite": (cells[0].get("composite") if cells else None),
                    "modified": json_path.stat().st_mtime,
                })
            except Exception as e:
                logger.warning(f"grid/list: failed to read {json_path}: {e}")
    return sorted(names.values(), key=lambda r: r["name"])


@router.get("/list", summary="List grid backtests with reports on disk")
async def grid_list():
    return {"grids": _list_grid_names()}


@router.get("/preview", summary="Preview a grid winner — diff vs current dynamic_params")
async def grid_preview(
    grid: str = Query("prod_v1"),
    cell_hash: Optional[str] = Query(None, description="Cell hash prefix (default: top by composite)"),
):
    try:
        mod = _load_script_module()
        report = mod._load_stage_b(grid)
        cell = mod._pick_cell(report, cell_hash)
        params = cell.get("params", {})
        agg = cell.get("agg", {})
        winner = {
            "sl_atr_multiplier": params.get("sl_atr_mult"),
            "tp_to_sl_ratio": params.get("target_rr"),
            "target_rr": params.get("target_rr"),
            "risk_percent": params.get("risk_percent"),
        }
        from src.core.database import NewsDB
        current = mod._read_current_params(NewsDB())

        # Build a structured diff (one entry per writable param).
        diff = []
        for k in mod.DYNAMIC_PARAMS_WRITABLE:
            cur_v = current.get(k)
            new_v = winner.get(k)
            try:
                cur_f = float(cur_v) if cur_v is not None else None
                new_f = float(new_v) if new_v is not None else None
            except (TypeError, ValueError):
                cur_f, new_f = None, None
            change_pct = None
            if cur_f and new_f and cur_f != 0:
                change_pct = round((new_f - cur_f) / abs(cur_f) * 100, 2)
            diff.append({
                "param": k,
                "current": cur_v,
                "winner": new_v,
                "change_pct": change_pct,
                "unchanged": (cur_f is not None and new_f is not None and abs(cur_f - new_f) < 1e-6),
            })

        return {
            "grid": grid,
            "stage": report.get("stage", "B"),
            "cell_hash": params.get("cell_hash"),
            "metrics": {
                "sharpe_mean": agg.get("sharpe_mean"),
                "sharpe_stdev": agg.get("sharpe_stdev"),
                "profit_factor_mean": agg.get("profit_factor_mean"),
                "return_pct_mean": agg.get("return_pct_mean"),
                "return_pct_stdev": agg.get("return_pct_stdev"),
                "max_drawdown_pct_mean": agg.get("max_drawdown_pct_mean"),
                "total_trades_mean": agg.get("total_trades_mean"),
            },
            "diff": diff,
            "winner_params": winner,
            "code_level_params": {
                "min_confidence": params.get("min_confidence"),
                "partial_close": params.get("partial_close"),
            },
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"grid/preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply", summary="Apply a grid winner to production dynamic_params")
async def grid_apply(
    grid: str = Body("prod_v1", embed=True),
    cell_hash: Optional[str] = Body(None, embed=True),
    confirm: bool = Body(False, embed=True),
):
    """Apply requires `confirm: true` — otherwise behaves like /preview."""
    try:
        mod = _load_script_module()
        report = mod._load_stage_b(grid)
        cell = mod._pick_cell(report, cell_hash)
        params = cell.get("params", {})
        winner = {
            "sl_atr_multiplier": params.get("sl_atr_mult"),
            "tp_to_sl_ratio": params.get("target_rr"),
            "target_rr": params.get("target_rr"),
            "risk_percent": params.get("risk_percent"),
        }
        if not confirm:
            return {
                "ok": False,
                "applied": False,
                "reason": "confirm=false (preview-only call)",
                "winner": winner,
                "cell_hash": params.get("cell_hash"),
            }
        from src.core.database import NewsDB
        db = NewsDB()
        current = mod._read_current_params(db)
        backup_path = mod._write_backup(current, grid, params.get("cell_hash", "unknown"))
        mod._apply(db, winner)
        logger.warning(
            f"📥 [grid] Applied winner via API: grid={grid} "
            f"cell={params.get('cell_hash')} backup={backup_path.relative_to(ROOT)}"
        )
        return {
            "ok": True,
            "applied": True,
            "grid": grid,
            "cell_hash": params.get("cell_hash"),
            "winner": winner,
            "backup_path": str(backup_path.relative_to(ROOT)),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"grid/apply error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backups", summary="List param-backup snapshots")
async def grid_backups():
    backup_dir = ROOT / "data" / "param_backups"
    if not backup_dir.exists():
        return {"backups": []}
    items = []
    for p in sorted(backup_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "filename": p.name,
                "path": str(p.relative_to(ROOT)),
                "backup_ts_utc": data.get("backup_ts_utc"),
                "reason": data.get("reason"),
                "size_kb": round(p.stat().st_size / 1024, 2),
                "params": data.get("params", {}),
            })
        except Exception as e:
            logger.warning(f"grid/backups: failed to read {p}: {e}")
    return {"backups": items}


@router.post("/rollback", summary="Restore a previous param-backup snapshot")
async def grid_rollback(
    backup_filename: str = Body(..., embed=True, description="Just the filename, e.g. 2026-04-26_22-00-00_prod_v1_to_abc123.json"),
    confirm: bool = Body(False, embed=True),
):
    backup_dir = ROOT / "data" / "param_backups"
    # Reject path traversal — only the filename is accepted.
    if "/" in backup_filename or "\\" in backup_filename or backup_filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid backup_filename")
    path = backup_dir / backup_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"backup not found: {backup_filename}")
    try:
        backup = json.loads(path.read_text(encoding="utf-8"))
        restore = backup.get("params") or {}
        if not confirm:
            return {"ok": False, "applied": False, "would_restore": restore, "from": backup_filename}
        mod = _load_script_module()
        from src.core.database import NewsDB
        db = NewsDB()
        mod._apply(db, restore)
        logger.warning(f"♻️ [grid] Rolled back via API to {backup_filename}")
        return {"ok": True, "applied": True, "restored": restore, "from": backup_filename}
    except Exception as e:
        logger.error(f"grid/rollback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
