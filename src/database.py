"""
database.py — warstwa dostępu do bazy danych SQLite lub Turso (libsql).
"""

import os
import json
import datetime
import threading
from typing import Optional

from src.logger import logger

# ======================== DATABASE CONNECTION ========================

DATABASE_URL = os.getenv("DATABASE_URL", "data/sentinel.db")
DATABASE_TOKEN = os.getenv("DATABASE_TOKEN")  # optional, used only for Turso

# Thread lock for concurrent access (FastAPI runs handlers in thread pool)
_db_lock = threading.Lock()

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
    os.makedirs(os.path.dirname(DATABASE_URL) or ".", exist_ok=True)
    _conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    _cursor = _conn.cursor()
    _using_sqlite = True
    logger.info(f"Using local SQLite database: {DATABASE_URL}")

# ======================== DATABASE CLASS ========================

_db_initialized = False  # Module-level flag — schema setup runs only once per process

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
        """Execute SQL, committing if needed (works for both sqlite3 and libsql). Thread-safe."""
        with _db_lock:
            try:
                self.cursor.execute(sql, params)
                # For modifications, commit
                if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
                    self.conn.commit()
            except Exception as e:
                if not _silent:
                    logger.error(f"Database error: {e}\nSQL: {sql}\nParams: {params}")
                raise

    def _fetchone(self):
        return self.cursor.fetchone()

    def _fetchall(self):
        return self.cursor.fetchall()

    def _query(self, sql: str, params: tuple = ()):
        """Execute a SELECT query thread-safely and return all rows."""
        with _db_lock:
            self.cursor.execute(sql, params)
            return self.cursor.fetchall()

    def _query_one(self, sql: str, params: tuple = ()):
        """Execute a SELECT query thread-safely and return first row."""
        with _db_lock:
            self.cursor.execute(sql, params)
            return self.cursor.fetchone()

    # ----- Batch portfolio read (single query instead of 5) -----
    def get_portfolio_params(self) -> dict:
        """Read all portfolio-related params in a single query — 5x faster than individual reads."""
        rows = self._query(
            "SELECT param_name, param_value FROM dynamic_params WHERE param_name LIKE 'portfolio_%'"
        )
        result = {}
        for name, value in rows:
            result[name] = value
        return result

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

        # 8. Agent threads (OpenAI Assistants conversation memory)
        self._execute("""
            CREATE TABLE IF NOT EXISTS agent_threads (
                user_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_used DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 9. ML predictions (ensemble output log for post-hoc analysis)
        self._execute("""
            CREATE TABLE IF NOT EXISTS ml_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                trade_id INTEGER,
                lstm_pred REAL,
                xgb_pred REAL,
                dqn_action INTEGER,
                ensemble_score REAL,
                ensemble_signal TEXT,
                confidence REAL,
                predictions_json TEXT
            )
        """)

        # 10. Regime stats (win rate per macro regime + session)
        self._execute("""
            CREATE TABLE IF NOT EXISTS regime_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT NOT NULL,
                session TEXT NOT NULL,
                direction TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(regime, session, direction)
            )
        """)

        # 11. News sentiment (AI-scored headline sentiment for learning)
        self._execute("""
            CREATE TABLE IF NOT EXISTS news_sentiment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                headline TEXT,
                sentiment TEXT,
                score REAL,
                source TEXT
            )
        """)

    def migrate(self):
        """Add missing columns to existing tables (compatible with SQLite and Turso/libsql)."""
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
            try:
                # Use cursor directly — "duplicate column" is expected and not a real error
                self.cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
                self.conn.commit()
                logger.info(f"Migration: added column trades.{col}")
            except Exception as e:
                # Column already exists — silently skip (expected for Turso and SQLite)
                err_msg = str(e).lower()
                if "duplicate" not in err_msg and "already exists" not in err_msg:
                    logger.debug(f"Migration skip trades.{col}: {e}")

        # Create indexes for performance
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
            logger.debug("Database indexes verified")
        except Exception as e:
            logger.warning(f"Index creation: {e}")

    # ----- Agent thread management -----
    def get_agent_thread(self, user_id: str) -> Optional[str]:
        """Zwraca thread_id dla danego user_id lub None jeśli nie istnieje."""
        try:
            self._execute("SELECT thread_id FROM agent_threads WHERE user_id = ?", (str(user_id),))
            row = self._fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"get_agent_thread error: {e}")
            return None

    def set_agent_thread(self, user_id: str, thread_id: str) -> None:
        """Zapisuje lub aktualizuje thread_id dla danego user_id."""
        self._execute(
            "INSERT OR REPLACE INTO agent_threads (user_id, thread_id, last_used) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (str(user_id), thread_id),
        )

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
            'weight_ichimoku_bull': 1.2,
            'weight_near_poc': 1.0,
            'weight_engulfing_bull': 1.3,
            'weight_engulfing_bear': 1.3,
            'weight_pin_bar_bull': 1.2,
            'weight_pin_bar_bear': 1.2,
            'weight_inside_bar': 0.8,
            'weight_ml_bull': 1.5,
            'weight_ml_bear': 1.5,
            'weight_rl_buy': 1.5,
            'weight_rl_sell': 1.5,

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

    def get_latest_scanner_signal(self):
        """Get the most recent scanner signal (PENDING or latest regardless of status)"""
        self.cursor.execute("""
            SELECT id, direction, entry, sl, tp, rsi, trend, structure
            FROM scanner_signals
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        return self.cursor.fetchone()

    def get_all_scanner_signals(self, limit=50):
        """Get all scanner signals, ordered by most recent first"""
        self.cursor.execute("""
            SELECT id, direction, entry, sl, tp, rsi, trend, structure, status, timestamp
            FROM scanner_signals
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return self.cursor.fetchall() or []

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
        except Exception as e:
            logger.debug(f"get_fail_rate_for_pattern error: {e}")
            return 0

    def is_news_processed(self, title_hash: str) -> bool:
        self.cursor.execute("SELECT 1 FROM processed_news WHERE title_hash = ?", (title_hash,))
        return self.cursor.fetchone() is not None

    def mark_news_as_processed(self, title_hash: str):
        self._execute("INSERT INTO processed_news (title_hash) VALUES (?)", (title_hash,))

    # ----- Regime stats (win rate per macro regime + session + direction) -----
    def update_regime_stats(self, regime: str, session: str, direction: str, outcome: str):
        """Aktualizuje statystyki dla danego reżimu makro + sesji + kierunku."""
        self.cursor.execute(
            "SELECT count, wins, losses FROM regime_stats WHERE regime = ? AND session = ? AND direction = ?",
            (regime, session, direction)
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
                "UPDATE regime_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP "
                "WHERE regime=? AND session=? AND direction=?",
                (count, wins, losses, win_rate, regime, session, direction)
            )
        else:
            wins = 1 if outcome == "PROFIT" else 0
            losses = 1 if outcome == "LOSS" else 0
            win_rate = wins / (wins + losses) if wins + losses > 0 else 0
            self._execute(
                "INSERT INTO regime_stats (regime, session, direction, count, wins, losses, win_rate) "
                "VALUES (?, ?, ?, 1, ?, ?, ?)",
                (regime, session, direction, wins, losses, win_rate)
            )

    def get_regime_stats(self, regime: str = None, session: str = None) -> list:
        """Pobiera statystyki reżimu. Opcjonalnie filtruje."""
        if regime and session:
            self.cursor.execute(
                "SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats "
                "WHERE regime = ? AND session = ? ORDER BY win_rate DESC",
                (regime, session)
            )
        elif regime:
            self.cursor.execute(
                "SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats "
                "WHERE regime = ? ORDER BY win_rate DESC",
                (regime,)
            )
        else:
            self.cursor.execute(
                "SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats "
                "ORDER BY regime, session, win_rate DESC"
            )
        return self.cursor.fetchall()

    # ----- News sentiment persistence -----
    def save_news_sentiment(self, headline: str, sentiment: str, score: float = 0.0, source: str = "rss"):
        """Zapisuje wynik sentymentu nagłówka wiadomości."""
        self._execute(
            "INSERT INTO news_sentiment (headline, sentiment, score, source) VALUES (?, ?, ?, ?)",
            (headline, sentiment, score, source)
        )

    def get_aggregated_news_sentiment(self, hours: int = 24) -> dict:
        """Zwraca zagregowany sentyment z ostatnich N godzin."""
        self.cursor.execute("""
            SELECT sentiment, COUNT(*) as cnt FROM news_sentiment
            WHERE timestamp > datetime('now', ?)
            GROUP BY sentiment
        """, (f"-{hours} hours",))
        rows = self.cursor.fetchall()
        total = sum(r[1] for r in rows) if rows else 0
        result = {"bullish": 0, "bearish": 0, "neutral": 0, "total": total}
        for sentiment, cnt in rows:
            key = sentiment.lower()
            if key in result:
                result[key] = cnt
        if total > 0:
            result["bullish_pct"] = round(result["bullish"] / total * 100, 1)
            result["bearish_pct"] = round(result["bearish"] / total * 100, 1)
        else:
            result["bullish_pct"] = 0
            result["bearish_pct"] = 0
        return result

    # ----- ML predictions log -----
    def get_recent_ml_predictions(self, limit: int = 20) -> list:
        """Pobiera ostatnie predykcje ML."""
        rows = self._query("""
            SELECT id, timestamp, lstm_pred, xgb_pred, dqn_action, ensemble_score, ensemble_signal, confidence
            FROM ml_predictions ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        return rows

    # ----- Advanced trade metrics -----
    def get_trade_performance_metrics(self) -> dict:
        """
        Oblicza zaawansowane metryki wydajności:
        - max drawdown, consecutive wins/losses, avg profit/loss, profit factor, expectancy
        """
        rows = self._query("""
            SELECT status, profit FROM trades
            WHERE status IN ('WIN', 'LOSS', 'PROFIT')
            ORDER BY id ASC
        """)
        if not rows:
            return {
                "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
                "expectancy": 0, "max_consecutive_wins": 0,
                "max_consecutive_losses": 0, "max_drawdown": 0,
                "total_profit": 0,
            }

        wins = losses = 0
        total_win_profit = 0.0
        total_loss_amount = 0.0
        equity_curve = [0.0]
        peak = 0.0
        max_dd = 0.0
        consec_wins = consec_losses = 0
        max_consec_wins = max_consec_losses = 0

        for status, profit in rows:
            p = float(profit or 0)
            is_win = status in ('WIN', 'PROFIT')

            if is_win:
                wins += 1
                total_win_profit += p
                consec_wins += 1
                consec_losses = 0
                max_consec_wins = max(max_consec_wins, consec_wins)
            else:
                losses += 1
                total_loss_amount += abs(p)
                consec_losses += 1
                consec_wins = 0
                max_consec_losses = max(max_consec_losses, consec_losses)

            eq = equity_curve[-1] + p
            equity_curve.append(eq)
            peak = max(peak, eq)
            dd = peak - eq
            max_dd = max(max_dd, dd)

        total = wins + losses
        avg_win = total_win_profit / wins if wins > 0 else 0
        avg_loss = total_loss_amount / losses if losses > 0 else 0
        profit_factor = total_win_profit / total_loss_amount if total_loss_amount > 0 else float('inf') if total_win_profit > 0 else 0
        win_rate = wins / total if total > 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) if total > 0 else 0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate * 100, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999.0,
            "expectancy": round(expectancy, 2),
            "max_consecutive_wins": max_consec_wins,
            "max_consecutive_losses": max_consec_losses,
            "max_drawdown": round(max_dd, 2),
            "total_profit": round(equity_curve[-1], 2),
        }

