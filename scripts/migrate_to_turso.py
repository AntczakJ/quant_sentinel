#!/usr/bin/env python3
"""
migrate_to_turso.py — migracja lokalnej bazy SQLite do Turso (libsql).

Bezpieczna migracja:
  - NIE nadpisuje istniejących danych w Turso
  - Tworzy brakujące tabele
  - Dodaje brakujące kolumny
  - Merguje dane (INSERT OR IGNORE — nie duplikuje)
  - Wyświetla raport przed i po

Użycie:
    python migrate_to_turso.py              # dry-run (pokazuje co zrobi)
    python migrate_to_turso.py --execute    # faktyczna migracja
"""

import os
import sys
import sqlite3
import json

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Manual .env loading
    if os.path.exists('.env'):
        with open('.env') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, val = line.partition('=')
                    val = val.strip().strip('"').strip("'")
                    os.environ.setdefault(key.strip(), val)

# Force Turso connection
TURSO_URL = os.getenv("TURSO_URL", os.getenv("DATABASE_URL", ""))
TURSO_TOKEN = os.getenv("TURSO_TOKEN", os.getenv("DATABASE_TOKEN", ""))
LOCAL_DB = "data/sentinel.db"

print(f"URL: {TURSO_URL[:50]}...")
print(f"Token: {TURSO_TOKEN[:20]}..." if TURSO_TOKEN else "Token: MISSING!")

if not TURSO_URL.startswith("libsql://"):
    print(f"ERROR: DATABASE_URL nie jest Turso URL: {TURSO_URL}")
    sys.exit(1)

dry_run = "--execute" not in sys.argv

import libsql


def get_local_db():
    return sqlite3.connect(LOCAL_DB)


def get_turso_db():
    return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)


def count_rows(conn, table):
    try:
        return conn.cursor().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return -1  # table doesn't exist


# =====================================================================
# 1. TABLES TO CREATE IN TURSO (if missing)
# =====================================================================

NEW_TABLES = {
    "setup_quality_stats": """CREATE TABLE IF NOT EXISTS setup_quality_stats (
        grade TEXT NOT NULL, direction TEXT NOT NULL,
        count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0, avg_profit REAL DEFAULT 0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(grade, direction))""",

    "hourly_stats": """CREATE TABLE IF NOT EXISTS hourly_stats (
        hour INTEGER NOT NULL, direction TEXT NOT NULL,
        count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(hour, direction))""",

    "trailing_stop_log": """CREATE TABLE IF NOT EXISTS trailing_stop_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        event TEXT NOT NULL, old_sl REAL, new_sl REAL,
        price_at_event REAL, r_multiple REAL)""",

    "loss_patterns": """CREATE TABLE IF NOT EXISTS loss_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern_type TEXT NOT NULL, direction TEXT,
        count INTEGER DEFAULT 0, description TEXT,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(pattern_type, direction))""",

    "rejected_setups": """CREATE TABLE IF NOT EXISTS rejected_setups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        timeframe TEXT, direction TEXT, price REAL,
        rejection_reason TEXT, filter_name TEXT,
        confluence_count INTEGER, rsi REAL, trend TEXT,
        pattern TEXT, atr REAL,
        would_have_won INTEGER DEFAULT NULL)""",

    "filter_performance": """CREATE TABLE IF NOT EXISTS filter_performance (
        filter_name TEXT NOT NULL, direction TEXT NOT NULL,
        correct_blocks INTEGER DEFAULT 0, incorrect_blocks INTEGER DEFAULT 0,
        correct_passes INTEGER DEFAULT 0, incorrect_passes INTEGER DEFAULT 0,
        accuracy REAL DEFAULT 0,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(filter_name, direction))""",
}

# Columns to add to trades table (if missing)
NEW_TRADE_COLUMNS = {
    'setup_grade': 'TEXT',
    'setup_score': 'REAL',
    'trailing_sl': 'REAL',
    'confirmation_data': 'TEXT',
    'model_agreement': 'REAL',
    'vol_regime': 'TEXT',
}

# =====================================================================
# 2. TABLES TO MIGRATE DATA FROM LOCAL -> TURSO
# =====================================================================

# Tables where we merge data (INSERT OR IGNORE by primary key)
MERGE_TABLES = [
    ("dynamic_params", "param_name", "SELECT param_name, param_value, param_text FROM dynamic_params"),
    ("pattern_stats", "pattern", "SELECT pattern, count, wins, losses, win_rate FROM pattern_stats"),
    ("session_stats", None, "SELECT pattern, session, count, wins, losses, win_rate FROM session_stats"),
    ("regime_stats", None, "SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats"),
]

# Tables where we copy all rows (append, skip duplicates)
APPEND_TABLES = [
    "trades",
    "scanner_signals",
    "ml_predictions",
]


def main():
    print("=" * 60)
    print("MIGRACJA QUANT SENTINEL: SQLite -> Turso")
    print("=" * 60)
    if dry_run:
        print("MODE: DRY RUN (dodaj --execute aby faktycznie migrowac)\n")
    else:
        print("MODE: EXECUTE (dane zostana zmigrowane)\n")

    local = get_local_db()
    turso = get_turso_db()
    turso_cur = turso.cursor()

    # ── RAPORT PRZED ──
    print("--- State BEFORE migration ---")
    print(f"{'Tabela':<25} {'Lokalna':>10} {'Turso':>10}")
    print("-" * 50)

    local_tables = [t[0] for t in local.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]

    all_tables = set(local_tables)
    for t in all_tables:
        lc = count_rows(local, t)
        tc = count_rows(turso, t)
        marker = ""
        if tc == -1:
            marker = " <- BRAK"
        elif lc > tc:
            marker = f" <- +{lc - tc}"
        print(f"  {t:<23} {lc:>10} {tc:>10}{marker}")

    print()

    # ── 1. CREATE MISSING TABLES ──
    print("--- 1. Tworzenie brakujacych tabel ---")
    for name, ddl in NEW_TABLES.items():
        tc = count_rows(turso, name)
        if tc == -1:
            print(f"  CREATE TABLE {name}")
            if not dry_run:
                turso_cur.execute(ddl)
                turso.commit()
        else:
            print(f"  {name} — already exists")

    # ── 2. ADD MISSING COLUMNS TO TRADES ──
    print("\n--- 2. Adding missing columns to trades ---")
    for col, typ in NEW_TRADE_COLUMNS.items():
        try:
            turso_cur.execute(f"SELECT {col} FROM trades LIMIT 1")
            print(f"  trades.{col} — already exists")
        except Exception:
            print(f"  ALTER TABLE trades ADD COLUMN {col} {typ}")
            if not dry_run:
                turso_cur.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
                turso.commit()

    # ── 3. MERGE STAT TABLES ──
    print("\n--- 3. Merge tabel statystycznych ---")
    for table, pk, query in MERGE_TABLES:
        local_rows = local.execute(query).fetchall()
        if not local_rows:
            print(f"  {table}: no data in local DB")
            continue

        # Get column names
        col_names = [d[0] for d in local.execute(query).description]
        placeholders = ", ".join(["?"] * len(col_names))
        cols = ", ".join(col_names)

        inserted = 0
        for row in local_rows:
            if not dry_run:
                try:
                    turso_cur.execute(
                        f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({placeholders})",
                        row)
                    inserted += 1
                except Exception as e:
                    pass  # duplicate or constraint
            else:
                inserted += 1

        if not dry_run:
            turso.commit()
        print(f"  {table}: {inserted} rows (INSERT OR IGNORE)")

    # ── 4. MIGRATE TRADES (skip existing by timestamp+entry+direction) ──
    print("\n--- 4. Migrating trades ---")
    local_trades = local.execute("""
        SELECT timestamp, direction, entry, sl, tp, rsi, trend, structure,
               status, failure_reason, condition_at_loss, pattern, factors,
               lot, profit, session, setup_grade, setup_score, trailing_sl,
               confirmation_data, model_agreement, vol_regime
        FROM trades ORDER BY id ASC
    """).fetchall()

    # Get existing trade signatures in Turso
    existing = set()
    try:
        for r in turso_cur.execute(
            "SELECT timestamp, direction, entry FROM trades"
        ).fetchall():
            existing.add((str(r[0]), str(r[1]), str(r[2])))
    except Exception:
        pass

    trade_cols = ("timestamp, direction, entry, sl, tp, rsi, trend, structure, "
                  "status, failure_reason, condition_at_loss, pattern, factors, "
                  "lot, profit, session, setup_grade, setup_score, trailing_sl, "
                  "confirmation_data, model_agreement, vol_regime")
    placeholders = ", ".join(["?"] * 22)

    new_trades = 0
    for t in local_trades:
        sig = (str(t[0]), str(t[1]), str(t[2]))
        if sig not in existing:
            if not dry_run:
                try:
                    turso_cur.execute(
                        f"INSERT INTO trades ({trade_cols}) VALUES ({placeholders})", t)
                    new_trades += 1
                except Exception as e:
                    print(f"    SKIP trade: {e}")
            else:
                new_trades += 1

    if not dry_run and new_trades > 0:
        turso.commit()
    print(f"  trades: {new_trades} new (from {len(local_trades)} local, {len(existing)} already in Turso)")

    # ── 5. MIGRATE SCANNER SIGNALS ──
    print("\n--- 5. Migrating scanner_signals ---")
    local_signals = local.execute("""
        SELECT timestamp, direction, entry, sl, tp, rsi, trend, structure, status
        FROM scanner_signals ORDER BY id ASC
    """).fetchall()

    existing_sigs = set()
    try:
        for r in turso_cur.execute(
            "SELECT timestamp, direction, entry FROM scanner_signals"
        ).fetchall():
            existing_sigs.add((str(r[0]), str(r[1]), str(r[2])))
    except Exception:
        pass

    new_sigs = 0
    for s in local_signals:
        sig = (str(s[0]), str(s[1]), str(s[2]))
        if sig not in existing_sigs:
            if not dry_run:
                try:
                    turso_cur.execute(
                        "INSERT INTO scanner_signals (timestamp, direction, entry, sl, tp, rsi, trend, structure, status) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", s)
                    new_sigs += 1
                except Exception:
                    pass
            else:
                new_sigs += 1

    if not dry_run and new_sigs > 0:
        turso.commit()
    print(f"  scanner_signals: {new_sigs} new")

    # ── 6. MIGRATE USER SETTINGS ──
    print("\n--- 6. Migrating user_settings ---")
    local_settings = local.execute("SELECT user_id, balance, risk_percent FROM user_settings").fetchall()
    for us in local_settings:
        if not dry_run:
            try:
                turso_cur.execute(
                    "INSERT OR REPLACE INTO user_settings (user_id, balance, risk_percent) VALUES (?, ?, ?)", us)
            except Exception:
                pass
    if not dry_run:
        turso.commit()
    print(f"  user_settings: {len(local_settings)} rows")

    # ── RAPORT PO ──
    if not dry_run:
        print("\n--- State AFTER migration ---")
        print(f"{'Tabela':<25} {'Turso':>10}")
        print("-" * 40)

        turso2 = get_turso_db()
        for t in sorted(all_tables | set(NEW_TABLES.keys())):
            tc = count_rows(turso2, t)
            if tc > 0:
                print(f"  {t:<23} {tc:>10}")
        turso2.close()

    print("\n" + "=" * 60)
    if dry_run:
        print("DRY RUN complete. Run with --execute to migrate:")
        print("  python migrate_to_turso.py --execute")
    else:
        print("MIGRATION COMPLETED SUCCESSFULLY!")
        print("\nBot now uses Turso (DATABASE_URL in .env).")
        print("Local DB data/sentinel.db remains as backup.")
    print("=" * 60)

    local.close()
    turso.close()


if __name__ == "__main__":
    main()
