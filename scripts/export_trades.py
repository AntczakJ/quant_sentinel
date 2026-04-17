#!/usr/bin/env python3
"""export_trades.py - Export trade journal to CSV or JSON.

Usage:
  python scripts/export_trades.py                     # CSV to stdout
  python scripts/export_trades.py -o trades.csv       # CSV to file
  python scripts/export_trades.py --json -o trades.json
  python scripts/export_trades.py --since 2026-04-16  # filter by date
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    for s in ("stdout", "stderr"):
        st = getattr(sys, s, None)
        if st and hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


COLUMNS = [
    "id", "timestamp", "direction", "entry", "sl", "tp", "status",
    "profit", "lot", "pattern", "session", "setup_grade", "setup_score",
    "spread_at_entry", "slippage", "vol_regime", "model_agreement",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=None, help="Output file (default: stdout)")
    ap.add_argument("--json", action="store_true", help="JSON format (default: CSV)")
    ap.add_argument("--since", default=None, help="Only trades after this date (YYYY-MM-DD)")
    ap.add_argument("--resolved-only", action="store_true", help="Exclude OPEN trades")
    args = ap.parse_args()

    from src.core.database import NewsDB
    db = NewsDB()

    where = []
    params = []
    if args.since:
        where.append("timestamp >= ?")
        params.append(args.since)
    if args.resolved_only:
        where.append("status IN ('WIN','LOSS','PROFIT','CLOSED')")

    sql = f"SELECT {', '.join(COLUMNS)} FROM trades"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"

    rows = db._query(sql, tuple(params) if params else ())
    if not rows:
        print("No trades found.", file=sys.stderr)
        return 0

    if args.json:
        data = [dict(zip(COLUMNS, r)) for r in rows]
        text = json.dumps(data, indent=2, default=str)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"Exported {len(data)} trades to {args.output}", file=sys.stderr)
        else:
            print(text)
    else:
        out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
        writer = csv.writer(out)
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow(r)
        if args.output:
            out.close()
            print(f"Exported {len(rows)} trades to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
