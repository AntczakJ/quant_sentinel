#!/usr/bin/env python3
"""
cleanup_db.py — Smart DB cleanup z analizą wpływu i backupem.

Tryby:
  --analyze (default)  — pokaż co by usunął, NIE usuwa nic
  --execute            — wykonaj cleanup (po backup)
  --reset-trades       — DODATKOWO wyczyść wszystkie trades (reset WR)
                         + cascade cleanup powiązanych tabel
                         + reset self-learning state

Backup: data/sentinel_backup_pre_cleanup_<timestamp>.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/sentinel.db")


def make_backup() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.parent / f"sentinel_backup_pre_cleanup_{ts}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup created: {backup_path}")
    return backup_path


# Always-stale: junk that no production code reads
ALWAYS_STALE_QUERIES = [
    ("users",
     "username LIKE 'test_user_%' OR username LIKE 'dup_user_%' OR username LIKE 'apikey_user_%'",
     "Test users (test_user_*, dup_user_*, apikey_user_*)"),
    ("dynamic_params",
     "param_name LIKE 'daily_report_%' AND param_value IS NULL AND param_text IS NULL",
     "Empty daily_report_* placeholders"),
    ("dynamic_params", "param_name LIKE '_test_%'",
     "_test_* leftover params"),
    ("dynamic_params", "param_name LIKE '%_defused_%' AND param_value IS NULL",
     "Empty defused_* params"),
    ("dynamic_params", "param_name = 'ab_test_state' AND param_value IS NULL",
     "Empty ab_test_state"),
    ("trades_audit", "1=1", "trades_audit (single debugging entry)"),
    ("pattern_stats", "pattern = 'TEST'", "TEST pattern_stats entry"),
    ("rejected_setups",
     "timestamp < datetime('now', '-14 days')",
     "rejected_setups older than 14d"),
    ("model_alerts",
     "timestamp < datetime('now', '-14 days')",
     "model_alerts older than 14d"),
    ("trailing_stop_log",
     "timestamp < datetime('now', '-14 days')",
     "trailing_stop_log older than 14d"),
    ("scanner_signals",
     "timestamp < datetime('now', '-30 days')",
     "scanner_signals older than 30d"),
    ("ml_predictions",
     "timestamp < datetime('now', '-14 days')",
     "ml_predictions older than 14d"),
]

RESET_TRADES_CASCADE = [
    ("trades", "1=1", "ALL trades (WR reset)"),
    ("ml_predictions", "1=1", "ALL ml_predictions (orphaned)"),
    ("trades_audit", "1=1", "ALL trades_audit"),
    ("trailing_stop_log", "1=1", "ALL trailing_stop_log"),
    ("pattern_stats", "1=1", "ALL pattern_stats (rebuilds from new trades)"),
    ("hourly_stats", "1=1", "ALL hourly_stats"),
    ("session_stats", "1=1", "ALL session_stats"),
    ("regime_stats", "1=1", "ALL regime_stats"),
    ("setup_quality_stats", "1=1", "ALL setup_quality_stats"),
    ("filter_performance", "1=1", "ALL filter_performance"),
    ("scanner_signals", "1=1", "ALL scanner_signals"),
    ("rejected_setups", "1=1", "ALL rejected_setups"),
    ("model_alerts", "1=1", "ALL model_alerts"),
    ("trade_journal", "1=1", "trade_journal"),
]

RESET_TRADES_DYNAMIC_PARAMS = {
    "kelly_reset_ts": str(int(datetime.now().timestamp())),
}


def analyze_table_impact(conn, table: str, where: str):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}")
    to_del = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = cur.fetchone()[0]
    return to_del, total - to_del


def run_cleanup(conn, queries, execute: bool = False):
    cur = conn.cursor()
    summary = []
    total_to_del = 0
    for table, where, label in queries:
        try:
            to_del, remaining = analyze_table_impact(conn, table, where)
            summary.append((table, label, to_del, remaining))
            total_to_del += to_del
            if execute and to_del > 0:
                cur.execute(f"DELETE FROM {table} WHERE {where}")
        except sqlite3.OperationalError as e:
            summary.append((table, f"{label} [SKIP: {e}]", 0, "?"))
    if execute:
        conn.commit()
        cur.execute("VACUUM")
    return {"summary": summary, "total_to_delete": total_to_del}


def reset_dynamic_params(conn, execute: bool = False):
    cur = conn.cursor()
    summary = []
    for name, value in RESET_TRADES_DYNAMIC_PARAMS.items():
        cur.execute(
            "SELECT param_value FROM dynamic_params WHERE param_name = ?", (name,)
        )
        row = cur.fetchone()
        old = row[0] if row else None
        summary.append((name, old, value))
        if execute:
            cur.execute(
                "INSERT OR REPLACE INTO dynamic_params (param_name, param_value, last_updated) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (name, value),
            )
    if execute:
        conn.commit()
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="actually run deletions (default: analyze only)")
    ap.add_argument("--reset-trades", action="store_true",
                    help="ADDITIONALLY wipe ALL trades + cascade for WR reset")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found")
        sys.exit(1)

    print(f"DB: {DB_PATH} ({DB_PATH.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"Mode: {'EXECUTE' if args.execute else 'ANALYZE ONLY'}")
    if args.reset_trades:
        print("** RESET-TRADES MODE — also wiping all trades + cascade **")
    print()

    if args.execute:
        make_backup()
    else:
        print("(no backup — analyze mode)")
    print()

    conn = sqlite3.connect(str(DB_PATH))

    print("=" * 70)
    print("PHASE 1: STALE DATA CLEANUP")
    print("=" * 70)
    res1 = run_cleanup(conn, ALWAYS_STALE_QUERIES, execute=args.execute)
    print(f"{'table':>22s} {'label':>52s} {'del':>6s} {'left':>6s}")
    for table, label, to_del, remain in res1["summary"]:
        print(f"{table:>22s} {label[:52]:>52s} {to_del:>6} {remain:>6}")
    print(f"{'TOTAL phase 1':>22s} {'':>52s} {res1['total_to_delete']:>6d}")

    if args.reset_trades:
        print()
        print("=" * 70)
        print("PHASE 2: RESET-TRADES CASCADE")
        print("=" * 70)
        res2 = run_cleanup(conn, RESET_TRADES_CASCADE, execute=args.execute)
        for table, label, to_del, remain in res2["summary"]:
            print(f"{table:>22s} {label[:52]:>52s} {to_del:>6} {remain:>6}")
        print(f"{'TOTAL phase 2':>22s} {'':>52s} {res2['total_to_delete']:>6d}")

        print()
        print("=" * 70)
        print("PHASE 3: RESET dynamic_params")
        print("=" * 70)
        res3 = reset_dynamic_params(conn, execute=args.execute)
        for name, old, new in res3:
            print(f"  {name:30s}: {str(old)[:25]} -> {str(new)[:25]}")

    conn.close()

    print()
    if args.execute:
        new_size = DB_PATH.stat().st_size / 1024 / 1024
        print(f"DB size after cleanup: {new_size:.2f} MB")
        print("Done.")
        if args.reset_trades:
            print()
            print("Po reset-trades zalecane:")
            print("  1. Restart API zeby przeladowal in-memory state")
            print("  2. (opcjonalnie) rm -f data/voter_accuracy_log.jsonl")
            print("  3. (opcjonalnie) rm -f data/shadow_predictions.jsonl")
    else:
        print("RUN WITH --execute to actually delete (analyze mode only).")


if __name__ == "__main__":
    main()
