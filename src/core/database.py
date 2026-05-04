"""
database.py - warstwa dostepu do bazy danych SQLite lub Turso (libsql).

Wszystkie operacje SELECT korzystaja z _query() / _query_one() (thread-safe).
Operacje INSERT/UPDATE/DELETE korzystaja z _execute() (thread-safe + auto-commit).
"""

import os
import json
import datetime
import threading
from typing import Any, Optional, List

from src.core.logger import logger

# ======================== DATABASE CONNECTION ========================
#
# Dual-write architecture:
#   PRIMARY  = local SQLite (fast reads, training data, everything)
#   SECONDARY = Turso cloud (optional sync for trades, signals, portfolio)
#
# Tables synced to Turso (production data):
#   trades, scanner_signals, dynamic_params, pattern_stats, session_stats,
#   regime_stats, setup_quality_stats, trades_audit, processed_news
#
# Tables LOCAL ONLY (training/debug — too large or too frequent for cloud):
#   ml_predictions, news_sentiment, trailing_stop_log, loss_patterns,
#   rejected_setups, filter_performance, hourly_stats

DATABASE_URL = os.getenv("DATABASE_URL", "data/sentinel.db")
TURSO_URL = os.getenv("TURSO_URL", "")
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")

# RLock (re-entrant) instead of plain Lock — same thread can legitimately
# re-enter the critical section when a locked helper calls another locked
# helper (e.g. _execute → set_param inside a triggered migration path).
# Plain Lock would deadlock on re-entry; RLock tracks owner and increments
# a counter on nested acquires.
_db_lock = threading.RLock()
_DB_LOCK_TIMEOUT = 5.0  # seconds — prevent indefinite hangs

# Tables that sync to Turso (production-critical data)
_TURSO_SYNC_TABLES = {
    "trades", "scanner_signals", "dynamic_params", "pattern_stats",
    "session_stats", "regime_stats", "setup_quality_stats", "trades_audit",
    "processed_news", "agent_threads", "trade_journal", "trades_archive",
}

# Tables that stay local only
_LOCAL_ONLY_TABLES = {
    "ml_predictions", "news_sentiment", "trailing_stop_log", "loss_patterns",
    "rejected_setups", "filter_performance", "hourly_stats", "model_alerts",
}


class _DBLockContext:
    """Context manager for database lock with timeout."""
    def __enter__(self):
        if not _db_lock.acquire(timeout=_DB_LOCK_TIMEOUT):
            raise TimeoutError(f"Database lock timeout after {_DB_LOCK_TIMEOUT}s — possible deadlock")
        return self

    def __exit__(self, *args):
        _db_lock.release()


def _db_locked():
    return _DBLockContext()


# ── Primary: always local SQLite ──
import sqlite3
os.makedirs(os.path.dirname(DATABASE_URL) or ".", exist_ok=True)
_conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
_cursor = _conn.cursor()
_using_sqlite = True

# 2026-05-04: PRAGMA optimization per DB performance audit.
# - journal_mode=WAL (already default but explicit) — enables concurrent reads/single writer
# - synchronous=NORMAL — ~40% faster writes vs FULL, WAL keeps durability across crashes
# - cache_size=-65536 — 64MB SQLite cache for repeated queries
# - mmap_size=268435456 — 256MB memory-mapped I/O for read-heavy analytics
# - temp_store=MEMORY — temp tables (json_each, etc.) in RAM
# - wal_autocheckpoint=1000 — ~4MB WAL before auto-checkpoint
try:
    for _pragma in [
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA cache_size=-65536",
        "PRAGMA mmap_size=268435456",
        "PRAGMA temp_store=MEMORY",
        "PRAGMA wal_autocheckpoint=1000",
    ]:
        _cursor.execute(_pragma)
    _conn.commit()
except Exception as _pe:
    logger.warning(f"PRAGMA tuning failed (non-fatal): {_pe}")

logger.info(f"Primary database: {DATABASE_URL}")

# ── Secondary: Turso cloud (optional) ──
_turso_conn = None
_turso_cursor = None

if TURSO_URL and TURSO_URL.startswith("libsql://"):
    # 2026-05-04 audit (DB+storage+APIs deep audit) found Turso has
    # NEGATIVE value: 500ms+ latency per scanner cycle, silent sync
    # failure mode, NO read benefit (all reads go to local), NO backup
    # for libsql:// URLs, schema drift risk. Recommendation: drop.
    # Now env-gated: set QUANT_DISABLE_TURSO=1 to skip Turso entirely.
    # Set to "0" or unset to keep legacy dual-write behavior (rollback).
    if os.environ.get("QUANT_DISABLE_TURSO", "").strip() == "1":
        logger.info("Turso sync DISABLED via QUANT_DISABLE_TURSO=1")
    else:
        try:
            import libsql
            _turso_conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN) if TURSO_TOKEN else libsql.connect(TURSO_URL)
            _turso_cursor = _turso_conn.cursor()
            logger.info(f"Secondary database (Turso): {TURSO_URL[:50]}...")
        except ImportError:
            logger.info("Turso sync disabled (libsql not installed)")
        except Exception as e:
            logger.warning(f"Turso connection failed: {e} — running local only")


def _should_sync_to_turso(sql: str) -> bool:
    """Check if this SQL statement should be replicated to Turso."""
    if not _turso_conn:
        return False
    sql_upper = sql.strip().upper()
    # Only sync writes (INSERT, UPDATE, DELETE) and schema changes
    if not sql_upper.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
        return False
    # Check if target table is in sync list
    for table in _TURSO_SYNC_TABLES:
        if table.upper() in sql_upper:
            return True
    return False

# ======================== DATABASE CLASS ========================

_db_initialized = False


def _reinit_connection_for_test():
    """Test-only helper: reopens the module-level _conn against the current
    os.environ['DATABASE_URL']. Without this, tests that mock DATABASE_URL
    via monkeypatch.setenv are silently ignored because `_conn` was
    opened once at module import time with whatever env was then.

    Called from tests/conftest.py autouse fixture. Production code never
    touches this — the expensive part (schema create + migrate) runs only
    if target DB is fresh.
    """
    global _conn, _cursor, _db_initialized, DATABASE_URL
    new_url = os.getenv("DATABASE_URL", "data/sentinel.db")
    if new_url == DATABASE_URL:
        return  # no change
    try:
        _conn.close()
    except Exception:
        pass
    DATABASE_URL = new_url
    os.makedirs(os.path.dirname(DATABASE_URL) or ".", exist_ok=True)
    _conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    _cursor = _conn.cursor()
    _db_initialized = False  # trigger create_tables() + migrate() on next NewsDB()


class NewsDB:
    def __init__(self):
        global _db_initialized
        self.conn = _conn
        self.cursor = _cursor
        if not _db_initialized:
            self.create_tables()
            self.migrate()
            _db_initialized = True

    def _execute(self, sql: str, params: tuple = (), _silent: bool = False):
        """Execute SQL, committing if needed. Thread-safe. Dual-write to Turso if applicable."""
        with _db_locked():
            try:
                self.cursor.execute(sql, params)
                if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
                    self.conn.commit()
            except Exception as e:
                if not _silent:
                    logger.error(f"Database error: {e}\nSQL: {sql}\nParams: {params}")
                raise

        # Async-ish sync to Turso (best-effort, never blocks primary)
        if _should_sync_to_turso(sql):
            try:
                if _turso_cursor is not None and _turso_conn is not None:
                    _turso_cursor.execute(sql, params)
                    _turso_conn.commit()
            except Exception as e:
                logger.debug(f"Turso sync failed (non-critical): {e}")

    def _insert_returning_id(self, sql: str, params: tuple = ()) -> int:
        """INSERT and return last_insert_rowid atomically (under the same lock). Dual-write."""
        with _db_locked():
            try:
                self.cursor.execute(sql, params)
                self.conn.commit()
                self.cursor.execute("SELECT last_insert_rowid()")
                row = self.cursor.fetchone()
                row_id = row[0] if row else 0
            except Exception as e:
                logger.error(f"Database error: {e}\nSQL: {sql}\nParams: {params}")
                raise

        if _should_sync_to_turso(sql):
            try:
                if _turso_cursor is not None and _turso_conn is not None:
                    _turso_cursor.execute(sql, params)
                    _turso_conn.commit()
            except Exception as e:
                logger.debug(f"Turso sync failed (non-critical): {e}")

        return row_id

    def _query(self, sql: str, params: tuple = ()) -> list:  # type: ignore[override]
        """Execute a SELECT query thread-safely and return all rows."""
        with _db_locked():
            self.cursor.execute(sql, params)
            return list(self.cursor.fetchall())

    def _query_one(self, sql: str, params: tuple = ()) -> Optional[tuple]:  # type: ignore[override]
        """Execute a SELECT query thread-safely and return first row."""
        with _db_locked():
            self.cursor.execute(sql, params)
            return self.cursor.fetchone()  # type: ignore[no-any-return]

    def get_portfolio_params(self) -> dict:
        rows = self._query("SELECT param_name, param_value, param_text FROM dynamic_params WHERE param_name LIKE 'portfolio_%'")
        result = {}
        for name, num_val, text_val in rows:
            result[name] = text_val if text_val is not None else num_val
        # Track bulk reads in the schema layer so the drift watchdog sees
        # them; otherwise portfolio_* keys would falsely appear as
        # "write_only".
        try:
            from src.core.dynamic_params_schema import track_read
            for name in result.keys():
                track_read(name)
        except Exception:
            pass
        return result

    def create_tables(self):
        self._execute("CREATE TABLE IF NOT EXISTS processed_news (title_hash TEXT PRIMARY KEY)")
        self._execute("CREATE TABLE IF NOT EXISTS user_settings (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 1000.0, risk_percent REAL DEFAULT 1.0)")
        self._execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            direction TEXT, entry REAL, sl REAL, tp REAL, rsi REAL, trend TEXT,
            structure TEXT DEFAULT 'Stable', status TEXT DEFAULT 'OPEN',
            failure_reason TEXT, condition_at_loss TEXT, pattern TEXT, factors TEXT,
            lot REAL, profit REAL, session TEXT)""")
        self._execute("""CREATE TABLE IF NOT EXISTS scanner_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            direction TEXT, entry REAL, sl REAL, tp REAL, rsi REAL, trend TEXT,
            structure TEXT, status TEXT DEFAULT 'PENDING')""")
        self._execute("""CREATE TABLE IF NOT EXISTS pattern_stats (
            pattern TEXT PRIMARY KEY, count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, win_rate REAL DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        self._execute("""CREATE TABLE IF NOT EXISTS dynamic_params (
            param_name TEXT PRIMARY KEY, param_value REAL, param_text TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        self._execute("""CREATE TABLE IF NOT EXISTS session_stats (
            pattern TEXT, session TEXT, count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, win_rate REAL DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (pattern, session))""")
        self._execute("""CREATE TABLE IF NOT EXISTS agent_threads (
            user_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_used DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        # ml_predictions has legacy per-model columns (lstm_pred, xgb_pred,
        # dqn_action) for fast filtering; newer voters are added as nullable
        # columns by the migration block below so the schema evolves without
        # rewriting historical rows.
        self._execute("""CREATE TABLE IF NOT EXISTS ml_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            trade_id INTEGER, lstm_pred REAL, xgb_pred REAL, dqn_action INTEGER,
            ensemble_score REAL, ensemble_signal TEXT, confidence REAL, predictions_json TEXT,
            smc_pred REAL, attention_pred REAL, dpformer_pred REAL, deeptrans_pred REAL,
            v2_xgb_pred REAL)""")
        self._execute("""CREATE TABLE IF NOT EXISTS regime_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT NOT NULL, session TEXT NOT NULL,
            direction TEXT NOT NULL, count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, win_rate REAL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(regime, session, direction))""")
        self._execute("""CREATE TABLE IF NOT EXISTS news_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            headline TEXT, sentiment TEXT, score REAL, source TEXT)""")
        # ── NOWE TABELE: Setup Quality, Hourly Stats, Trailing Stop ──
        self._execute("""CREATE TABLE IF NOT EXISTS setup_quality_stats (
            grade TEXT NOT NULL, direction TEXT NOT NULL,
            count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0, avg_profit REAL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(grade, direction))""")
        self._execute("""CREATE TABLE IF NOT EXISTS hourly_stats (
            hour INTEGER NOT NULL, direction TEXT NOT NULL,
            count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(hour, direction))""")
        self._execute("""CREATE TABLE IF NOT EXISTS trailing_stop_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event TEXT NOT NULL, old_sl REAL, new_sl REAL,
            price_at_event REAL, r_multiple REAL)""")
        self._execute("""CREATE TABLE IF NOT EXISTS loss_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL, direction TEXT,
            count INTEGER DEFAULT 0, description TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pattern_type, direction))""")
        # ── REJECTED SETUPS — śledzenie odrzuconych trade'ów ──
        self._execute("""CREATE TABLE IF NOT EXISTS rejected_setups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            timeframe TEXT, direction TEXT, price REAL,
            rejection_reason TEXT, filter_name TEXT,
            confluence_count INTEGER, rsi REAL, trend TEXT,
            pattern TEXT, atr REAL,
            would_have_won INTEGER DEFAULT NULL)""")
        # ── FILTER PERFORMANCE — skuteczność każdego filtra ──
        self._execute("""CREATE TABLE IF NOT EXISTS filter_performance (
            filter_name TEXT NOT NULL, direction TEXT NOT NULL,
            correct_blocks INTEGER DEFAULT 0, incorrect_blocks INTEGER DEFAULT 0,
            correct_passes INTEGER DEFAULT 0, incorrect_passes INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(filter_name, direction))""")
        # ── MODEL ALERTS — persisted drift/accuracy/calibration alerts ──
        self._execute("""CREATE TABLE IF NOT EXISTS model_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            model_name TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            psi_value REAL,
            resolved BOOLEAN DEFAULT 0)""")
        # ── MACRO SNAPSHOTS — per-cycle persistence of macro_regime + USDJPY z-score
        # so historical regime data is queryable for audits (e.g. "did B7
        # actually fire on every SHORT in zielony?", "what was the regime
        # mix during the loss streak?"). Written each BG scanner cycle by
        # api/main.py::_persist_macro_snapshot. Index on timestamp for
        # range queries; macro_regime for grouped stats. ~1 row / 5 min ≈
        # 288 rows / day = 100k / year — fine for SQLite.
        self._execute("""CREATE TABLE IF NOT EXISTS macro_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            macro_regime TEXT,
            usdjpy_zscore REAL,
            usdjpy_price REAL,
            atr_ratio REAL,
            uup REAL,
            tlt REAL,
            vixy REAL,
            market_regime TEXT,
            signals_json TEXT)""")
        self._execute("CREATE INDEX IF NOT EXISTS idx_macro_snapshots_ts "
                      "ON macro_snapshots(timestamp)")
        self._execute("CREATE INDEX IF NOT EXISTS idx_macro_snapshots_regime "
                      "ON macro_snapshots(macro_regime)")
        # ── TRADE JOURNAL — rationale, emotions, lessons per trade ──
        self._execute("""CREATE TABLE IF NOT EXISTS trade_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            rationale TEXT,
            emotion TEXT,
            lesson TEXT,
            notes TEXT,
            FOREIGN KEY (trade_id) REFERENCES trades(id))""")

    def migrate(self):
        needed = {'pattern': 'TEXT', 'failure_reason': 'TEXT', 'condition_at_loss': 'TEXT',
                  'factors': 'TEXT', 'session': 'TEXT', 'lot': 'REAL', 'profit': 'REAL',
                  'setup_grade': 'TEXT', 'setup_score': 'REAL', 'trailing_sl': 'REAL',
                  'confirmation_data': 'TEXT', 'model_agreement': 'REAL',
                  'vol_regime': 'TEXT'}
        for col, typ in needed.items():
            try:
                with _db_locked():
                    self.cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
                    self.conn.commit()
                logger.info(f"Migration: added column trades.{col}")
            except Exception as e:
                err_msg = str(e).lower()
                if "duplicate" not in err_msg and "already exists" not in err_msg:
                    logger.debug(f"Migration skip trades.{col}: {e}")

        # Add param_text column to dynamic_params for text/JSON values
        try:
            with _db_locked():
                self.cursor.execute("ALTER TABLE dynamic_params ADD COLUMN param_text TEXT")
                self.conn.commit()
            logger.info("Migration: added column dynamic_params.param_text")
        except Exception as e:
            err_msg = str(e).lower()
            if "duplicate" not in err_msg and "already exists" not in err_msg:
                logger.debug(f"Migration skip dynamic_params.param_text: {e}")

        # Per-voter columns on ml_predictions — idempotent ALTER for DBs
        # created before the ensemble grew past lstm/xgb/dqn. predictions_json
        # already stores the full payload; these columns are for cheap SQL
        # filtering / joins without JSON parsing.
        for col in ("smc_pred", "attention_pred", "dpformer_pred", "deeptrans_pred", "v2_xgb_pred"):
            try:
                with _db_locked():
                    self.cursor.execute(f"ALTER TABLE ml_predictions ADD COLUMN {col} REAL")
                    self.conn.commit()
                logger.info(f"Migration: added column ml_predictions.{col}")
            except Exception as e:
                err_msg = str(e).lower()
                if "duplicate" not in err_msg and "already exists" not in err_msg:
                    logger.debug(f"Migration skip ml_predictions.{col}: {e}")

        # Migrate text values from param_value to param_text
        try:
            self._execute("""
                UPDATE dynamic_params SET param_text = param_value, param_value = NULL
                WHERE param_name LIKE '%_text' OR param_name = 'portfolio_history'
            """, _silent=True)
        except Exception:
            pass

        # Normalize legacy "PROFIT" status to "WIN" for consistency
        try:
            migrated = self._query_one("SELECT COUNT(*) FROM trades WHERE status = 'PROFIT'")
            if migrated and migrated[0] > 0:
                self._execute("UPDATE trades SET status = 'WIN' WHERE status = 'PROFIT'")
                self._execute("UPDATE scanner_signals SET status = 'WIN' WHERE status = 'PROFIT'", _silent=True)
                # Rebuild stats since status values changed
                self.rebuild_all_stats()
                logger.info(f"Migration: normalized {migrated[0]} PROFIT→WIN, rebuilt stats")
        except Exception:
            pass

        # Normalize session names: old 3-session → new 5-session format
        session_map = {"Asia": "asian", "London": "london", "NewYork": "new_york"}
        for old_name, new_name in session_map.items():
            try:
                self._execute("UPDATE trades SET session=? WHERE session=?", (new_name, old_name))
                self._execute("UPDATE session_stats SET session=? WHERE session=?", (new_name, old_name), _silent=True)
            except Exception:
                pass

        # Backfill NULL sessions from timestamps
        try:
            null_sessions = self._query("SELECT id, timestamp FROM trades WHERE session IS NULL AND timestamp IS NOT NULL")
            for row in (null_sessions or []):
                session = self.get_session(row[1])
                if session and session != 'unknown':
                    self._execute("UPDATE trades SET session=? WHERE id=?", (session, row[0]))
            if null_sessions:
                logger.info(f"Migration: backfilled {len(null_sessions)} NULL sessions")
        except Exception:
            pass

        # Backfill audit columns (filled_entry/filled_sl) for historical resolved trades
        try:
            missing = self._query(
                "SELECT id, entry, sl, tp, status FROM trades "
                "WHERE status IN ('WIN','LOSS') AND filled_entry IS NULL AND entry IS NOT NULL"
            )
            for row in (missing or []):
                t_id, entry, sl, tp, status = row
                filled_tp = tp if status == 'WIN' else None
                self._execute(
                    "UPDATE trades SET filled_entry=?, filled_sl=?, filled_tp=?, "
                    "slippage=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (entry, sl, filled_tp, t_id)
                )
            if missing:
                logger.info(f"Migration: backfilled audit columns for {len(missing)} trades")
        except Exception:
            pass

        try:
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_pattern ON trades(pattern)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_status_ts ON trades(status, timestamp DESC)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_scanner_timestamp ON scanner_signals(timestamp)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_scanner_status ON scanner_signals(status)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_scanner_status_ts ON scanner_signals(status, timestamp DESC)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_pattern_stats_win_rate ON pattern_stats(win_rate)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_dynamic_params_name ON dynamic_params(param_name)")
            # Additional indexes for frequently queried columns
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_direction ON trades(direction)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_trades_profit ON trades(profit)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_scanner_direction ON scanner_signals(direction)")
            # ml_predictions: largest table (4k+ rows), queried by timestamp
            # for recent fetch + JOIN to trades for regime accuracy analysis.
            self._execute("CREATE INDEX IF NOT EXISTS idx_ml_pred_timestamp ON ml_predictions(timestamp DESC)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_ml_pred_trade_id ON ml_predictions(trade_id)")
            # 2026-05-04: missing rejected_setups timestamp index identified
            # by DB perf audit. WHERE timestamp > '2026-04-01' was full-scan
            # on 14k rows (13.49ms → ~0.5ms with index, 26x speedup).
            self._execute("CREATE INDEX IF NOT EXISTS idx_rejected_timestamp ON rejected_setups(timestamp)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_rejected_filter ON rejected_setups(filter_name)")
            self._execute("CREATE INDEX IF NOT EXISTS idx_ml_pred_timestamp_trade ON ml_predictions(timestamp, trade_id)")
            # rejected_setups: queried by filter_name for filter accuracy
            self._execute("CREATE INDEX IF NOT EXISTS idx_rejected_filter ON rejected_setups(filter_name)")
        except Exception as e:
            logger.warning(f"Index creation: {e}")

        # --- Phase 4: Audit trail ---
        # Add execution quality columns to trades
        audit_cols = {
            'filled_entry': 'REAL', 'filled_sl': 'REAL', 'filled_tp': 'REAL',
            'slippage': 'REAL', 'spread_at_entry': 'REAL',
            'updated_at': 'TIMESTAMP',
        }
        for col, typ in audit_cols.items():
            try:
                with _db_locked():
                    self.cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
                    self.conn.commit()
            except Exception:
                pass  # column already exists

        # trades_audit table — tracks every status change with hash chain
        self._execute("""CREATE TABLE IF NOT EXISTS trades_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL,
            old_status TEXT,
            new_status TEXT,
            field_changed TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            prev_hash TEXT,
            entry_hash TEXT
        )""")
        self._execute("CREATE INDEX IF NOT EXISTS idx_audit_trade ON trades_audit(trade_id)")
        # Add hash columns if table already exists without them
        for col in ('prev_hash', 'entry_hash'):
            try:
                with _db_locked():
                    self.cursor.execute(f"ALTER TABLE trades_audit ADD COLUMN {col} TEXT")
                    self.conn.commit()
            except Exception:
                pass

    def log_trade_audit(self, trade_id: int, old_status: str, new_status: str,
                        field_changed: str = "status", old_value: str = "",
                        new_value: str = "", reason: str = ""):
        """Record a change to a trade for audit trail."""
        try:
            self._execute(
                "INSERT INTO trades_audit (trade_id, old_status, new_status, field_changed, old_value, new_value, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (trade_id, old_status, new_status, field_changed, old_value, new_value, reason)
            )
        except (AttributeError, TypeError) as e:
            logger.debug(f"Audit log failed: {e}")

    def get_trade_audit(self, trade_id: int) -> list:
        """Get audit history for a specific trade."""
        return self._query(
            "SELECT * FROM trades_audit WHERE trade_id = ? ORDER BY timestamp",
            (trade_id,)
        )

    def get_agent_thread(self, user_id: str) -> Optional[str]:
        try:
            row = self._query_one("SELECT thread_id FROM agent_threads WHERE user_id = ?", (str(user_id),))
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"get_agent_thread error: {e}")
            return None

    def set_agent_thread(self, user_id: str, thread_id: str) -> None:
        self._execute("INSERT OR REPLACE INTO agent_threads (user_id, thread_id, last_used) VALUES (?, ?, CURRENT_TIMESTAMP)", (str(user_id), thread_id))

    def get_session(self, timestamp: str) -> str:
        """Determine trading session from timestamp using real exchange local times (DST-aware).

        Matches smc_engine.get_active_session logic — sessions defined in local exchange time:
          Asian  (Asia/Tokyo):       09:00-15:00
          London (Europe/London):    08:00-16:30
          NY     (America/New_York): 09:30-16:00
          Overlap: London + NY both active
        """
        from datetime import datetime as _dt, timezone as _tz
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            # Fallback: approximate with old CET logic
            try:
                hour = int(timestamp[11:13])
            except (ValueError, IndexError):
                return "unknown"
            if 0 <= hour < 8:
                return "asian"
            elif 8 <= hour < 14:
                return "london"
            elif 14 <= hour < 17:
                return "overlap"
            elif 17 <= hour < 23:
                return "new_york"
            else:
                return "off_hours"

        try:
            # Parse ISO timestamp as UTC
            ts = timestamp.replace('Z', '+00:00')
            utc_dt = _dt.fromisoformat(ts)
            if utc_dt.tzinfo is None:
                utc_dt = utc_dt.replace(tzinfo=_tz.utc)
        except (ValueError, IndexError):
            return "unknown"

        tokyo  = utc_dt.astimezone(ZoneInfo('Asia/Tokyo'))
        london = utc_dt.astimezone(ZoneInfo('Europe/London'))
        ny     = utc_dt.astimezone(ZoneInfo('America/New_York'))

        tokyo_min  = tokyo.hour * 60 + tokyo.minute
        london_min = london.hour * 60 + london.minute
        ny_min     = ny.hour * 60 + ny.minute

        london_active = 8 * 60 <= london_min < 16 * 60 + 30
        ny_active     = 9 * 60 + 30 <= ny_min < 16 * 60
        asian_active  = 9 * 60 <= tokyo_min < 15 * 60

        if london_active and ny_active:
            return "overlap"
        elif london_active:
            return "london"
        elif ny_active:
            return "new_york"
        elif asian_active:
            return "asian"
        else:
            return "off_hours"

    def update_pattern_stats(self, pattern: str, outcome: str):
        """Atomowa aktualizacja statystyk wzorca (bez race condition)."""
        is_win = 1 if outcome in ("WIN", "PROFIT") else 0
        is_loss = 1 if outcome not in ("WIN", "PROFIT") else 0
        # Atomic upsert — żadna inna operacja nie może wtrącić się między SELECT i UPDATE
        self._execute("""
            INSERT INTO pattern_stats (pattern, count, wins, losses, win_rate)
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(pattern) DO UPDATE SET
                count = count + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_rate = CAST(wins + ? AS REAL) / (count + 1),
                last_updated = CURRENT_TIMESTAMP
        """, (pattern, is_win, is_loss, float(is_win),
              is_win, is_loss, is_win))

    def get_pattern_stats(self, pattern: str) -> dict:
        row = self._query_one("SELECT count, wins, losses, win_rate FROM pattern_stats WHERE pattern = ?", (pattern,))
        if row: return {"count": row[0], "wins": row[1], "losses": row[2], "win_rate": row[3]}
        return {"count": 0, "wins": 0, "losses": 0, "win_rate": 0}

    def get_all_patterns_stats(self) -> list:
        return self._query("SELECT pattern, count, wins, losses, win_rate FROM pattern_stats ORDER BY win_rate DESC")

    def set_param(self, name: str, value):
        # Schema-aware path: validate + auto-mirror coupled keys
        # (e.g. target_rr → tp_to_sl_ratio, see dynamic_params_schema.py).
        # Failure-soft: any error in the schema layer is logged and the
        # write proceeds — schema must never block a production write.
        mirror_target: str | None = None
        try:
            from src.core.dynamic_params_schema import validate_param_write
            mirror_target = validate_param_write(name, value)
        except Exception as _e:  # pragma: no cover
            logger.debug(f"dynamic_params schema check failed: {_e}")

        if isinstance(value, str) and not self._is_numeric_string(value):
            self._execute(
                "INSERT INTO dynamic_params (param_name, param_text) VALUES (?, ?) "
                "ON CONFLICT(param_name) DO UPDATE SET param_text=excluded.param_text, param_value=NULL, last_updated=CURRENT_TIMESTAMP",
                (name, value))
        else:
            self._execute(
                "INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) "
                "ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value, param_text=NULL, last_updated=CURRENT_TIMESTAMP",
                (name, value))

        # Auto-mirror coupled keys exactly once (no recursion — mirror writes
        # bypass the mirror lookup by writing directly with the same value).
        if mirror_target and mirror_target != name:
            try:
                if isinstance(value, str) and not self._is_numeric_string(value):
                    self._execute(
                        "INSERT INTO dynamic_params (param_name, param_text) VALUES (?, ?) "
                        "ON CONFLICT(param_name) DO UPDATE SET param_text=excluded.param_text, param_value=NULL, last_updated=CURRENT_TIMESTAMP",
                        (mirror_target, value))
                else:
                    self._execute(
                        "INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) "
                        "ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value, param_text=NULL, last_updated=CURRENT_TIMESTAMP",
                        (mirror_target, value))
                logger.debug(
                    f"[dynamic_params] auto-mirrored {name} → {mirror_target} = {value}"
                )
            except Exception as _e:  # pragma: no cover
                logger.warning(f"[dynamic_params] mirror write failed: {_e}")

    def get_param(self, name: str, default=None):
        row = self._query_one("SELECT param_value, param_text FROM dynamic_params WHERE param_name = ?", (name,))
        try:
            from src.core.dynamic_params_schema import track_read
            track_read(name)
        except Exception:
            pass
        if not row:
            return default
        # Return text if available, otherwise numeric
        if row[1] is not None:
            return row[1]
        return row[0] if row[0] is not None else default

    @staticmethod
    def _is_numeric_string(s: str) -> bool:
        try:
            float(s)
            return True
        except (ValueError, TypeError):
            return False

    # ── MODEL ALERTS ──────────────────────────────────────────────────────

    def save_model_alert(self, model_name: str, alert_type: str, severity: str,
                         message: str, psi_value: float = None) -> Optional[int]:
        """
        Insert a model alert with 1-hour deduplication.
        Won't insert if same model_name + alert_type alert exists within the last hour.
        Returns the new alert id, or None if deduplicated.
        """
        existing = self._query_one(
            "SELECT id FROM model_alerts "
            "WHERE model_name = ? AND alert_type = ? AND resolved = 0 "
            "AND timestamp > datetime('now', '-1 hour')",
            (model_name, alert_type),
        )
        if existing:
            return None
        return self._insert_returning_id(
            "INSERT INTO model_alerts (model_name, alert_type, severity, message, psi_value) "
            "VALUES (?, ?, ?, ?, ?)",
            (model_name, alert_type, severity, message, psi_value),
        )

    def get_model_alerts(self, limit: int = 20, unresolved_only: bool = False) -> list:
        """Fetch recent model alerts as list of dicts."""
        sql = "SELECT id, timestamp, model_name, alert_type, severity, message, psi_value, resolved FROM model_alerts"
        if unresolved_only:
            sql += " WHERE resolved = 0"
        sql += " ORDER BY timestamp DESC LIMIT ?"
        rows = self._query(sql, (limit,))
        return [
            {"id": r[0], "timestamp": r[1], "model_name": r[2], "alert_type": r[3],
             "severity": r[4], "message": r[5], "psi_value": r[6], "resolved": bool(r[7])}
            for r in rows
        ]

    def resolve_alert(self, alert_id: int) -> bool:
        """Mark a model alert as resolved. Returns True if a row was updated."""
        self._execute(
            "UPDATE model_alerts SET resolved = 1 WHERE id = ? AND resolved = 0",
            (alert_id,),
        )
        row = self._query_one("SELECT changes()")
        return bool(row and row[0] > 0)

    def get_unresolved_alert_count(self) -> int:
        row = self._query_one("SELECT COUNT(*) FROM model_alerts WHERE resolved = 0")
        return row[0] if row else 0

    def update_session_stats(self, pattern: str, session: str, outcome: str):
        is_win = 1 if outcome in ("WIN", "PROFIT") else 0
        is_loss = 1 if outcome not in ("WIN", "PROFIT") else 0
        self._execute("""
            INSERT INTO session_stats (pattern, session, count, wins, losses, win_rate)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(pattern, session) DO UPDATE SET
                count = count + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_rate = CAST(wins + ? AS REAL) / (count + 1),
                last_updated = CURRENT_TIMESTAMP
        """, (pattern, session, is_win, is_loss, float(is_win),
              is_win, is_loss, is_win))

    def get_session_stats(self, pattern: Optional[str] = None) -> list:
        if pattern:
            return self._query("SELECT pattern, session, count, wins, losses, win_rate FROM session_stats WHERE pattern = ? ORDER BY win_rate DESC", (pattern,))
        return self._query("SELECT pattern, session, count, wins, losses, win_rate FROM session_stats ORDER BY pattern, win_rate DESC")

    def get_session_win_rate(self, session: str, direction: Optional[str] = None, min_trades: int = 5) -> dict:
        """Get win rate for a specific session, optionally filtered by direction."""
        if direction:
            row = self._query_one(
                "SELECT COUNT(*) as n, "
                "SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins "
                "FROM trades WHERE session=? AND direction LIKE ? AND status IN ('WIN','LOSS')",
                (session, f"%{direction}%")
            )
        else:
            row = self._query_one(
                "SELECT COUNT(*) as n, "
                "SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins "
                "FROM trades WHERE session=? AND status IN ('WIN','LOSS')",
                (session,)
            )
        if not row or not row[0] or row[0] < min_trades:
            return {"session": session, "count": row[0] if row else 0, "win_rate": None, "sufficient_data": False}
        n, wins = row[0], row[1] or 0
        return {"session": session, "count": n, "wins": wins, "win_rate": round(wins / n, 3), "sufficient_data": True}

    def get_all_session_performance(self, min_trades: int = 3) -> list:
        """Get win rate breakdown per session for dashboard/analysis."""
        rows = self._query(
            "SELECT session, direction, COUNT(*) as n, "
            "SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins, "
            "SUM(CASE WHEN status='LOSS' THEN 1 ELSE 0 END) as losses, "
            "ROUND(CAST(SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) AS REAL) / COUNT(*), 3) as wr "
            "FROM trades WHERE status IN ('WIN','LOSS') "
            "GROUP BY session, direction HAVING COUNT(*) >= ? "
            "ORDER BY wr DESC",
            (min_trades,)
        )
        return [{"session": r[0], "direction": r[1], "count": r[2], "wins": r[3],
                 "losses": r[4], "win_rate": r[5]} for r in (rows or [])]

    def init_weights(self):
        fw = {'weight_ob_main': 2.0, 'weight_ob_m5': 1.5, 'weight_ob_h1': 1.5, 'weight_fvg': 1.5, 'weight_grab_mss': 2.0, 'weight_dbr_rbd': 1.5, 'weight_news': 1.0, 'weight_macro': 1.5, 'weight_rsi_opt': 1.0, 'weight_m5_confluence': 1.0, 'weight_bos': 1.5, 'weight_choch': 1.5, 'weight_ob_count': 0.8, 'weight_ob_confluence': 0.8, 'weight_choch_h1': 1.2, 'weight_supply_demand': 1.5, 'weight_rsi_divergence': 1.5, 'weight_ichimoku_bull': 1.2, 'weight_near_poc': 1.0, 'weight_engulfing_bull': 1.3, 'weight_engulfing_bear': 1.3, 'weight_pin_bar_bull': 1.2, 'weight_pin_bar_bear': 1.2, 'weight_inside_bar': 0.8, 'weight_ml_bull': 1.5, 'weight_ml_bear': 1.5, 'weight_rl_buy': 1.5, 'weight_rl_sell': 1.5}
        for name, val in fw.items():
            if self.get_param(name) is None: self.set_param(name, val)
        # NOTE on target_rr vs tp_to_sl_ratio: self_learning writes both
        # (as of 2026-04-16 fix commit 95569f7), production trading reads
        # tp_to_sl_ratio in finance.py:119. target_rr is kept for
        # historical / debug visibility of what the optimizer chose; it's
        # not seeded as a default here to avoid the confusion that caused
        # a ~2-month bug where target_rr=3.16 was optimizer output but
        # tp_to_sl_ratio=2.39 was what production actually used.
        for name, val in {
            'min_score': 5.0, 'risk_percent': 1.0, 'min_tp_distance_mult': 1.0,
            'sl_atr_multiplier': 1.5, 'sl_min_distance': 4.0,
            'tp_to_sl_ratio': 2.5,
        }.items():
            if self.get_param(name) is None: self.set_param(name, val)

    def get_trade_factors(self, trade_id: int) -> dict:
        row = self._query_one("SELECT factors FROM trades WHERE id = ?", (trade_id,))
        return json.loads(row[0]) if row and row[0] else {}

    def update_balance(self, user_id: int, amount: float):
        self._execute("INSERT INTO user_settings (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance", (user_id, amount))

    def get_balance(self, user_id: int) -> float:
        row = self._query_one("SELECT balance FROM user_settings WHERE user_id = ?", (user_id,))
        return row[0] if row else 1000.0

    def get_performance_stats(self):
        results = dict(self._query("SELECT status, COUNT(*) FROM trades GROUP BY status"))
        history = self._query("SELECT timestamp, direction, status FROM trades ORDER BY id DESC LIMIT 5")
        return results, history

    def log_trade(self, direction, price, sl, tp, rsi, trend, structure="Stable", pattern=None, factors=None, lot=None, profit=None):
        # 2026-05-04 fix (TZ audit): get_session() refactored to PARSE UTC
        # input (line 577 — `Parse ISO timestamp as UTC`), but log_trade was
        # still passing `datetime.now()` (naive local CEST). Result: every
        # trade tagged with session ~1-2h offset (summer/winter) — CEST 15:00
        # was interpreted as UTC 15:00 → London BST 16:00 = post-killzone
        # when actual was within killzone. Now: pass UTC consistently.
        now_utc = datetime.datetime.utcnow()
        ts = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        session = self.get_session(ts)
        fj = json.dumps(factors) if factors else None
        self._execute("INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, trend, structure, pattern, factors, session, lot, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (ts, direction, price, sl, tp, rsi, trend, structure, pattern, fj, session, lot, profit))

    def get_open_trades(self):
        return self._query("SELECT id, direction, entry, sl, tp FROM trades WHERE status = 'OPEN'")

    def update_trade_profit(self, trade_id: int, profit: float):
        self._execute("UPDATE trades SET profit = ? WHERE id = ?", (profit, trade_id))

    def backfill_trade_profits(self) -> int:
        """Populate missing profit values for closed trades.

        Includes the lot multiplier (fixed 2026-04-16): standard XAU contract
        is 100 oz, so $ PnL = price_move * 100 * lot. Earlier version of
        this function ignored lot and wrote price_move as-is, resulting in
        10x underreporting for 0.1 lot trades and 2x for 0.02 lot.
        """
        rows = self._query(
            "SELECT id, direction, entry, sl, tp, status, lot FROM trades "
            "WHERE status IN ('WIN', 'LOSS', 'PROFIT') AND "
            "(profit IS NULL OR profit = 0 OR profit = 0.0)"
        )
        if not rows: return 0
        OZ_PER_STANDARD_LOT = 100.0
        updated = 0
        for t_id, direction, entry, sl, tp, status, lot in rows:
            try:
                ef, sf, tf = float(entry or 0), float(sl or 0), float(tp or 0)
                lf = float(lot or 0.01)
                if ef <= 0 or lf <= 0: continue
                price_move = abs(tf - ef) if status in ('WIN', 'PROFIT') else -abs(ef - sf)
                pv = round(price_move * OZ_PER_STANDARD_LOT * lf, 2)
                if pv != 0:
                    self._execute("UPDATE trades SET profit = ? WHERE id = ?", (pv, t_id)); updated += 1
            except (ValueError, TypeError): continue
        return updated

    def update_trade_status(self, trade_id: int, status: str):
        self._execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))

    def cleanup_invalid_trades(self, reference_price: float, tolerance_pct: float = 0.25) -> int:
        if reference_price <= 0: return 0
        low, high = reference_price * (1 - tolerance_pct), reference_price * (1 + tolerance_pct)
        rows = self._query("SELECT COUNT(*) FROM trades WHERE entry IS NOT NULL AND (CAST(entry AS REAL) < ? OR CAST(entry AS REAL) > ?)", (low, high))
        count = rows[0][0] if rows and rows[0] else 0
        if count == 0: return 0
        self._execute("DELETE FROM trades WHERE entry IS NOT NULL AND (CAST(entry AS REAL) < ? OR CAST(entry AS REAL) > ?)", (low, high))
        try: self._execute("DELETE FROM scanner_signals WHERE entry IS NOT NULL AND (CAST(entry AS REAL) < ? OR CAST(entry AS REAL) > ?)", (low, high))
        except (Exception) as e: logger.debug(f"scanner_signals cleanup skipped: {e}")
        logger.info(f"Usunięto {count} tradów z cenami poza zakresem ${low:.0f}-${high:.0f} (ref: ${reference_price:.0f})")
        return count

    def get_failures_report(self) -> str:
        losses = self._query("SELECT direction, rsi, trend, entry, structure FROM trades WHERE status = 'LOSS' ORDER BY id DESC LIMIT 5")
        if not losses: return "Brak zarejestrowanych porażek."
        report = "ANALIZA PORAŻEK:\n"
        for l in losses: report += f"- Strata na {l[0]} | RSI: {l[1]} | Trend: {l[2]} | Struktura: {l[4]}\n"
        return report

    def log_loss_details(self, trade_id, reason, market_condition):
        self._execute("UPDATE trades SET failure_reason = ?, condition_at_loss = ? WHERE id = ?", (reason, market_condition, trade_id))

    def get_recent_lessons(self, limit=5):
        return self._query("SELECT direction, entry, rsi, trend, status FROM trades WHERE status = 'LOSS' ORDER BY id DESC LIMIT ?", (limit,))

    def save_scanner_signal(self, direction, entry, sl, tp, rsi, trend, structure):
        self._execute("INSERT INTO scanner_signals (direction, entry, sl, tp, rsi, trend, structure, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')", (direction, entry, sl, tp, rsi, trend, structure))

    def get_latest_scanner_signal(self):
        return self._query_one("SELECT id, direction, entry, sl, tp, rsi, trend, structure, status, timestamp FROM scanner_signals ORDER BY timestamp DESC LIMIT 1")

    def get_all_scanner_signals(self, limit=50):
        return self._query("SELECT id, direction, entry, sl, tp, rsi, trend, structure, status, timestamp FROM scanner_signals ORDER BY timestamp DESC LIMIT ?", (limit,)) or []

    def check_trade_outcomes(self, current_gold_price):
        for sig in self._query("SELECT id, direction, sl, tp, rsi, trend, structure FROM scanner_signals WHERE status = 'PENDING'"):
            sid, d, sl, tp, rsi, trend, structure = sig
            st = None
            if d == "LONG":
                if current_gold_price >= tp: st = "WIN"
                elif current_gold_price <= sl: st = "LOSS"
            else:
                if current_gold_price <= tp: st = "WIN"
                elif current_gold_price >= sl: st = "LOSS"
            if st: self._execute("UPDATE scanner_signals SET status = ? WHERE id = ?", (st, sid))

    def get_fail_rate_for_pattern(self, rsi, structure):
        try:
            results = self._query("SELECT status FROM trades WHERE rsi BETWEEN ? AND ? AND structure = ?", (rsi - 5, rsi + 5, structure))
            if not results or len(results) < 3: return 0
            return (sum(1 for r in results if r[0] == 'LOSS') / len(results)) * 100
        except Exception as e:
            logger.debug(f"get_fail_rate_for_pattern error: {e}"); return 0

    def is_news_processed(self, title_hash: str) -> bool:
        return self._query_one("SELECT 1 FROM processed_news WHERE title_hash = ?", (title_hash,)) is not None

    def mark_news_as_processed(self, title_hash: str):
        # INSERT OR IGNORE — prevents UNIQUE constraint crash when two callers
        # (e.g. bg scanner + quick-trade) race to mark the same hash
        self._execute("INSERT OR IGNORE INTO processed_news (title_hash) VALUES (?)", (title_hash,))

    def update_regime_stats(self, regime: str, session: str, direction: str, outcome: str):
        is_win = 1 if outcome in ("WIN", "PROFIT") else 0
        is_loss = 1 if outcome not in ("WIN", "PROFIT") else 0
        self._execute("""
            INSERT INTO regime_stats (regime, session, direction, count, wins, losses, win_rate)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(regime, session, direction) DO UPDATE SET
                count = count + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_rate = CAST(wins + ? AS REAL) / (count + 1),
                last_updated = CURRENT_TIMESTAMP
        """, (regime, session, direction, is_win, is_loss, float(is_win),
              is_win, is_loss, is_win))

    def get_regime_stats(self, regime: Optional[str] = None, session: Optional[str] = None) -> list:
        if regime and session:
            return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats WHERE regime = ? AND session = ? ORDER BY win_rate DESC", (regime, session))
        elif regime:
            return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats WHERE regime = ? ORDER BY win_rate DESC", (regime,))
        return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats ORDER BY regime, session, win_rate DESC")

    def rebuild_all_stats(self):
        """Przelicz pattern_stats i session_stats od nowa na podstawie trades."""
        # Clear stale stats
        self._execute("DELETE FROM pattern_stats")
        self._execute("DELETE FROM session_stats")

        rows = self._query("""
            SELECT id, pattern, session, status FROM trades
            WHERE status IN ('WIN', 'LOSS') AND pattern IS NOT NULL
        """)
        for _, pattern, session, status in rows:
            self.update_pattern_stats(pattern, status)
            if session:
                self.update_session_stats(pattern, session, status)
        logger.info(f"Rebuilt stats from {len(rows)} resolved trades")

    def save_news_sentiment(self, headline: str, sentiment: str, score: float = 0.0, source: str = "rss"):
        self._execute("INSERT INTO news_sentiment (headline, sentiment, score, source) VALUES (?, ?, ?, ?)", (headline, sentiment, score, source))

    def get_aggregated_news_sentiment(self, hours: int = 24) -> dict:
        rows = self._query("SELECT sentiment, COUNT(*) as cnt FROM news_sentiment WHERE timestamp > datetime('now', ?) GROUP BY sentiment", (f"-{hours} hours",))
        total = sum(r[1] for r in rows) if rows else 0
        result = {"bullish": 0, "bearish": 0, "neutral": 0, "total": total}
        for s, c in rows:
            k = s.lower()
            if k in result: result[k] = c
        result["bullish_pct"] = round(result["bullish"] / total * 100, 1) if total > 0 else 0
        result["bearish_pct"] = round(result["bearish"] / total * 100, 1) if total > 0 else 0
        return result

    def get_recent_ml_predictions(self, limit: int = 20) -> list:
        return self._query("SELECT id, timestamp, lstm_pred, xgb_pred, dqn_action, ensemble_score, ensemble_signal, confidence FROM ml_predictions ORDER BY timestamp DESC LIMIT ?", (limit,))

    # ── SETUP QUALITY STATS ──

    def update_setup_quality_stats(self, grade: str, direction: str, outcome: str, profit: float = 0):
        is_win = 1 if outcome in ("WIN", "PROFIT") else 0
        is_loss = 1 if outcome not in ("WIN", "PROFIT") else 0
        self._execute("""
            INSERT INTO setup_quality_stats (grade, direction, count, wins, losses, win_rate, avg_profit)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(grade, direction) DO UPDATE SET
                count = count + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_rate = CAST(wins + ? AS REAL) / (count + 1),
                avg_profit = (avg_profit * count + ?) / (count + 1),
                last_updated = CURRENT_TIMESTAMP
        """, (grade, direction, is_win, is_loss, float(is_win), profit,
              is_win, is_loss, is_win, profit))

    def get_setup_quality_stats(self, grade: Optional[str] = None) -> list:
        if grade:
            return self._query("SELECT grade, direction, count, wins, losses, win_rate, avg_profit FROM setup_quality_stats WHERE grade = ?", (grade,))
        return self._query("SELECT grade, direction, count, wins, losses, win_rate, avg_profit FROM setup_quality_stats ORDER BY grade, direction")

    # ── HOURLY STATS ──

    def update_hourly_stats(self, hour: int, direction: str, outcome: str):
        is_win = 1 if outcome in ("WIN", "PROFIT") else 0
        is_loss = 1 if outcome not in ("WIN", "PROFIT") else 0
        self._execute("""
            INSERT INTO hourly_stats (hour, direction, count, wins, losses, win_rate)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(hour, direction) DO UPDATE SET
                count = count + 1,
                wins = wins + ?,
                losses = losses + ?,
                win_rate = CAST(wins + ? AS REAL) / (count + 1),
                last_updated = CURRENT_TIMESTAMP
        """, (hour, direction, is_win, is_loss, float(is_win),
              is_win, is_loss, is_win))

    def get_hourly_stats(self, hour: Optional[int] = None) -> list:
        if hour is not None:
            return self._query("SELECT hour, direction, count, wins, losses, win_rate FROM hourly_stats WHERE hour = ?", (hour,))
        return self._query("SELECT hour, direction, count, wins, losses, win_rate FROM hourly_stats ORDER BY hour")

    def get_bad_hours(self, min_trades: int = 5, max_winrate: float = 0.35) -> list:
        """Zwraca godziny z win_rate < max_winrate (historycznie przegrywające)."""
        return self._query(
            "SELECT hour, direction, win_rate, count FROM hourly_stats WHERE count >= ? AND win_rate < ? ORDER BY win_rate ASC",
            (min_trades, max_winrate))

    # ── TRAILING STOP LOG ──

    def log_trailing_stop_event(self, trade_id: int, event: str, old_sl: float, new_sl: float, price: float, r_multiple: float):
        self._execute(
            "INSERT INTO trailing_stop_log (trade_id, event, old_sl, new_sl, price_at_event, r_multiple) VALUES (?, ?, ?, ?, ?, ?)",
            (trade_id, event, old_sl, new_sl, price, r_multiple))

    def get_trailing_stop_history(self, trade_id: int) -> list:
        return self._query(
            "SELECT timestamp, event, old_sl, new_sl, price_at_event, r_multiple FROM trailing_stop_log WHERE trade_id = ? ORDER BY timestamp",
            (trade_id,))

    # ── LOSS PATTERNS ──

    def update_loss_pattern(self, pattern_type: str, direction: str, description: str = ""):
        self._execute("""
            INSERT INTO loss_patterns (pattern_type, direction, count, description)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(pattern_type, direction) DO UPDATE SET
                count = count + 1,
                description = excluded.description,
                last_seen = CURRENT_TIMESTAMP
        """, (pattern_type, direction, description))

    def get_loss_patterns(self, direction: Optional[str] = None, min_count: int = 2) -> list:
        if direction:
            return self._query(
                "SELECT pattern_type, direction, count, description FROM loss_patterns WHERE direction = ? AND count >= ? ORDER BY count DESC",
                (direction, min_count))
        return self._query(
            "SELECT pattern_type, direction, count, description FROM loss_patterns WHERE count >= ? ORDER BY count DESC",
            (min_count,))

    def get_trade_by_id(self, trade_id: int):
        return self._query_one("SELECT * FROM trades WHERE id = ?", (trade_id,))

    def update_trade_trailing_sl(self, trade_id: int, new_sl: float):
        self._execute("UPDATE trades SET trailing_sl = ?, sl = ? WHERE id = ?", (new_sl, new_sl, trade_id))

    def update_trade_setup_grade(self, trade_id: int, grade: str, score: float):
        self._execute("UPDATE trades SET setup_grade = ?, setup_score = ? WHERE id = ?", (grade, score, trade_id))

    def get_open_trades_extended(self):
        """Zwraca otwarte trade'y z rozszerzonymi danymi (do trailing stop).

        Includes `lot` column (added 2026-04-16) so resolve_trades_task
        can compute PnL with correct position size instead of raw
        price_move.
        """
        return self._query(
            "SELECT id, direction, entry, sl, tp, trailing_sl, setup_grade, factors, lot FROM trades WHERE status = 'OPEN'"
        )

    # ── MACRO SNAPSHOTS ──

    def write_macro_snapshot(
        self,
        macro_regime: Optional[str] = None,
        usdjpy_zscore: Optional[float] = None,
        usdjpy_price: Optional[float] = None,
        atr_ratio: Optional[float] = None,
        uup: Optional[float] = None,
        tlt: Optional[float] = None,
        vixy: Optional[float] = None,
        market_regime: Optional[str] = None,
        signals: Optional[dict] = None,
    ) -> None:
        """Persist one regime snapshot. Called by the BG scanner each cycle.

        All args are optional — fields that couldn't be computed (e.g.
        macro proxies unavailable) are stored as NULL. ``signals`` carries
        the per-component vote dict (-1/0/+1 per signal) as JSON for
        future audits ("did USDJPY agree with vol on this day?").
        """
        signals_json = json.dumps(signals, default=str) if signals else None
        self._execute("""
            INSERT INTO macro_snapshots
            (macro_regime, usdjpy_zscore, usdjpy_price, atr_ratio,
             uup, tlt, vixy, market_regime, signals_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (macro_regime, usdjpy_zscore, usdjpy_price, atr_ratio,
              uup, tlt, vixy, market_regime, signals_json))

    def get_recent_macro_snapshots(self, limit: int = 200) -> list:
        """Most-recent N snapshots (descending timestamp). Useful for
        regime-change detection and quick API endpoint preview."""
        return self._query(
            "SELECT id, timestamp, macro_regime, usdjpy_zscore, usdjpy_price, "
            "atr_ratio, market_regime FROM macro_snapshots "
            "ORDER BY id DESC LIMIT ?", (limit,))

    # ── REJECTED SETUPS ──

    def log_rejected_setup(self, timeframe: str, direction: str, price: float,
                           rejection_reason: str, filter_name: str,
                           confluence_count: int = 0, rsi: float = 0,
                           trend: str = "", pattern: str = "", atr: float = 0):
        self._execute("""
            INSERT INTO rejected_setups
            (timeframe, direction, price, rejection_reason, filter_name,
             confluence_count, rsi, trend, pattern, atr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (timeframe, direction, price, rejection_reason, filter_name,
              confluence_count, rsi, trend, pattern, atr))

    def get_recent_rejections(self, filter_name: Optional[str] = None, limit: int = 50) -> list:
        if filter_name:
            return self._query(
                "SELECT id, timestamp, timeframe, direction, price, rejection_reason, filter_name, pattern "
                "FROM rejected_setups WHERE filter_name = ? ORDER BY id DESC LIMIT ?",
                (filter_name, limit))
        return self._query(
            "SELECT id, timestamp, timeframe, direction, price, rejection_reason, filter_name, pattern "
            "FROM rejected_setups ORDER BY id DESC LIMIT ?", (limit,))

    def validate_rejection(self, rejection_id: int, would_have_won: bool):
        """Po fakcie sprawdź czy odrzucenie było trafne."""
        self._execute(
            "UPDATE rejected_setups SET would_have_won = ? WHERE id = ?",
            (1 if would_have_won else 0, rejection_id))

    def get_filter_rejection_accuracy(self, filter_name: str) -> dict:
        """Zwraca accuracy filtra na podstawie walidacji odrzuceń."""
        row = self._query_one("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN would_have_won = 0 THEN 1 ELSE 0 END) as correct_rejections,
                SUM(CASE WHEN would_have_won = 1 THEN 1 ELSE 0 END) as missed_wins
            FROM rejected_setups
            WHERE filter_name = ? AND would_have_won IS NOT NULL
        """, (filter_name,))
        if not row or not row[0]:
            return {"total": 0, "accuracy": 0, "correct": 0, "missed_wins": 0}
        total, correct, missed = row
        return {
            "total": total,
            "accuracy": round(correct / total, 3) if total > 0 else 0,
            "correct": correct or 0,
            "missed_wins": missed or 0,
        }

    # ── FILTER PERFORMANCE ──

    def update_filter_performance(self, filter_name: str, direction: str,
                                  blocked: bool, trade_won: bool):
        """Aktualizuj accuracy filtra po rozwiązaniu trade'a.

        Logika:
          blocked=True,  trade_won=False → correct_block  (filtr słusznie zablokował)
          blocked=True,  trade_won=True  → incorrect_block (filtr zablokował winnera)
          blocked=False, trade_won=True  → correct_pass   (filtr słusznie przepuścił)
          blocked=False, trade_won=False → incorrect_pass  (filtr przepuścił losera)
        """
        cb = 1 if (blocked and not trade_won) else 0
        ib = 1 if (blocked and trade_won) else 0
        cp = 1 if (not blocked and trade_won) else 0
        ip = 1 if (not blocked and not trade_won) else 0

        self._execute("""
            INSERT INTO filter_performance (filter_name, direction,
                correct_blocks, incorrect_blocks, correct_passes, incorrect_passes, accuracy)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(filter_name, direction) DO UPDATE SET
                correct_blocks = correct_blocks + ?,
                incorrect_blocks = incorrect_blocks + ?,
                correct_passes = correct_passes + ?,
                incorrect_passes = incorrect_passes + ?,
                accuracy = CAST(correct_blocks + ? + correct_passes + ? AS REAL) /
                           MAX(correct_blocks + ? + incorrect_blocks + ? + correct_passes + ? + incorrect_passes + ?, 1),
                last_updated = CURRENT_TIMESTAMP
        """, (filter_name, direction, cb, ib, cp, ip,
              cb, ib, cp, ip,
              cb, cp,
              cb, ib, cp, ip))

    def get_filter_accuracy(self, filter_name: Optional[str] = None) -> list:
        if filter_name:
            return self._query(
                "SELECT filter_name, direction, correct_blocks, incorrect_blocks, "
                "correct_passes, incorrect_passes, accuracy FROM filter_performance WHERE filter_name = ?",
                (filter_name,))
        return self._query(
            "SELECT filter_name, direction, correct_blocks, incorrect_blocks, "
            "correct_passes, incorrect_passes, accuracy FROM filter_performance ORDER BY accuracy DESC")

    # ── TRADE CONFIRMATION DATA ──

    def update_trade_confirmation(self, trade_id: int, confirmation_data: str,
                                  model_agreement: float, vol_regime: str):
        self._execute(
            "UPDATE trades SET confirmation_data = ?, model_agreement = ?, vol_regime = ? WHERE id = ?",
            (confirmation_data, model_agreement, vol_regime, trade_id))

    # ── PER-REGIME MODEL ACCURACY ──

    def get_model_accuracy_by_regime(self, regime: Optional[str] = None) -> list:
        """Zwraca accuracy modeli per regime (z ml_predictions + trades)."""
        sql = """
            SELECT mp.ensemble_signal, t.status, t.vol_regime,
                   mp.confidence, mp.ensemble_score
            FROM ml_predictions mp
            JOIN trades t ON mp.trade_id = t.id
            WHERE t.status IN ('WIN', 'LOSS')
        """
        params: tuple = ()
        if regime:
            sql += " AND t.vol_regime = ?"
            params = (regime,)
        return self._query(sql, params)

    def get_trade_performance_metrics(self) -> dict:
        rows = self._query("SELECT status, profit FROM trades WHERE status IN ('WIN', 'LOSS', 'PROFIT') ORDER BY id ASC")
        if not rows:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "profit_factor": 0, "expectancy": 0, "max_consecutive_wins": 0, "max_consecutive_losses": 0, "max_drawdown": 0, "total_profit": 0}
        wins = losses = 0; twp = tla = 0.0; eq = [0.0]; peak = mdd = 0.0; cw = cl = mcw = mcl = 0
        for status, profit in rows:
            p = float(profit or 0)
            if status in ('WIN', 'PROFIT'):
                wins += 1; twp += p; cw += 1; cl = 0; mcw = max(mcw, cw)
            else:
                losses += 1; tla += abs(p); cl += 1; cw = 0; mcl = max(mcl, cl)
            e = eq[-1] + p; eq.append(e); peak = max(peak, e); mdd = max(mdd, peak - e)
        t = wins + losses; aw = twp / wins if wins > 0 else 0; al = tla / losses if losses > 0 else 0
        pf = twp / tla if tla > 0 else (999.0 if twp > 0 else 0)
        wr = wins / t if t > 0 else 0; exp = (wr * aw) - ((1 - wr) * al) if t > 0 else 0
        return {"total": t, "wins": wins, "losses": losses, "win_rate": round(wr, 4), "avg_win": round(aw, 2), "avg_loss": round(al, 2), "profit_factor": round(pf, 2), "expectancy": round(exp, 2), "max_consecutive_wins": mcw, "max_consecutive_losses": mcl, "max_drawdown": round(mdd, 2), "total_profit": round(eq[-1], 2)}

    # ══════════════════════════════════════════════════════════════════════
    #  DATA RETENTION & ARCHIVAL
    # ══════════════════════════════════════════════════════════════════════

    def archive_old_trades(self, days: int = 90) -> int:
        """
        Move resolved trades older than N days to trades_archive table.
        Only moves trades with status != 'OPEN' (i.e. WIN, LOSS, CLOSED, PROPOSED).
        Returns count of archived trades.
        """
        # Create archive table with same schema as trades (if not exists)
        self._execute("""CREATE TABLE IF NOT EXISTS trades_archive (
            id INTEGER PRIMARY KEY,
            timestamp DATETIME,
            direction TEXT, entry REAL, sl REAL, tp REAL, rsi REAL, trend TEXT,
            structure TEXT, status TEXT,
            failure_reason TEXT, condition_at_loss TEXT, pattern TEXT, factors TEXT,
            lot REAL, profit REAL, session TEXT,
            setup_grade TEXT, setup_score REAL, trailing_sl REAL,
            confirmation_data TEXT, model_agreement REAL, vol_regime TEXT,
            archived_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")

        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()

        # Select trades to archive
        old_trades = self._query(
            "SELECT id, timestamp, direction, entry, sl, tp, rsi, trend, structure, status, "
            "failure_reason, condition_at_loss, pattern, factors, lot, profit, session, "
            "setup_grade, setup_score, trailing_sl, confirmation_data, model_agreement, vol_regime "
            "FROM trades WHERE status != 'OPEN' AND timestamp < ?",
            (cutoff,)
        )

        if not old_trades:
            return 0

        archived = 0
        for row in old_trades:
            try:
                self._execute(
                    "INSERT OR IGNORE INTO trades_archive "
                    "(id, timestamp, direction, entry, sl, tp, rsi, trend, structure, status, "
                    "failure_reason, condition_at_loss, pattern, factors, lot, profit, session, "
                    "setup_grade, setup_score, trailing_sl, confirmation_data, model_agreement, vol_regime) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row
                )
                self._execute("DELETE FROM trades WHERE id = ?", (row[0],))
                archived += 1
            except Exception as e:
                logger.warning(f"[RETENTION] Failed to archive trade #{row[0]}: {e}")

        logger.info(f"[RETENTION] Archived {archived} trades older than {days} days")
        return archived

    def purge_old_news(self, days: int = 30) -> int:
        """
        Delete processed_news entries older than N days.
        processed_news has no timestamp column, so we trim by row count
        keeping only the most recent entries (based on rowid).
        Returns count of purged rows.
        """
        # processed_news has only title_hash (no timestamp), so trim by count
        # Keep at most 10000 recent entries
        max_keep = 10000
        count_row = self._query_one("SELECT COUNT(*) FROM processed_news")
        total = count_row[0] if count_row else 0

        if total <= max_keep:
            return 0

        to_delete = total - max_keep
        # Delete oldest rows by rowid
        self._execute(
            "DELETE FROM processed_news WHERE rowid IN "
            "(SELECT rowid FROM processed_news ORDER BY rowid ASC LIMIT ?)",
            (to_delete,)
        )
        logger.info(f"[RETENTION] Purged {to_delete} old processed_news entries (kept {max_keep})")
        return to_delete

    def purge_old_predictions(self, days: int = 60) -> int:
        """
        Delete ml_predictions older than N days.
        Returns count of purged rows.
        """
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        try:
            before_row = self._query_one("SELECT COUNT(*) FROM ml_predictions")
            before = before_row[0] if before_row else 0

            self._execute(
                "DELETE FROM ml_predictions WHERE timestamp < ?",
                (cutoff,)
            )

            after_row = self._query_one("SELECT COUNT(*) FROM ml_predictions")
            after = after_row[0] if after_row else 0

            purged = before - after
            if purged > 0:
                logger.info(f"[RETENTION] Purged {purged} ml_predictions older than {days} days")
            return purged
        except Exception as e:
            logger.debug(f"[RETENTION] purge_old_predictions skipped: {e}")
            return 0

    def purge_old_rejected_setups(self, days: int = 30) -> int:
        """
        Delete rejected_setups older than N days.
        Returns count of purged rows.

        rejected_setups grows ~3-5k rows/week from BG scanner cycles. Without
        this purge the table reaches 50k+ rows in 6 months, slowing audit
        queries. 30d retention preserves enough for filter-tuning analysis
        while bounding growth. Added 2026-05-02 audit (was missing).
        """
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        try:
            before_row = self._query_one("SELECT COUNT(*) FROM rejected_setups")
            before = before_row[0] if before_row else 0

            self._execute(
                "DELETE FROM rejected_setups WHERE timestamp < ?",
                (cutoff,)
            )

            after_row = self._query_one("SELECT COUNT(*) FROM rejected_setups")
            after = after_row[0] if after_row else 0

            purged = before - after
            if purged > 0:
                logger.info(f"[RETENTION] Purged {purged} rejected_setups older than {days} days")
            return purged
        except Exception as e:
            logger.debug(f"[RETENTION] purge_old_rejected_setups skipped: {e}")
            return 0

    def report_stale_params(self, stale_days: int = 60) -> int:
        """
        Log dynamic_params keys not updated in N days. Read-only — does NOT
        delete (deletion would risk removing keys that are read but not
        written, like factor weights with manual default values).
        Returns count of stale keys for the retention summary.
        """
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=stale_days)).isoformat()
        try:
            rows = self._query(
                "SELECT param_name, last_updated FROM dynamic_params "
                "WHERE last_updated < ? "
                "ORDER BY last_updated ASC LIMIT 50",
                (cutoff,)
            )
            if rows:
                logger.info(
                    f"[RETENTION] {len(rows)} dynamic_params keys stale (>{stale_days}d): "
                    f"{', '.join(r[0] for r in rows[:5])}{'...' if len(rows) > 5 else ''}"
                )
            return len(rows) if rows else 0
        except Exception as e:
            logger.debug(f"[RETENTION] report_stale_params skipped: {e}")
            return 0

    def run_retention_cleanup(self) -> dict:
        """
        Run all data retention tasks: archive old trades, purge news, purge
        predictions, purge rejected_setups, report stale params.
        Returns summary dict with counts.
        """
        logger.info("[RETENTION] Starting daily data retention cleanup...")
        summary = {}

        try:
            summary["trades_archived"] = self.archive_old_trades(days=90)
        except Exception as e:
            logger.warning(f"[RETENTION] archive_old_trades failed: {e}")
            summary["trades_archived"] = 0

        try:
            summary["news_purged"] = self.purge_old_news(days=30)
        except Exception as e:
            logger.warning(f"[RETENTION] purge_old_news failed: {e}")
            summary["news_purged"] = 0

        try:
            summary["predictions_purged"] = self.purge_old_predictions(days=60)
        except Exception as e:
            logger.warning(f"[RETENTION] purge_old_predictions failed: {e}")
            summary["predictions_purged"] = 0

        try:
            summary["rejected_setups_purged"] = self.purge_old_rejected_setups(days=30)
        except Exception as e:
            logger.warning(f"[RETENTION] purge_old_rejected_setups failed: {e}")
            summary["rejected_setups_purged"] = 0

        try:
            summary["stale_params_count"] = self.report_stale_params(stale_days=60)
        except Exception as e:
            logger.warning(f"[RETENTION] report_stale_params failed: {e}")
            summary["stale_params_count"] = 0

        total = sum(summary.values())
        logger.info(f"[RETENTION] Cleanup complete: {summary} (total: {total})")
        return summary

    # ══════════════════════════════════════════════════════════════════════
    #  TRADE JOURNALING
    # ══════════════════════════════════════════════════════════════════════

    def save_journal_entry(self, trade_id: int, rationale: str = None,
                           emotion: str = None, lesson: str = None,
                           notes: str = None) -> int:
        """
        Upsert a journal entry for a trade.
        If an entry already exists for trade_id, update it; otherwise insert new.
        Returns the journal entry id.
        """
        existing = self._query_one(
            "SELECT id FROM trade_journal WHERE trade_id = ?", (trade_id,)
        )
        if existing:
            self._execute(
                "UPDATE trade_journal SET rationale = ?, emotion = ?, lesson = ?, "
                "notes = ?, timestamp = CURRENT_TIMESTAMP WHERE trade_id = ?",
                (rationale, emotion, lesson, notes, trade_id)
            )
            return existing[0]
        else:
            return self._insert_returning_id(
                "INSERT INTO trade_journal (trade_id, rationale, emotion, lesson, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                (trade_id, rationale, emotion, lesson, notes)
            )

    def get_journal_entry(self, trade_id: int) -> Optional[dict]:
        """Get journal entry for a specific trade. Returns dict or None."""
        row = self._query_one(
            "SELECT j.id, j.trade_id, j.timestamp, j.rationale, j.emotion, j.lesson, j.notes "
            "FROM trade_journal j WHERE j.trade_id = ?",
            (trade_id,)
        )
        if not row:
            return None
        return {
            "id": row[0],
            "trade_id": row[1],
            "timestamp": row[2],
            "rationale": row[3],
            "emotion": row[4],
            "lesson": row[5],
            "notes": row[6],
        }

    def get_journal_entries(self, limit: int = 20) -> list:
        """
        Get recent journal entries with trade info (direction, entry, status, profit).
        Returns list of dicts, newest first.
        """
        rows = self._query(
            "SELECT j.id, j.trade_id, j.timestamp, j.rationale, j.emotion, j.lesson, j.notes, "
            "t.direction, t.entry, t.status, t.profit, t.pattern "
            "FROM trade_journal j "
            "LEFT JOIN trades t ON j.trade_id = t.id "
            "ORDER BY j.timestamp DESC LIMIT ?",
            (limit,)
        )
        entries = []
        for row in rows:
            entries.append({
                "id": row[0],
                "trade_id": row[1],
                "timestamp": row[2],
                "rationale": row[3],
                "emotion": row[4],
                "lesson": row[5],
                "notes": row[6],
                "trade": {
                    "direction": row[7],
                    "entry": row[8],
                    "status": row[9],
                    "profit": row[10],
                    "pattern": row[11],
                } if row[7] is not None else None,
            })
        return entries

