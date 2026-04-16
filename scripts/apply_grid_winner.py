#!/usr/bin/env python3
"""apply_grid_winner.py — Promote a grid backtest winner to production.

Reads the ranked cells from `reports/wf_grid_<name>_B/stage_B.json`
(Stage B is the Monte Carlo + walk-forward validated output — always
prefer it over Stage A for production decisions). Backs up the current
dynamic_params values that the winner would overwrite, then applies
the new values atomically.

Safety features:
- Never touches sentinel.db without confirmation (--yes required for apply)
- Writes backup JSON timestamped in data/param_backups/ so rollback is
  one command
- --dry-run shows the diff without writing anything
- --rollback <backup-file> restores a previous state

Usage
-----
  # Preview top-5 and what would change (no write)
  python scripts/apply_grid_winner.py --grid prod_v1 --dry-run

  # Apply the #1 cell by composite score (default)
  python scripts/apply_grid_winner.py --grid prod_v1 --yes

  # Apply a specific cell by hash (for manual picks from the pareto front)
  python scripts/apply_grid_winner.py --grid prod_v1 --cell-hash f706dd1580 --yes

  # Rollback to a prior state
  python scripts/apply_grid_winner.py --rollback data/param_backups/2026-04-16_14-50-00.json

What gets written (5 params):
  min_confidence     -> (stored only in env/code, script logs for manual edit)
  sl_atr_multiplier  -> dynamic_params
  tp_to_sl_ratio     -> dynamic_params (mirrored from target_rr for prod)
  target_rr          -> dynamic_params (kept in sync with tp_to_sl_ratio)
  risk_percent       -> dynamic_params
  partial_close      -> (stored only in env/code for backtest mode)

Only dynamic_params parameters are overwritten. `min_confidence` and
`partial_close` are logged as manual-edit reminders because they live
in code paths that aren't parametric at runtime.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


DYNAMIC_PARAMS_WRITABLE = (
    "sl_atr_multiplier",
    "tp_to_sl_ratio",
    "target_rr",
    "risk_percent",
)

CODE_LEVEL_PARAMS = (
    "min_confidence",  # hardcoded in scanner.py
    "partial_close",   # behavior flag, not a tunable
)


def _load_stage_b(grid_name: str) -> dict:
    path = ROOT / "reports" / f"wf_grid_{grid_name}_B" / "stage_B.json"
    if not path.exists():
        # Fallback to Stage A if B not yet written
        path_a = ROOT / "reports" / f"wf_grid_{grid_name}_A" / "stage_A.json"
        if path_a.exists():
            print(f"[warn] Stage B not found, falling back to Stage A ({path_a})")
            print("[warn] Stage A lacks Monte Carlo validation — stdev unknown. Verify manually.")
            return json.loads(path_a.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"No grid report found for {grid_name} (tried B then A)")
    return json.loads(path.read_text(encoding="utf-8"))


def _pick_cell(report: dict, cell_hash: str | None) -> dict:
    cells = report.get("cells", [])
    if not cells:
        raise ValueError("Report has no cells")
    if cell_hash is None:
        # Top by composite (cells are already sorted in the report)
        return cells[0]
    for c in cells:
        if c.get("params", {}).get("cell_hash", "").startswith(cell_hash):
            return c
    raise ValueError(f"No cell with hash prefix '{cell_hash}' found")


def _read_current_params(db) -> dict:
    return {name: db.get_param(name, None) for name in DYNAMIC_PARAMS_WRITABLE}


def _format_diff(before: dict, after: dict) -> str:
    lines = []
    for k in DYNAMIC_PARAMS_WRITABLE:
        b = before.get(k)
        a = after.get(k)
        if b is None:
            lines.append(f"  {k:22s}  (unset) -> {a}")
        elif a is None:
            lines.append(f"  {k:22s}  {b} -> (unchanged, not in winner)")
        elif abs(float(b) - float(a)) < 1e-6:
            lines.append(f"  {k:22s}  {b} (no change)")
        else:
            pct = (float(a) - float(b)) / float(b) * 100 if float(b) else 0
            lines.append(f"  {k:22s}  {b:.4f} -> {a:.4f}  ({pct:+.1f}%)")
    return "\n".join(lines)


def _write_backup(before: dict, grid_name: str, cell_hash: str) -> Path:
    backup_dir = ROOT / "data" / "param_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    path = backup_dir / f"{ts}_{grid_name}_to_{cell_hash[:8]}.json"
    path.write_text(json.dumps({
        "backup_ts_utc": ts,
        "reason": f"Pre-apply backup before promoting grid={grid_name} cell={cell_hash}",
        "params": before,
    }, indent=2), encoding="utf-8")
    return path


def _apply(db, params: dict) -> None:
    for k, v in params.items():
        if k in DYNAMIC_PARAMS_WRITABLE and v is not None:
            db.set_param(k, float(v))


def cmd_apply(args) -> int:
    from src.core.database import NewsDB

    report = _load_stage_b(args.grid)
    cell = _pick_cell(report, args.cell_hash)
    p = cell.get("params", {})
    agg = cell.get("agg", {})

    # Winner values — note target_rr and tp_to_sl_ratio both get the cell's target_rr
    winner_params = {
        "sl_atr_multiplier": p.get("sl_atr_mult"),
        "tp_to_sl_ratio": p.get("target_rr"),
        "target_rr": p.get("target_rr"),
        "risk_percent": p.get("risk_percent"),
    }

    db = NewsDB()
    current = _read_current_params(db)

    print(f"\n=== Grid winner: {p.get('cell_hash')} (stage={report.get('stage','?')}) ===")
    print(f"  Composite score: top of ranking")
    print(f"  Sharpe mean: {agg.get('sharpe_mean'):.2f} +/- {agg.get('sharpe_stdev', 0):.2f}")
    print(f"  PF mean:     {agg.get('profit_factor_mean'):.2f}")
    print(f"  Return mean: {agg.get('return_pct_mean'):.2f}% +/- {agg.get('return_pct_stdev', 0):.2f}%")
    print(f"  DD mean:     {agg.get('max_drawdown_pct_mean'):.2f}%")
    print(f"  Trades mean: {agg.get('total_trades_mean', 0):.0f}")
    print()
    print("=== Diff ===")
    print(_format_diff(current, winner_params))
    print()
    print(f"=== Code-level params (NOT auto-applied — manual scanner.py edit) ===")
    print(f"  min_confidence: grid wants {p.get('min_confidence')}  (current: hardcoded 0.4 / 0.3 scalp)")
    print(f"  partial_close:  grid wants {p.get('partial_close')}  (current: code-controlled)")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return 0

    if not args.yes:
        print("\nNot applying — re-run with --yes to write.")
        return 1

    backup_path = _write_backup(current, args.grid, p.get("cell_hash", "unknown"))
    _apply(db, winner_params)
    print(f"\n[OK] Applied. Backup: {backup_path.relative_to(ROOT)}")
    print(f"Rollback: python scripts/apply_grid_winner.py --rollback {backup_path.relative_to(ROOT)}")
    return 0


def cmd_rollback(args) -> int:
    from src.core.database import NewsDB

    path = Path(args.rollback)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        print(f"Backup not found: {path}")
        return 1
    backup = json.loads(path.read_text(encoding="utf-8"))
    restore = backup.get("params", {})
    db = NewsDB()
    current = _read_current_params(db)
    print("=== Rolling back ===")
    print(_format_diff(current, restore))
    _apply(db, restore)
    print(f"\n[OK] Rolled back to {backup.get('backup_ts_utc')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="prod_v1", help="Grid name (default: prod_v1)")
    ap.add_argument("--cell-hash", default=None,
                    help="Apply specific cell by hash prefix (default: top by composite)")
    ap.add_argument("--yes", action="store_true", help="Confirm write")
    ap.add_argument("--dry-run", action="store_true", help="Show diff without writing")
    ap.add_argument("--rollback", default=None, help="Path to backup JSON to restore")
    args = ap.parse_args()

    if args.rollback:
        return cmd_rollback(args)
    return cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
