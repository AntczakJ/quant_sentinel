"""
database.py - warstwa dostepu do bazy danych SQLite lub Turso (libsql).

Wszystkie operacje SELECT korzystaja z _query() / _query_one() (thread-safe).
Operacje INSERT/UPDATE/DELETE korzystaja z _execute() (thread-safe + auto-commit).
"""

import os
import json
import datetime
import threading
from typing import Optional

from src.logger import logger

# ======================== DATABASE CONNECTION ========================

DATABASE_URL = os.getenv("DATABASE_URL", "data/sentinel.db")
DATABASE_TOKEN = os.getenv("DATABASE_TOKEN")

_db_lock = threading.Lock()

if DATABASE_URL.startswith("libsql://"):
    try:
        import libsql
        if DATABASE_TOKEN:
            _conn = libsql.connect(DATABASE_URL, auth_token=DATABASE_TOKEN)
        else:
            _conn = libsql.connect(DATABASE_URL)
        _cursor = _conn.cursor()
        _using_sqlite = False
        logger.info(f"Using Turso database: {DATABASE_URL}")
    except ImportError:
        logger.error("libsql-client not installed. Run: pip install libsql-client")
        raise
else:
    import sqlite3
    os.makedirs(os.path.dirname(DATABASE_URL) or ".", exist_ok=True)
    _conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    _cursor = _conn.cursor()
    _using_sqlite = True
    logger.info(f"Using local SQLite database: {DATABASE_URL}")

# ======================== DATABASE CLASS ========================

_db_initialized = False


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
        """Execute SQL, committing if needed. Thread-safe."""
        with _db_lock:
            try:
                self.cursor.execute(sql, params)
                if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")):
                    self.conn.commit()
            except Exception as e:
                if not _silent:
                    logger.error(f"Database error: {e}\nSQL: {sql}\nParams: {params}")
                raise

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

    def get_portfolio_params(self) -> dict:
        rows = self._query("SELECT param_name, param_value FROM dynamic_params WHERE param_name LIKE 'portfolio_%'")
        return {name: value for name, value in rows}

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
            param_name TEXT PRIMARY KEY, param_value REAL, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        self._execute("""CREATE TABLE IF NOT EXISTS session_stats (
            pattern TEXT, session TEXT, count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, win_rate REAL DEFAULT 0, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (pattern, session))""")
        self._execute("""CREATE TABLE IF NOT EXISTS agent_threads (
            user_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, last_used DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        self._execute("""CREATE TABLE IF NOT EXISTS ml_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            trade_id INTEGER, lstm_pred REAL, xgb_pred REAL, dqn_action INTEGER,
            ensemble_score REAL, ensemble_signal TEXT, confidence REAL, predictions_json TEXT)""")
        self._execute("""CREATE TABLE IF NOT EXISTS regime_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT NOT NULL, session TEXT NOT NULL,
            direction TEXT NOT NULL, count INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, win_rate REAL DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(regime, session, direction))""")
        self._execute("""CREATE TABLE IF NOT EXISTS news_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            headline TEXT, sentiment TEXT, score REAL, source TEXT)""")

    def migrate(self):
        needed = {'pattern': 'TEXT', 'failure_reason': 'TEXT', 'condition_at_loss': 'TEXT',
                  'factors': 'TEXT', 'session': 'TEXT', 'lot': 'REAL', 'profit': 'REAL'}
        for col, typ in needed.items():
            try:
                with _db_lock:
                    self.cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
                    self.conn.commit()
                logger.info(f"Migration: added column trades.{col}")
            except Exception as e:
                err_msg = str(e).lower()
                if "duplicate" not in err_msg and "already exists" not in err_msg:
                    logger.debug(f"Migration skip trades.{col}: {e}")
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
        except Exception as e:
            logger.warning(f"Index creation: {e}")

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
        hour = int(timestamp[11:13])
        if 0 <= hour < 8: return "Asia"
        elif 8 <= hour < 16: return "London"
        else: return "NewYork"

    def update_pattern_stats(self, pattern: str, outcome: str):
        row = self._query_one("SELECT count, wins, losses FROM pattern_stats WHERE pattern = ?", (pattern,))
        if row:
            count, wins, losses = row
            count += 1
            if outcome == "PROFIT": wins += 1
            else: losses += 1
            wr = wins / count if count > 0 else 0
            self._execute("UPDATE pattern_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE pattern=?", (count, wins, losses, wr, pattern))
        else:
            wins = 1 if outcome == "PROFIT" else 0
            losses = 1 if outcome == "LOSS" else 0
            wr = wins / (wins + losses) if wins + losses > 0 else 0
            self._execute("INSERT INTO pattern_stats (pattern, count, wins, losses, win_rate) VALUES (?, ?, ?, ?, ?)", (pattern, 1, wins, losses, wr))

    def get_pattern_stats(self, pattern: str) -> dict:
        row = self._query_one("SELECT count, wins, losses, win_rate FROM pattern_stats WHERE pattern = ?", (pattern,))
        if row: return {"count": row[0], "wins": row[1], "losses": row[2], "win_rate": row[3]}
        return {"count": 0, "wins": 0, "losses": 0, "win_rate": 0}

    def get_all_patterns_stats(self) -> list:
        return self._query("SELECT pattern, count, wins, losses, win_rate FROM pattern_stats ORDER BY win_rate DESC")

    def set_param(self, name: str, value):
        self._execute("INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value, last_updated=CURRENT_TIMESTAMP", (name, value))

    def get_param(self, name: str, default=None):
        row = self._query_one("SELECT param_value FROM dynamic_params WHERE param_name = ?", (name,))
        return row[0] if row else default

    def update_session_stats(self, pattern: str, session: str, outcome: str):
        row = self._query_one("SELECT count, wins, losses FROM session_stats WHERE pattern = ? AND session = ?", (pattern, session))
        if row:
            count, wins, losses = row
            count += 1
            if outcome == "PROFIT": wins += 1
            else: losses += 1
            wr = wins / count if count > 0 else 0
            self._execute("UPDATE session_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE pattern=? AND session=?", (count, wins, losses, wr, pattern, session))
        else:
            wins = 1 if outcome == "PROFIT" else 0
            losses = 1 if outcome == "LOSS" else 0
            wr = wins / (wins + losses) if wins + losses > 0 else 0
            self._execute("INSERT INTO session_stats (pattern, session, count, wins, losses, win_rate) VALUES (?, ?, ?, ?, ?, ?)", (pattern, session, 1, wins, losses, wr))

    def get_session_stats(self, pattern: str = None) -> list:
        if pattern:
            return self._query("SELECT pattern, session, count, wins, losses, win_rate FROM session_stats WHERE pattern = ? ORDER BY win_rate DESC", (pattern,))
        return self._query("SELECT pattern, session, count, wins, losses, win_rate FROM session_stats ORDER BY pattern, win_rate DESC")

    def init_weights(self):
        fw = {'weight_ob_main': 2.0, 'weight_ob_m5': 1.5, 'weight_ob_h1': 1.5, 'weight_fvg': 1.5, 'weight_grab_mss': 2.0, 'weight_dbr_rbd': 1.5, 'weight_news': 1.0, 'weight_macro': 1.5, 'weight_rsi_opt': 1.0, 'weight_m5_confluence': 1.0, 'weight_bos': 1.5, 'weight_choch': 1.5, 'weight_ob_count': 0.8, 'weight_ob_confluence': 0.8, 'weight_choch_h1': 1.2, 'weight_supply_demand': 1.5, 'weight_rsi_divergence': 1.5, 'weight_ichimoku_bull': 1.2, 'weight_near_poc': 1.0, 'weight_engulfing_bull': 1.3, 'weight_engulfing_bear': 1.3, 'weight_pin_bar_bull': 1.2, 'weight_pin_bar_bear': 1.2, 'weight_inside_bar': 0.8, 'weight_ml_bull': 1.5, 'weight_ml_bear': 1.5, 'weight_rl_buy': 1.5, 'weight_rl_sell': 1.5}
        for name, val in fw.items():
            if self.get_param(name) is None: self.set_param(name, val)
        for name, val in {'min_score': 5.0, 'risk_percent': 1.0, 'min_tp_distance_mult': 1.0, 'target_rr': 2.5}.items():
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
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session = self.get_session(ts)
        fj = json.dumps(factors) if factors else None
        self._execute("INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, trend, structure, pattern, factors, session, lot, profit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (ts, direction, price, sl, tp, rsi, trend, structure, pattern, fj, session, lot, profit))

    def get_open_trades(self):
        return self._query("SELECT id, direction, entry, sl, tp FROM trades WHERE status = 'OPEN'")

    def update_trade_profit(self, trade_id: int, profit: float):
        self._execute("UPDATE trades SET profit = ? WHERE id = ?", (profit, trade_id))

    def backfill_trade_profits(self) -> int:
        rows = self._query("SELECT id, direction, entry, sl, tp, status FROM trades WHERE status IN ('WIN', 'LOSS', 'PROFIT') AND (profit IS NULL OR profit = 0 OR profit = 0.0)")
        if not rows: return 0
        updated = 0
        for t_id, direction, entry, sl, tp, status in rows:
            try:
                ef, sf, tf = float(entry or 0), float(sl or 0), float(tp or 0)
                if ef <= 0: continue
                pv = round(abs(tf - ef), 2) if status in ('WIN', 'PROFIT') else round(-abs(ef - sf), 2)
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
        except Exception: pass
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
        return self._query_one("SELECT id, direction, entry, sl, tp, rsi, trend, structure FROM scanner_signals ORDER BY timestamp DESC LIMIT 1")

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
        row = self._query_one("SELECT count, wins, losses FROM regime_stats WHERE regime = ? AND session = ? AND direction = ?", (regime, session, direction))
        if row:
            c, w, l = row; c += 1
            if outcome == "PROFIT": w += 1
            else: l += 1
            wr = w / c if c > 0 else 0
            self._execute("UPDATE regime_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE regime=? AND session=? AND direction=?", (c, w, l, wr, regime, session, direction))
        else:
            w = 1 if outcome == "PROFIT" else 0; l = 1 if outcome == "LOSS" else 0
            wr = w / (w + l) if w + l > 0 else 0
            self._execute("INSERT INTO regime_stats (regime, session, direction, count, wins, losses, win_rate) VALUES (?, ?, ?, 1, ?, ?, ?)", (regime, session, direction, w, l, wr))

    def get_regime_stats(self, regime: str = None, session: str = None) -> list:
        if regime and session:
            return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats WHERE regime = ? AND session = ? ORDER BY win_rate DESC", (regime, session))
        elif regime:
            return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats WHERE regime = ? ORDER BY win_rate DESC", (regime,))
        return self._query("SELECT regime, session, direction, count, wins, losses, win_rate FROM regime_stats ORDER BY regime, session, win_rate DESC")

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

