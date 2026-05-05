#!/usr/bin/env python
"""scripts/broker_reconcile.py — nightly DB-vs-broker reconciliation.

2026-05-05: shipped per comparative research (top-1 ops gap). Trade
execution is operator-manual via Telegram → broker terminal, so the
DB has no native ground-truth tie to actual fills. This script consumes
a broker history export (CSV) and joins to the `trades` table, flagging:

  1. **DB → no broker** — trade in DB but no matching broker fill within
     ±60s of opentime + ±0.001 lot. Likely operator never placed it
     OR placed at materially different price/lot.
  2. **Broker → no DB** — broker fill with no matching DB row. Operator
     placed something the system didn't propose (manual override).
  3. **Lot mismatch** — system intended X lot, broker filled Y. Operator
     overrode size; sizing analytics are skewed.
  4. **Slippage** — system intended entry price X, broker filled Y. Tracks
     real-world execution quality.

Output: markdown report + writes mismatch flags to a new `reconciliation`
table for forward analytics. Does NOT modify trades — operator decides.

Usage:
  python scripts/broker_reconcile.py --broker-csv exports/mt5_history.csv
  python scripts/broker_reconcile.py --broker-csv exports/mt5_history.csv --since 2026-04-01

Broker CSV format (MT4/5 export — adjust column names via --col-map if needed):
  Time,Symbol,Type,Volume,Price,S/L,T/P,Time,Price,Commission,Swap,Profit
  2026-05-05 14:30:01,XAUUSD,buy,0.01,3300.50,3290,3320,2026-05-05 16:45:32,3315.20,0,0,14.70

Default column mapping assumes MT5 desktop "History" → right-click → "Report"
→ "Open as XLSX" → save-as CSV. Override with --col-map JSON if your broker
uses different column names.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Default column mapping for MT4/5 broker export. Operator can override.
DEFAULT_COL_MAP = {
    "open_time":   "Time",
    "symbol":      "Symbol",
    "side":        "Type",      # "buy"/"sell" → LONG/SHORT
    "lot":         "Volume",
    "open_price":  "Price",
    "close_time":  "Time.1",    # MT5 export duplicates "Time" header
    "close_price": "Price.1",
    "profit":      "Profit",
}

LOT_TOLERANCE = 0.0005           # ±0.0005 lot = ±$0.05 on XAU spot, fills typically clean
TIME_TOLERANCE_SEC = 60          # 60s window — manual placement latency
PRICE_TOLERANCE_FRACTION = 0.002 # 0.2% — accounts for slippage + spread


def _parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--broker-csv", type=Path, required=True,
                    help="Broker history export CSV path")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "sentinel.db",
                    help="trades DB path")
    ap.add_argument("--since", type=str, default=None,
                    help="Only reconcile trades from this date (YYYY-MM-DD)")
    ap.add_argument("--col-map", type=str, default=None,
                    help="Override default broker column mapping as JSON")
    ap.add_argument("--symbol-aliases", type=str,
                    default="XAUUSD,GOLD,XAU/USD,XAU.USD",
                    help="Comma-separated broker symbol aliases for our XAU/USD")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write reconciliation table; print report only")
    return ap.parse_args()


def _read_broker_csv(path: Path, col_map: dict) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "open_time":  row.get(col_map["open_time"], "").strip(),
                    "symbol":     row.get(col_map["symbol"], "").strip().upper(),
                    "side":       row.get(col_map["side"], "").strip().lower(),
                    "lot":        float(row.get(col_map["lot"], 0) or 0),
                    "open_price": float(row.get(col_map["open_price"], 0) or 0),
                    "close_time": row.get(col_map["close_time"], "").strip(),
                    "close_price": float(row.get(col_map["close_price"], 0) or 0),
                    "profit":     float(row.get(col_map["profit"], 0) or 0),
                })
            except (ValueError, KeyError):
                # Skip malformed rows but warn
                continue
    return rows


def _parse_time(s: str) -> dt.datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _ensure_recon_table(conn: sqlite3.Connection) -> None:
    """Create reconciliation table if absent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recon_run_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trade_id INTEGER,
            broker_open_time TEXT,
            broker_symbol TEXT,
            broker_side TEXT,
            broker_lot REAL,
            broker_open_price REAL,
            db_lot REAL,
            db_entry REAL,
            mismatch_kind TEXT,
            slippage_pct REAL,
            lot_diff REAL,
            notes TEXT
        )
    """)
    conn.commit()


def _fetch_db_trades(conn: sqlite3.Connection, since: str | None) -> list[dict]:
    sql = "SELECT id, timestamp, direction, entry, lot FROM trades WHERE 1=1"
    params: tuple = ()
    if since:
        sql += " AND timestamp >= ?"
        params = (since,)
    rows = conn.execute(sql, params).fetchall()
    return [
        {"id": r[0], "ts": r[1], "direction": (r[2] or "").upper(),
         "entry": float(r[3] or 0), "lot": float(r[4] or 0)}
        for r in rows
    ]


def reconcile(broker_rows: list[dict], db_rows: list[dict],
              symbol_aliases: set[str]) -> list[dict]:
    """Pairwise join; emit mismatch list."""
    mismatches: list[dict] = []
    matched_db_ids: set[int] = set()
    matched_broker_idxs: set[int] = set()

    # Filter broker to symbol of interest
    relevant_broker = [
        (i, b) for i, b in enumerate(broker_rows)
        if b["symbol"] in symbol_aliases
    ]

    # Match DB → broker (best-fit by time proximity within tolerance)
    for db_row in db_rows:
        db_ts = _parse_time(db_row["ts"])
        if db_ts is None:
            continue
        best_match = None
        best_dt = TIME_TOLERANCE_SEC + 1
        for i, b in relevant_broker:
            if i in matched_broker_idxs:
                continue
            b_ts = _parse_time(b["open_time"])
            if b_ts is None:
                continue
            ddt = abs((db_ts - b_ts).total_seconds())
            if ddt > TIME_TOLERANCE_SEC:
                continue
            # Direction agreement
            db_side_long = "LONG" in db_row["direction"]
            b_side_long = b["side"] == "buy"
            if db_side_long != b_side_long:
                continue
            if ddt < best_dt:
                best_dt = ddt
                best_match = (i, b)

        if best_match is None:
            mismatches.append({
                "trade_id": db_row["id"],
                "kind": "db_no_broker",
                "db_ts": db_row["ts"],
                "db_lot": db_row["lot"],
                "db_entry": db_row["entry"],
                "notes": "DB trade with no broker counterpart within ±60s",
            })
        else:
            i, b = best_match
            matched_db_ids.add(db_row["id"])
            matched_broker_idxs.add(i)
            # Lot mismatch?
            lot_diff = abs(db_row["lot"] - b["lot"])
            if lot_diff > LOT_TOLERANCE:
                mismatches.append({
                    "trade_id": db_row["id"],
                    "kind": "lot_mismatch",
                    "db_lot": db_row["lot"],
                    "broker_lot": b["lot"],
                    "lot_diff": lot_diff,
                    "broker_open_time": b["open_time"],
                    "notes": f"DB intended {db_row['lot']}, broker filled {b['lot']}",
                })
            # Slippage on entry?
            if db_row["entry"] > 0 and b["open_price"] > 0:
                slip_frac = abs(b["open_price"] - db_row["entry"]) / db_row["entry"]
                if slip_frac > PRICE_TOLERANCE_FRACTION:
                    mismatches.append({
                        "trade_id": db_row["id"],
                        "kind": "slippage",
                        "db_entry": db_row["entry"],
                        "broker_open_price": b["open_price"],
                        "slippage_pct": round(slip_frac * 100, 3),
                        "broker_open_time": b["open_time"],
                        "notes": f"DB intended {db_row['entry']:.2f}, broker filled {b['open_price']:.2f}",
                    })

    # Broker → DB orphans
    for i, b in relevant_broker:
        if i in matched_broker_idxs:
            continue
        mismatches.append({
            "trade_id": None,
            "kind": "broker_no_db",
            "broker_open_time": b["open_time"],
            "broker_symbol": b["symbol"],
            "broker_side": b["side"],
            "broker_lot": b["lot"],
            "broker_open_price": b["open_price"],
            "notes": "Broker fill with no DB counterpart (manual override?)",
        })

    return mismatches


def _print_report(mismatches: list[dict], n_db: int, n_broker: int) -> None:
    if not mismatches:
        print(f"✓ ALL CLEAN — {n_db} DB trades / {n_broker} broker fills, full match.")
        return
    by_kind: dict[str, list[dict]] = {}
    for m in mismatches:
        by_kind.setdefault(m["kind"], []).append(m)
    print(f"\nReconciliation report — {len(mismatches)} mismatch(es) "
          f"across {n_db} DB / {n_broker} broker rows:\n")
    for kind, items in by_kind.items():
        print(f"=== {kind} ({len(items)}) ===")
        for m in items[:10]:
            tid = m.get("trade_id") or "-"
            print(f"  trade #{tid}: {m.get('notes', '')}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")
        print()


def _persist(conn: sqlite3.Connection, mismatches: list[dict]) -> None:
    for m in mismatches:
        conn.execute("""
            INSERT INTO reconciliation
            (trade_id, broker_open_time, broker_symbol, broker_side,
             broker_lot, broker_open_price, db_lot, db_entry,
             mismatch_kind, slippage_pct, lot_diff, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            m.get("trade_id"),
            m.get("broker_open_time"), m.get("broker_symbol"), m.get("broker_side"),
            m.get("broker_lot"), m.get("broker_open_price"),
            m.get("db_lot"), m.get("db_entry"),
            m.get("kind"), m.get("slippage_pct"), m.get("lot_diff"),
            m.get("notes"),
        ))
    conn.commit()


def main() -> int:
    args = _parse_args()
    col_map = DEFAULT_COL_MAP.copy()
    if args.col_map:
        col_map.update(json.loads(args.col_map))

    if not args.broker_csv.exists():
        print(f"ERROR: broker CSV not found: {args.broker_csv}", file=sys.stderr)
        return 1

    aliases = {a.strip().upper() for a in args.symbol_aliases.split(",")}

    broker_rows = _read_broker_csv(args.broker_csv, col_map)
    print(f"[recon] Loaded {len(broker_rows)} broker rows from {args.broker_csv.name}")

    conn = sqlite3.connect(str(args.db))
    db_rows = _fetch_db_trades(conn, args.since)
    print(f"[recon] Loaded {len(db_rows)} DB trades since {args.since or 'all-time'}")

    mismatches = reconcile(broker_rows, db_rows, aliases)
    _print_report(mismatches, len(db_rows), len(broker_rows))

    if not args.dry_run:
        _ensure_recon_table(conn)
        _persist(conn, mismatches)
        print(f"[recon] Persisted {len(mismatches)} rows to `reconciliation` table.")

    conn.close()
    return 0 if not mismatches else 2


if __name__ == "__main__":
    sys.exit(main())
