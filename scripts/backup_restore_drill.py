#!/usr/bin/env python3
"""
scripts/backup_restore_drill.py — Validate that DB backups are restorable.

Non-destructive drill: creates backup, copies to tmp, validates integrity.
NEVER touches live data/sentinel.db except in read-only mode.

Run monthly (cron) to verify backup strategy still works.

Exit codes:
  0 = all backups verified
  1 = at least one backup failed integrity/query check
  2 = no backups found
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


def _find_backups(backup_dir: str = "data/backups") -> list[Path]:
    """Return list of backup files, sorted newest first."""
    bp = Path(backup_dir)
    if not bp.exists():
        return []
    return sorted(
        bp.glob("sentinel_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _verify_backup(path: Path) -> tuple[bool, str]:
    """Copy backup to tmp, run integrity check, query expected tables.

    Returns (ok, details_message).
    """
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / path.name
        try:
            shutil.copy2(path, dest)
        except Exception as e:
            return False, f"copy failed: {e}"

        try:
            conn = sqlite3.connect(str(dest))
            cur = conn.cursor()

            # 1. PRAGMA integrity_check
            result = cur.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                conn.close()
                return False, f"integrity: {result[0]}"

            # 2. Critical tables exist
            tables = {
                row[0] for row in
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            required = {"trades", "scanner_signals", "dynamic_params", "pattern_stats"}
            missing = required - tables
            if missing:
                conn.close()
                return False, f"missing tables: {missing}"

            # 3. Basic queries return results (schema is usable)
            try:
                trade_count = cur.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
                signal_count = cur.execute("SELECT COUNT(*) FROM scanner_signals").fetchone()[0]
            except sqlite3.Error as e:
                conn.close()
                return False, f"query failed: {e}"

            # 4. Indexes present (performance-critical)
            indexes = {
                row[0] for row in
                cur.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
            }
            conn.close()
            has_ts_idx = any("timestamp" in i for i in indexes)

            size_kb = path.stat().st_size / 1024
            details = (f"size={size_kb:.0f}KB trades={trade_count} "
                       f"signals={signal_count} indexes={len(indexes)}"
                       f"{' OKts-idx' if has_ts_idx else ' MISSINGNO-TS-IDX'}")
            return True, details
        except Exception as e:
            return False, f"exception: {type(e).__name__}: {e}"


def main():
    print("=" * 60)
    print("Backup Restore Drill")
    print("=" * 60)

    backups = _find_backups()
    if not backups:
        print("[FAIL] No backups found in data/backups/")
        print("       Run: python -c 'from src.ops.db_backup import create_backup; create_backup()'")
        sys.exit(2)

    # Verify up to 5 most recent
    to_check = backups[:5]
    print(f"Found {len(backups)} backups, verifying top {len(to_check)}\n")

    all_ok = True
    for i, path in enumerate(to_check, 1):
        ok, details = _verify_backup(path)
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {i}. {path.name} - {details}")
        if not ok:
            all_ok = False

    print()
    print("=" * 60)
    if all_ok:
        print(f"[PASS] All {len(to_check)} backup(s) verified restorable")
        sys.exit(0)
    else:
        print(f"[FAIL] At least one backup failed verification")
        print(f"       Do NOT rely on these for disaster recovery")
        sys.exit(1)


if __name__ == "__main__":
    main()
