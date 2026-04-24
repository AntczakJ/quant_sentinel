#!/usr/bin/env python3
"""
scripts/rebuild_pattern_stats.py — Rebuild `pattern_stats` table from
the trades log after contamination (e.g. a loss-streak cohort polluted
the aggregate WR).

Usage:
    # Dry-run: print what would be written, don't commit
    python scripts/rebuild_pattern_stats.py --dry-run

    # Rebuild from ALL WIN/LOSS trades
    python scripts/rebuild_pattern_stats.py

    # Rebuild from trades AFTER a cutoff date (e.g. post-streak cohort only)
    python scripts/rebuild_pattern_stats.py --since 2026-04-23

    # Rebuild from trades AFTER a specific trade ID
    python scripts/rebuild_pattern_stats.py --after-id 189

Safety:
  - Backups the existing pattern_stats table to
    `data/backups/pattern_stats_backup_<ts>.json` before modifying.
  - Single sqlite transaction — rolls back on any error.
  - Dry-run mode prints everything but commits nothing.

The toxic_pattern filter in scanner.py reads pattern_stats directly, so
any rebuild takes effect on the next scanner cycle. No API restart
required.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DB_PATH = REPO_ROOT / "data" / "sentinel.db"
BACKUP_DIR = REPO_ROOT / "data" / "backups"


def backup_current(conn: sqlite3.Connection) -> Path:
    """Snapshot current pattern_stats to JSON before rebuild."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"pattern_stats_backup_{ts}.json"
    rows = conn.execute(
        "SELECT pattern, count, wins, losses, win_rate, last_updated "
        "FROM pattern_stats ORDER BY pattern"
    ).fetchall()
    data = [
        {
            "pattern": r[0], "count": r[1], "wins": r[2],
            "losses": r[3], "win_rate": r[4], "last_updated": r[5],
        }
        for r in rows
    ]
    with open(backup_path, "w") as f:
        json.dump(data, f, indent=2)
    return backup_path


def aggregate_trades(conn: sqlite3.Connection, since: str | None,
                     after_id: int | None) -> dict[str, dict]:
    """Aggregate trades by pattern. Returns {pattern: {wins, losses, ...}}."""
    where_parts = ["status IN ('WIN', 'LOSS')", "pattern IS NOT NULL"]
    params: list = []
    if since:
        where_parts.append("timestamp >= ?")
        params.append(since)
    if after_id is not None:
        where_parts.append("id > ?")
        params.append(after_id)
    where_sql = " AND ".join(where_parts)

    query = (
        f"SELECT pattern, status, profit, MAX(timestamp) OVER (PARTITION BY pattern) as latest "
        f"FROM trades WHERE {where_sql}"
    )
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.OperationalError:
        # Window functions not available — fall back to 2-pass
        rows = conn.execute(
            f"SELECT pattern, status, profit, timestamp FROM trades WHERE {where_sql}",
            params,
        ).fetchall()
        rows = [(r[0], r[1], r[2], r[3]) for r in rows]

    agg: dict[str, dict] = {}
    for r in rows:
        pat = r[0]
        st = r[1]
        if pat not in agg:
            agg[pat] = {
                "count": 0, "wins": 0, "losses": 0,
                "profit_sum": 0.0, "latest": None,
            }
        agg[pat]["count"] += 1
        if st == "WIN":
            agg[pat]["wins"] += 1
        elif st == "LOSS":
            agg[pat]["losses"] += 1
        agg[pat]["profit_sum"] += float(r[2] or 0)
        ts = r[3]
        if ts and (agg[pat]["latest"] is None or ts > agg[pat]["latest"]):
            agg[pat]["latest"] = ts

    for pat, a in agg.items():
        a["win_rate"] = a["wins"] / a["count"] if a["count"] else 0.0

    return agg


def write_rebuilt(conn: sqlite3.Connection, agg: dict[str, dict], dry_run: bool) -> None:
    if dry_run:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM pattern_stats")
    for pat, a in agg.items():
        conn.execute(
            "INSERT INTO pattern_stats (pattern, count, wins, losses, win_rate, last_updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pat, a["count"], a["wins"], a["losses"], round(a["win_rate"], 4),
             a["latest"] or now),
        )


def main():
    ap = argparse.ArgumentParser(description="Rebuild pattern_stats from trades log")
    ap.add_argument("--since", type=str, default=None,
                    help="Only include trades with timestamp >= this (e.g. 2026-04-23)")
    ap.add_argument("--after-id", type=int, default=None,
                    help="Only include trades with id > this")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change, don't commit")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    try:
        backup_path = backup_current(conn) if not args.dry_run else None

        agg = aggregate_trades(conn, args.since, args.after_id)
        if not agg:
            print("No matching trades found — nothing to rebuild.")
            return

        filter_desc = []
        if args.since:
            filter_desc.append(f"since={args.since}")
        if args.after_id is not None:
            filter_desc.append(f"after_id={args.after_id}")
        filter_str = " ".join(filter_desc) if filter_desc else "all trades"

        print(f"\n=== pattern_stats rebuild ({filter_str}) ===")
        print(f"{'pattern':40} {'n':>3}  {'W':>3} {'L':>3}  {'WR':>5}  latest")
        print("-" * 80)
        for pat in sorted(agg.keys(), key=lambda k: -agg[k]["count"]):
            a = agg[pat]
            print(f"{pat:40} {a['count']:>3}  {a['wins']:>3} {a['losses']:>3}  "
                  f"{a['win_rate']:>5.2f}  {a['latest']}")
        print()

        if args.dry_run:
            print("DRY RUN — no changes committed.")
        else:
            write_rebuilt(conn, agg, args.dry_run)
            conn.commit()
            print(f"✅ Rebuilt {len(agg)} patterns. Backup: {backup_path}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e} — rolled back", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
