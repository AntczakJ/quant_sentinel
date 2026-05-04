"""
scripts/archive_rejected_setups.py — archive old rejected_setups rows.

2026-05-04: largest table by row count (~14k rows). Most are >30 days
old and never queried by analytics (hot queries always filter recent).

Strategy:
1. Move rows older than --days-keep to rejected_setups_archive table
2. DELETE from rejected_setups
3. VACUUM (optional, --vacuum flag)

Hot table ~80% smaller after first archive run → faster scanner writes,
faster filter_precision_report queries.

Usage:
    python scripts/archive_rejected_setups.py --days-keep 30 [--vacuum] [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-keep", type=int, default=30,
                    help="Keep rows newer than N days in main table")
    ap.add_argument("--vacuum", action="store_true",
                    help="Run VACUUM after archive (slow on large DBs, optional)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default="data/sentinel.db")
    args = ap.parse_args()

    cutoff = (datetime.now() - timedelta(days=args.days_keep)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(ROOT / args.db)
    cur = conn.cursor()

    # Snapshot stats
    cur.execute("SELECT COUNT(*) FROM rejected_setups")
    total_before = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM rejected_setups WHERE timestamp < ?", (cutoff,))
    to_archive = cur.fetchone()[0]
    cur.execute("PRAGMA page_count")
    pages_before = cur.fetchone()[0]
    cur.execute("PRAGMA page_size")
    page_size = cur.fetchone()[0]
    size_mb_before = (pages_before * page_size) / (1024 * 1024)

    print(f"=== Archive rejected_setups (cutoff: {cutoff}) ===")
    print(f"Total rows: {total_before}")
    print(f"To archive: {to_archive} ({to_archive/max(1,total_before)*100:.1f}%)")
    print(f"DB size: {size_mb_before:.1f} MB")

    if to_archive == 0:
        print("Nothing to archive.")
        return

    if args.dry_run:
        print("DRY-RUN — no changes.")
        return

    # Create archive table if missing (same schema as rejected_setups)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rejected_setups_archive AS
        SELECT * FROM rejected_setups WHERE 0
    """)
    # Insert archived rows
    cur.execute("""
        INSERT INTO rejected_setups_archive
        SELECT * FROM rejected_setups WHERE timestamp < ?
    """, (cutoff,))
    archived = cur.rowcount
    # Delete from main table
    cur.execute("DELETE FROM rejected_setups WHERE timestamp < ?", (cutoff,))
    deleted = cur.rowcount
    conn.commit()

    print(f"Archived: {archived} rows")
    print(f"Deleted: {deleted} rows")

    if args.vacuum:
        print("Running VACUUM...")
        cur.execute("VACUUM")
        cur.execute("PRAGMA page_count")
        pages_after = cur.fetchone()[0]
        size_mb_after = (pages_after * page_size) / (1024 * 1024)
        print(f"DB size after VACUUM: {size_mb_after:.1f} MB (saved {size_mb_before - size_mb_after:.1f} MB)")

    conn.close()


if __name__ == "__main__":
    main()
