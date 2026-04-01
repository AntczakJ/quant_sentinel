"""
database.py — warstwa dostępu do bazy danych SQLite lub Turso (libsql).
"""

import os
import json
import datetime
from typing import Optional

from src.logger import logger

# ======================== DATABASE CONNECTION ========================

DATABASE_URL = os.getenv("DATABASE_URL", "data/sentinel.db")
DATABASE_TOKEN = os.getenv("DATABASE_TOKEN")  # optional, used only for Turso

if DATABASE_URL.startswith("libsql://"):
    # Use Turso (remote SQLite)
    try:
        import libsql
        if DATABASE_TOKEN:
            _conn = libsql.connect(DATABASE_URL, auth_token=DATABASE_TOKEN)
        else:
            # fallback: token may be in URL as query param
            _conn = libsql.connect(DATABASE_URL)
        _cursor = _conn.cursor()
        _using_sqlite = False
        logger.info(f"Using Turso database: {DATABASE_URL}")
    except ImportError:
        logger.error("libsql-client not installed. Run: pip install libsql-client")
        raise
else:
    # Use local SQLite
    import sqlite3
    os.makedirs(os.path.dirname(DATABASE_URL), exist_ok=True)
    _conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    _cursor = _conn.cursor()
    _using_sqlite = True
    logger.info(f"Using local SQLite database: {DATABASE_URL}")

# ======================== DATABASE CLASS ========================

class NewsDB:
    def __init__(self):
        self.conn = _conn
        self.cursor = _cursor
        self.create_tables()
        self.migrate()

    def _execute(self, sql: str, params: tuple = ()):
        """Execute SQL, committing if needed (works for both sqlite3 and libsql)."""
        try:
            self.cursor.execute(sql, params)
            # For modifications, commit
            if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
                self.conn.commit()
        except Exception as e:
            logger.error(f"Database error: {e}\nSQL: {sql}\nParams: {params}")
            raise

    def _fetchone(self):
        return self.cursor.fetchone()

    def _fetchall(self):
        return self.cursor.fetchall()

    # ----- Table creation (SQLite syntax, works with libsql) -----
    def create_tables(self):
        # 1. News dedup
        self._execute("CREATE TABLE IF NOT EXISTS processed_news (title_hash TEXT PRIMARY KEY)")

        # 2. User settings
        self._execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 1000.0,
                risk_percent REAL DEFAULT 1.0
            )
        """)

        # 3. Trades
        self._execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                direction TEXT,
                entry REAL,
                sl REAL,
                tp REAL,
                rsi REAL,
                trend TEXT,
                structure TEXT DEFAULT 'Stable',
                status TEXT DEFAULT 'OPEN',
                failure_reason TEXT,
                condition_at_loss TEXT,
                pattern TEXT,
                factors TEXT,
                lot REAL,
                profit REAL,
                session TEXT
            )
        """)

        # 4. Scanner signals
        self._execute("""
            CREATE TABLE IF NOT EXISTS scanner_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                direction TEXT,
                entry REAL,
                sl REAL,
                tp REAL,
                rsi REAL,
                trend TEXT,
                structure TEXT,
                status TEXT DEFAULT 'PENDING'
            )
        """)

        # 5. Pattern stats
        self._execute("""
            CREATE TABLE IF NOT EXISTS pattern_stats (
                pattern TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 6. Dynamic params
        self._execute("""
            CREATE TABLE IF NOT EXISTS dynamic_params (
                param_name TEXT PRIMARY KEY,
                param_value REAL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 7. Session stats
        self._execute("""
            CREATE TABLE IF NOT EXISTS session_stats (
                pattern TEXT,
                session TEXT,
                count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (pattern, session)
            )
        """)

    def migrate(self):
        """Add missing columns to existing tables (SQLite syntax)."""
        try:
            self.cursor.execute("PRAGMA table_info(trades)")
            columns = [col[1] for col in self.cursor.fetchall()]
            needed = {
                'pattern': 'TEXT',
                'failure_reason': 'TEXT',
                'condition_at_loss': 'TEXT',
                'factors': 'TEXT',
                'session': 'TEXT',
                'lot': 'REAL',
                'profit': 'REAL'
            }
            for col, typ in needed.items():
                if col not in columns:
                    self._execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
        except Exception as e:
            logger.warning(f"Migration: {e}")

    # ----- Helper methods -----
    def get_session(self, timestamp: str) -> str:
        hour = int(timestamp[11:13])
        if 0 <= hour < 8:
            return "Asia"
        elif 8 <= hour < 16:
            return "London"
        else:
            return "NewYork"

    def update_pattern_stats(self, pattern: str, outcome: str):
        self.cursor.execute("SELECT count, wins, losses FROM pattern_stats WHERE pattern = ?", (pattern,))
        row = self.cursor.fetchone()
        if row:
            count, wins, losses = row
            count += 1
            if outcome == "PROFIT":
                wins += 1
            else:
                losses += 1
            win_rate = wins / count if count > 0 else 0
            self._execute(
                "UPDATE pattern_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE pattern=?",
                (count, wins, losses, win_rate, pattern)
            )
        else:
            wins = 1 if outcome == "PROFIT" else 0
            losses = 1 if outcome == "LOSS" else 0
            win_rate = wins / (wins + losses) if wins+losses>0 else 0
            self._execute(
                "INSERT INTO pattern_stats (pattern, count, wins, losses, win_rate) VALUES (?, ?, ?, ?, ?)",
                (pattern, 1, wins, losses, win_rate)
            )

    def get_pattern_stats(self, pattern: str) -> dict:
        self.cursor.execute("SELECT count, wins, losses, win_rate FROM pattern_stats WHERE pattern = ?", (pattern,))
        row = self.cursor.fetchone()
        if row:
            return {"count": row[0], "wins": row[1], "losses": row[2], "win_rate": row[3]}
        return {"count": 0, "wins": 0, "losses": 0, "win_rate": 0}

    def get_all_patterns_stats(self) -> list:
        self.cursor.execute("SELECT pattern, count, wins, losses, win_rate FROM pattern_stats ORDER BY win_rate DESC")
        return self.cursor.fetchall()

    def set_param(self, name: str, value: float):
        self._execute(
            "INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value, last_updated=CURRENT_TIMESTAMP",
            (name, value)
        )

    def get_param(self, name: str, default: float = None) -> Optional[float]:
        self.cursor.execute("SELECT param_value FROM dynamic_params WHERE param_name = ?", (name,))
        row = self.cursor.fetchone()
        return row[0] if row else default

    def update_session_stats(self, pattern: str, session: str, outcome: str):
        self.cursor.execute(
            "SELECT count, wins, losses FROM session_stats WHERE pattern = ? AND session = ?",
            (pattern, session)
        )
        row = self.cursor.fetchone()
        if row:
            count, wins, losses = row
            count += 1
            if outcome == "PROFIT":
                wins += 1
            else:
                losses += 1
            win_rate = wins / count if count > 0 else 0
            self._execute(
                "UPDATE session_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE pattern=? AND session=?",
                (count, wins, losses, win_rate, pattern, session)
            )
        else:
            wins = 1 if outcome == "PROFIT" else 0
            losses = 1 if outcome == "LOSS" else 0
            win_rate = wins / (wins + losses) if wins+losses>0 else 0
            self._execute(
                "INSERT INTO session_stats (pattern, session, count, wins, losses, win_rate) VALUES (?, ?, ?, ?, ?, ?)",
                (pattern, session, 1, wins, losses, win_rate)
            )

    def get_session_stats(self, pattern: str = None) -> list:
        if pattern:
            self.cursor.execute(
                "SELECT pattern, session, count, wins, losses, win_rate FROM session_stats WHERE pattern = ? ORDER BY win_rate DESC",
                (pattern,)
            )
        else:
            self.cursor.execute(
                "SELECT pattern, session, count, wins, losses, win_rate FROM session_stats ORDER BY pattern, win_rate DESC"
            )
        return self.cursor.fetchall()

    def init_weights(self):
        # Factor weights
        factor_weights = {
            'weight_ob_main': 2.0, 'weight_ob_m5': 1.5, 'weight_ob_h1': 1.5,
            'weight_fvg': 1.5, 'weight_grab_mss': 2.0, 'weight_dbr_rbd': 1.5,
            'weight_news': 1.0, 'weight_macro': 1.5, 'weight_rsi_opt': 1.0,
            'weight_m5_confluence': 1.0, 'weight_bos': 1.5, 'weight_choch': 1.5,
            'weight_ob_count': 0.8, 'weight_ob_confluence': 0.8, 'weight_choch_h1': 1.2,
            'weight_supply_demand': 1.5, 'weight_rsi_divergence': 1.5,
        }
        for name, val in factor_weights.items():
            if self.get_param(name) is None:
                self.set_param(name, val)

        # Other params
        other_params = {
            'min_score': 5.0,
            'risk_percent': 1.0,
            'min_tp_distance_mult': 1.0,
            'target_rr': 2.5,
        }
        for name, val in other_params.items():
            if self.get_param(name) is None:
                self.set_param(name, val)

    def get_trade_factors(self, trade_id: int) -> dict:
        self.cursor.execute("SELECT factors FROM trades WHERE id = ?", (trade_id,))
        row = self.cursor.fetchone()
        if row and row[0]:
            return json.loads(row[0])
        return {}

    def update_balance(self, user_id: int, amount: float):
        self._execute(
            "INSERT INTO user_settings (user_id, balance) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance",
            (user_id, amount)
        )

    def get_balance(self, user_id: int) -> float:
        self.cursor.execute("SELECT balance FROM user_settings WHERE user_id = ?", (user_id,))
        res = self.cursor.fetchone()
        return res[0] if res else 1000.0

    def get_performance_stats(self):
        self.cursor.execute("SELECT status, COUNT(*) FROM trades GROUP BY status")
        results = dict(self.cursor.fetchall())
        self.cursor.execute("SELECT timestamp, direction, status FROM trades ORDER BY id DESC LIMIT 5")
        history = self.cursor.fetchall()
        return results, history

    def log_trade(self, direction, price, sl, tp, rsi, trend, structure="Stable", pattern=None, factors=None, lot=None, profit=None):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session = self.get_session(ts)
        factors_json = json.dumps(factors) if factors else None
        self._execute(
            """
            INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, trend, structure, pattern, factors, session, lot, profit)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, direction, price, sl, tp, rsi, trend, structure, pattern, factors_json, session, lot, profit)
        )

    def get_open_trades(self):
        self.cursor.execute("SELECT id, direction, entry, sl, tp FROM trades WHERE status = 'OPEN'")
        return self.cursor.fetchall()

    def update_trade_profit(self, trade_id: int, profit: float):
        self._execute("UPDATE trades SET profit = ? WHERE id = ?", (profit, trade_id))

    def update_trade_status(self, trade_id: int, status: str):
        self._execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))

    def get_failures_report(self) -> str:
        self.cursor.execute("""
            SELECT direction, rsi, trend, entry, structure FROM trades
            WHERE status = 'LOSS' ORDER BY id DESC LIMIT 5
        """)
        losses = self.cursor.fetchall()
        if not losses:
            return "Brak zarejestrowanych porażek."
        report = "ANALIZA PORAŻEK:\n"
        for l in losses:
            report += f"- Strata na {l[0]} | RSI: {l[1]} | Trend: {l[2]} | Struktura: {l[4]}\n"
        return report

    def log_loss_details(self, trade_id, reason, market_condition):
        self._execute(
            "UPDATE trades SET failure_reason = ?, condition_at_loss = ? WHERE id = ?",
            (reason, market_condition, trade_id)
        )

    def get_recent_lessons(self, limit=5):
        self.cursor.execute("""
            SELECT direction, entry, rsi, trend, status FROM trades 
            WHERE status = 'LOSS' ORDER BY id DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

    def save_scanner_signal(self, direction, entry, sl, tp, rsi, trend, structure):
        self._execute("""
            INSERT INTO scanner_signals (direction, entry, sl, tp, rsi, trend, structure, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """, (direction, entry, sl, tp, rsi, trend, structure))

    def check_trade_outcomes(self, current_gold_price):
        self.cursor.execute("SELECT id, direction, sl, tp, rsi, trend, structure FROM scanner_signals WHERE status = 'PENDING'")
        active = self.cursor.fetchall()
        for sig in active:
            sig_id, direction, sl, tp, rsi, trend, structure = sig
            status = None
            if direction == "LONG":
                if current_gold_price >= tp: status = "WIN"
                elif current_gold_price <= sl: status = "LOSS"
            else:
                if current_gold_price <= tp: status = "WIN"
                elif current_gold_price >= sl: status = "LOSS"
            if status:
                self._execute("UPDATE scanner_signals SET status = ? WHERE id = ?", (status, sig_id))

    def get_fail_rate_for_pattern(self, rsi, structure):
        try:
            self.cursor.execute("""
                SELECT status FROM trades 
                WHERE rsi BETWEEN ? AND ? AND structure = ?
            """, (rsi - 5, rsi + 5, structure))
            results = self.cursor.fetchall()
            if not results or len(results) < 3:
                return 0
            losses = sum(1 for r in results if r[0] == 'LOSS')
            return (losses / len(results)) * 100
        except:
            return 0

    def is_news_processed(self, title_hash: str) -> bool:
        self.cursor.execute("SELECT 1 FROM processed_news WHERE title_hash = ?", (title_hash,))
        return self.cursor.fetchone() is not None

    def mark_news_as_processed(self, title_hash: str):
        self._execute("INSERT INTO processed_news (title_hash) VALUES (?)", (title_hash,))  