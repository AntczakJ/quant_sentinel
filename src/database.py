"""
database.py — warstwa dostępu do bazy danych SQLite.
Zawiera pełną logikę newsów, finansów, transakcji oraz Feedback Loop dla AI.
"""

import sqlite3
import os

class NewsDB:
    def __init__(self, db_path="data/sentinel.db"):
        # Upewniamy się, że folder 'data/' istnieje
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # Połączenie z bazą
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate()

    def create_tables(self):
        """Tworzy wszystkie wymagane tabele jeśli jeszcze nie istnieją."""
        with self.conn:
            # 1. Newsy
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS processed_news (title_hash TEXT PRIMARY KEY)"
            )

            # 2. Ustawienia użytkownika
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS user_settings
                              (
                                  user_id
                                  INTEGER
                                  PRIMARY
                                  KEY,
                                  balance
                                  REAL
                                  DEFAULT
                                  1000.0,
                                  risk_percent
                                  REAL
                                  DEFAULT
                                  1.0
                              )
                              """)

            # 3. Główna tabela transakcji (dodajemy kolumnę pattern)
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS trades
                              (
                                  id
                                  INTEGER
                                  PRIMARY
                                  KEY
                                  AUTOINCREMENT,
                                  timestamp
                                  DATETIME
                                  DEFAULT
                                  CURRENT_TIMESTAMP,
                                  direction
                                  TEXT,
                                  entry
                                  REAL,
                                  sl
                                  REAL,
                                  tp
                                  REAL,
                                  rsi
                                  REAL,
                                  trend
                                  TEXT,
                                  structure
                                  TEXT
                                  DEFAULT
                                  'Stable',
                                  status
                                  TEXT
                                  DEFAULT
                                  'OPEN',
                                  failure_reason
                                  TEXT,
                                  condition_at_loss
                                  TEXT,
                                  pattern
                                  TEXT
                                  factors 
                                  TEXT          -- nowa kolumna: JSON z obecnymi czynnikami
                              )
                              """)

            # 4. Tabela Skanera
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS scanner_signals
                              (
                                  id
                                  INTEGER
                                  PRIMARY
                                  KEY
                                  AUTOINCREMENT,
                                  timestamp
                                  DATETIME
                                  DEFAULT
                                  CURRENT_TIMESTAMP,
                                  direction
                                  TEXT,
                                  entry
                                  REAL,
                                  sl
                                  REAL,
                                  tp
                                  REAL,
                                  rsi
                                  REAL,
                                  trend
                                  TEXT,
                                  structure
                                  TEXT,
                                  status
                                  TEXT
                                  DEFAULT
                                  'PENDING'
                              )
                              """)

            # 5. Tabela statystyk wzorców
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS pattern_stats
                              (
                                  pattern
                                  TEXT
                                  PRIMARY
                                  KEY,
                                  count
                                  INTEGER
                                  DEFAULT
                                  0,
                                  wins
                                  INTEGER
                                  DEFAULT
                                  0,
                                  losses
                                  INTEGER
                                  DEFAULT
                                  0,
                                  win_rate
                                  REAL
                                  DEFAULT
                                  0,
                                  last_updated
                                  TIMESTAMP
                                  DEFAULT
                                  CURRENT_TIMESTAMP
                              )
                              """)

            # 6. Tabela parametrów dynamicznych
            self.conn.execute("""
                              CREATE TABLE IF NOT EXISTS dynamic_params
                              (
                                  param_name
                                  TEXT
                                  PRIMARY
                                  KEY,
                                  param_value
                                  REAL,
                                  last_updated
                                  TIMESTAMP
                                  DEFAULT
                                  CURRENT_TIMESTAMP
                              )
                              """)

    def migrate(self):
        """Dodaje brakujące kolumny do istniejącej bazy."""
        try:
            with self.conn:
                self.cursor.execute("PRAGMA table_info(trades)")
                columns = [column[1] for column in self.cursor.fetchall()]
                if 'pattern' not in columns:
                    self.conn.execute("ALTER TABLE trades ADD COLUMN pattern TEXT")
                if 'failure_reason' not in columns:
                    self.conn.execute("ALTER TABLE trades ADD COLUMN failure_reason TEXT")
                if 'condition_at_loss' not in columns:
                    self.conn.execute("ALTER TABLE trades ADD COLUMN condition_at_loss TEXT")
        except Exception as e:
            print(f"ℹ️ Migracja: {e}")

    # --- ZARZĄDZANIE KAPITAŁEM ---
    def update_pattern_stats(self, pattern: str, outcome: str):
        """Aktualizuje statystyki dla danego wzorca."""
        with self.conn:
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
                self.conn.execute(
                    "UPDATE pattern_stats SET count=?, wins=?, losses=?, win_rate=?, last_updated=CURRENT_TIMESTAMP WHERE pattern=?",
                    (count, wins, losses, win_rate, pattern)
                )
            else:
                wins = 1 if outcome == "PROFIT" else 0
                losses = 1 if outcome == "LOSS" else 0
                win_rate = wins / (wins + losses)
                self.conn.execute(
                    "INSERT INTO pattern_stats (pattern, count, wins, losses, win_rate) VALUES (?, ?, ?, ?, ?)",
                    (pattern, 1, wins, losses, win_rate)
                )

    def get_pattern_stats(self, pattern: str) -> dict:
        """Zwraca statystyki wzorca."""
        self.cursor.execute("SELECT count, wins, losses, win_rate FROM pattern_stats WHERE pattern = ?", (pattern,))
        row = self.cursor.fetchone()
        if row:
            return {"count": row[0], "wins": row[1], "losses": row[2], "win_rate": row[3]}
        return {"count": 0, "wins": 0, "losses": 0, "win_rate": 0}

    def get_all_patterns_stats(self) -> list:
        """Zwraca wszystkie wzorce z win_rate > 0."""
        self.cursor.execute("SELECT pattern, count, wins, losses, win_rate FROM pattern_stats ORDER BY win_rate DESC")
        return self.cursor.fetchall()

    # --- Dynamic parameters ---
    def set_param(self, name: str, value: float):
        """Zapisuje dynamiczny parametr."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO dynamic_params (param_name, param_value) VALUES (?, ?) ON CONFLICT(param_name) DO UPDATE SET param_value=excluded.param_value, last_updated=CURRENT_TIMESTAMP",
                (name, value)
            )

    def get_param(self, name: str, default: float = None) -> float:
        """Odczytuje dynamiczny parametr."""
        self.cursor.execute("SELECT param_value FROM dynamic_params WHERE param_name = ?", (name,))
        row = self.cursor.fetchone()
        return row[0] if row else default


    def update_balance(self, user_id: int, amount: float):
        with self.conn:
            self.conn.execute("""
                INSERT INTO user_settings (user_id, balance)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance
            """, (user_id, amount))

    def get_balance(self, user_id: int) -> float:
        self.cursor.execute("SELECT balance FROM user_settings WHERE user_id = ?", (user_id,))
        res = self.cursor.fetchone()
        return res[0] if res else 1000.0

    # --- STATYSTYKI I HISTORIA ---

    def get_performance_stats(self):
        self.cursor.execute("SELECT status, COUNT(*) FROM trades GROUP BY status")
        results = dict(self.cursor.fetchall())
        self.cursor.execute("SELECT timestamp, direction, status FROM trades ORDER BY id DESC LIMIT 5")
        history = self.cursor.fetchall()
        return results, history

    # --- OBSŁUGA TRANSAKCJI ---

    # src/database.py – log_trade

    def log_trade(self, direction, price, sl, tp, rsi, trend, structure="Stable", pattern=None):
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            self.conn.execute("""
                              INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, trend, structure, pattern)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                              """, (timestamp, direction, price, sl, tp, rsi, trend, structure, pattern))

    def get_open_trades(self):
        self.cursor.execute("SELECT id, direction, entry, sl, tp FROM trades WHERE status = 'OPEN'")
        return self.cursor.fetchall()

    def update_trade_status(self, trade_id: int, status: str):
        with self.conn:
            self.conn.execute("UPDATE trades SET status = ? WHERE id = ?", (status, trade_id))

    # --- AI FEEDBACK LOOP ---

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
        with self.conn:
            self.conn.execute(
                "UPDATE trades SET failure_reason = ?, condition_at_loss = ? WHERE id = ?",
                (reason, market_condition, trade_id)
            )

    def get_recent_lessons(self, limit=5):
        self.cursor.execute("""
            SELECT direction, entry, rsi, trend, status FROM trades 
            WHERE status = 'LOSS' ORDER BY id DESC LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()

    # --- AUTONOMICZNY SKANER ---

    def save_scanner_signal(self, direction, entry, sl, tp, rsi, trend, structure):
        self.cursor.execute("""
            INSERT INTO scanner_signals (direction, entry, sl, tp, rsi, trend, structure, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """, (direction, entry, sl, tp, rsi, trend, structure))
        self.conn.commit()

    def check_trade_outcomes(self, current_gold_price):
        self.cursor.execute("SELECT id, direction, sl, tp, rsi, trend, structure FROM scanner_signals WHERE status = 'PENDING'")
        active_signals = self.cursor.fetchall()
        for sig in active_signals:
            sig_id, direction, sl, tp, rsi, trend, structure = sig
            status = None
            if direction == "LONG":
                if current_gold_price >= tp: status = "WIN"
                elif current_gold_price <= sl: status = "LOSS"
            else: # SHORT
                if current_gold_price <= tp: status = "WIN"
                elif current_gold_price >= sl: status = "LOSS"
            if status:
                with self.conn:
                    self.conn.execute("UPDATE scanner_signals SET status = ? WHERE id = ?", (status, sig_id))

    def get_fail_rate_for_pattern(self, rsi, structure):
        try:
            self.cursor.execute("""
                SELECT status FROM trades 
                WHERE rsi BETWEEN ? AND ? AND structure = ?
            """, (rsi - 5, rsi + 5, structure))
            results = self.cursor.fetchall()
            if not results or len(results) < 3: return 0
            losses = len([r for r in results if r[0] == 'LOSS'])
            return (losses / len(results)) * 100
        except: return 0

    # --- OBSŁUGA NEWSÓW ---
    def is_news_processed(self, title_hash: str) -> bool:
        self.cursor.execute("SELECT 1 FROM processed_news WHERE title_hash = ?", (title_hash,))
        return self.cursor.fetchone() is not None

    def mark_news_as_processed(self, title_hash: str):
        with self.conn:
            self.conn.execute("INSERT INTO processed_news (title_hash) VALUES (?)", (title_hash,))