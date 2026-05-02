"""
apply_attention_rebalance.py — proposed hot-fix for attention-dominance.

Applies a SAFE weight rebalance to dynamic_params:
  attention 0.20 -> 0.10
  xgb       0.05 -> 0.20
  lstm      0.05 -> 0.15

Effect (after re-normalize): xgb 33% + lstm 25% = 58% combined,
attention 17%. Lets the higher-accuracy voters outvote the dominant
low-accuracy attention.

USAGE
-----
    # 1. Dry run (default) — prints proposed changes, does not write
    python scripts/apply_attention_rebalance.py

    # 2. Apply (creates timestamped backup of dynamic_params snapshot)
    python scripts/apply_attention_rebalance.py --apply

    # 3. Rollback last apply
    python scripts/apply_attention_rebalance.py --rollback

After --apply: also restart API for the in-memory cache to pick up
new weights (the fusion re-reads on every prediction, but a clean
restart avoids any stale state in attention.onnx loader). Janek must
restart manually:

    .venv/Scripts/python.exe -m uvicorn api.main:app \\
        --host 127.0.0.1 --port 8000 --log-level info \\
        > logs/api.log 2>&1 &

See memory/next_session_2026-05-02_priorities.md ROOT CAUSE section
for the diagnostic that motivated this fix.
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
BACKUP_DIR = REPO / "data" / "backups" / "weight_rebalance"

PROPOSED = {
    "ensemble_weight_attention": 0.10,
    "ensemble_weight_xgb": 0.20,
    "ensemble_weight_lstm": 0.15,
}


def snapshot(con: sqlite3.Connection) -> dict:
    cur = con.cursor()
    cur.execute(
        "SELECT param_name, param_value, last_updated "
        "FROM dynamic_params "
        "WHERE param_name LIKE 'ensemble_weight_%'"
    )
    return {
        row[0]: {"value": row[1], "last_updated": row[2]}
        for row in cur.fetchall()
    }


def write_backup(snap: dict) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    path = BACKUP_DIR / f"weights_{ts}.json"
    path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    return path


def normalize_view(weights: dict) -> dict:
    """Return raw + normalized weights for the 7 fusion keys."""
    fusion_keys = ["smc", "attention", "lstm", "xgb", "dqn", "deeptrans", "v2_xgb"]
    raw = {k: weights.get(f"ensemble_weight_{k}", {}).get("value", 0) for k in fusion_keys}
    total = sum(raw.values())
    norm = {k: (v / total if total > 0 else 0) for k, v in raw.items()}
    return raw, norm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    ap.add_argument("--rollback", action="store_true", help="Restore from latest backup")
    args = ap.parse_args()

    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1

    if args.rollback:
        backups = sorted(BACKUP_DIR.glob("weights_*.json"))
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
        print("Rolled back. Restart API to pick up old weights.")
        return 0

    con = sqlite3.connect(DB)
    try:
        before = snapshot(con)
        print("=" * 60)
        print(f"Mode: {'APPLY (will write to DB)' if args.apply else 'DRY-RUN (no writes)'}")
        print("=" * 60)
        print()
        print("Current weights (DB):")
        for name in sorted(before.keys()):
            info = before[name]
            print(f"  {name:35} = {info['value']:.4f} ({info['last_updated']})")
        raw, norm = normalize_view(before)
        print()
        print("Effective fusion weights (normalized over 7 fusion keys):")
        for k, v in norm.items():
            flag = " <-- DOMINANT" if v >= 0.30 else ""
            print(f"  {k:12} = {v:.4f}{flag}")

        print()
        print("Proposed changes:")
        for name, new_val in PROPOSED.items():
            old_val = before.get(name, {}).get("value")
            arrow = f"{old_val:.4f} -> {new_val:.4f}" if old_val is not None else f"insert {new_val:.4f}"
            print(f"  {name:35} {arrow}")

        # Compute proposed normalized state
        proposed_full = {k: dict(before[k]) for k in before}
        for name, new_val in PROPOSED.items():
            proposed_full.setdefault(name, {})["value"] = new_val
        raw_p, norm_p = normalize_view(proposed_full)
        print()
        print("Proposed effective fusion weights (normalized):")
        for k, v in norm_p.items():
            flag = " <-- DOMINANT" if v >= 0.30 else ""
            print(f"  {k:12} = {v:.4f}{flag}")

        if not args.apply:
            print()
            print("DRY-RUN complete. Re-run with --apply to write changes.")
            return 0

        # Apply
        backup_path = write_backup(before)
        print()
        print(f"Backup written: {backup_path}")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for name, new_val in PROPOSED.items():
            con.execute(
                "UPDATE dynamic_params SET param_value=?, last_updated=? "
                "WHERE param_name=?",
                (new_val, ts, name)
            )
        con.commit()
        print(f"Applied {len(PROPOSED)} weight changes.")
        print()
        print("Next step: restart API")
        print("    .venv/Scripts/python.exe -m uvicorn api.main:app \\")
        print("        --host 127.0.0.1 --port 8000 --log-level info \\")
        print("        > logs/api.log 2>&1 &")
        print()
        print("Then: monitor for 24h to see if SHORT setups start firing.")
        print("Rollback: python scripts/apply_attention_rebalance.py --rollback")
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
