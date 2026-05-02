"""
apply_factor_weight_tuning.py — proposed weight changes from factor_edge_report.

Based on cohort 2026-04-06 → 2026-05-02 (N=46 resolved trades, baseline
WR 19.6%):

  factor          n   WR     lift    current   proposed
  bos            15  40.0%  +20pp     1.598     1.800   (bump strongest factor)
  ichimoku_bear  16  31.2%  +12pp     0.926     1.150   (bump SHORT-favoring)
  fvg            12   8.3%  -11pp     1.281     0.700   (cut: predicts losses)
  killzone       12   8.3%  -11pp     1.137     0.700   (cut)
  ichimoku_bull  18  11.1%   -8pp     1.187     0.850   (cut: LONG-only trap)
  macro          20  10.0%  -10pp     1.108     0.800   (cut: LONG-only trap)

Reasoning:
  - bos: strongest factor by lift, deserves higher weight
  - ichimoku_bear: same logic, SHORT-only data so direction-routing helps
  - fvg + killzone: NEGATIVE lift = the factor flags LOSING setups more
    than winning ones. Reducing weight reduces their contribution to score.
  - ichimoku_bull + macro: 100% LONG-only samples, both lose in current
    bull-falling regime. May be regime-specific; reduce to limit damage
    in this regime, can revert when regime flips.

USAGE
    # Dry-run (default)
    python scripts/apply_factor_weight_tuning.py

    # Apply
    python scripts/apply_factor_weight_tuning.py --apply

    # Rollback latest apply
    python scripts/apply_factor_weight_tuning.py --rollback

CAUTION:
  - Current cohort N=46 is small. Wilson lower bounds:
    bos 19.8%, ichimoku_bear 14.2%, fvg 1.5%, killzone 1.5%
    fvg/killzone confidence intervals overlap baseline — these CUTs are
    less certain than the BUMPs.
  - Self-learner already auto-tunes weight_bos etc. via update_factor_weight.
    These tunings are NUDGES on top, not replacements. Self-learner will
    re-tune from these new starting points.
  - Restart API after --apply to ensure smc_engine reloads weights.

See reports/<DATE>_factor_edge.md for the source data.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sentinel.db"
BACKUP_DIR = REPO / "data" / "backups" / "factor_weights"

# Proposed nudges — derived from factor_edge_report (cohort 04-06 → 05-02)
PROPOSALS = {
    "weight_bos":           ("bump", 1.800),  # WR 40%, +20pp lift
    "weight_ichimoku_bear": ("bump", 1.150),  # WR 31%, +12pp, SHORT-only
    "weight_fvg":           ("cut",  0.700),  # WR 8%, -11pp
    "weight_killzone":      ("cut",  0.700),  # WR 8%, -11pp
    "weight_ichimoku_bull": ("cut",  0.850),  # WR 11%, LONG-only trap
    "weight_macro":         ("cut",  0.800),  # WR 10%, LONG-only trap
}


def snapshot(con: sqlite3.Connection) -> dict:
    cur = con.cursor()
    cur.execute(
        "SELECT param_name, param_value, last_updated "
        "FROM dynamic_params "
        "WHERE param_name IN (" + ",".join(["?"] * len(PROPOSALS)) + ")",
        list(PROPOSALS.keys()),
    )
    return {row[0]: {"value": row[1], "last_updated": row[2]} for row in cur.fetchall()}


def write_backup(snap: dict) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    path = BACKUP_DIR / f"factor_weights_{ts}.json"
    path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1

    if args.rollback:
        backups = sorted(BACKUP_DIR.glob("factor_weights_*.json"))
        if not backups:
            print("No backups to rollback from.")
            return 1
        latest = backups[-1]
        snap = json.loads(latest.read_text(encoding="utf-8"))
        print(f"Rolling back from {latest.name}:")
        con = sqlite3.connect(DB)
        try:
            for name, info in snap.items():
                con.execute(
                    "UPDATE dynamic_params SET param_value=?, last_updated=? "
                    "WHERE param_name=?",
                    (info["value"], info["last_updated"], name)
                )
                print(f"  {name} <- {info['value']}")
            con.commit()
        finally:
            con.close()
        return 0

    con = sqlite3.connect(DB)
    try:
        before = snapshot(con)
        print("=" * 60)
        print(f"Mode: {'APPLY (will write to DB)' if args.apply else 'DRY-RUN'}")
        print("=" * 60)
        print()
        print(f"{'param_name':30}{'current':>12}{'proposed':>12}{'kind':>10}")
        for name, (kind, new_val) in PROPOSALS.items():
            cur_info = before.get(name, {})
            cur_val = cur_info.get("value", "(insert)")
            cur_str = f"{cur_val:.4f}" if isinstance(cur_val, (int, float)) else cur_val
            print(f"{name:30}{cur_str:>12}{new_val:>12.4f}{kind:>10}")

        if not args.apply:
            print("\nDRY-RUN complete. Re-run with --apply.")
            return 0

        backup_path = write_backup(before)
        print(f"\nBackup: {backup_path}")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for name, (kind, new_val) in PROPOSALS.items():
            con.execute(
                "INSERT INTO dynamic_params(param_name, param_value, last_updated) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(param_name) DO UPDATE SET "
                "param_value=excluded.param_value, last_updated=excluded.last_updated",
                (name, new_val, ts)
            )
        con.commit()
        print(f"Applied {len(PROPOSALS)} factor weight nudges.")
        print("\nNext: restart API so smc_engine reloads weights on next inference.")
        print("Rollback: python scripts/apply_factor_weight_tuning.py --rollback")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
