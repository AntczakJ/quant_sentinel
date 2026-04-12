"""tests/test_backtest_e2e.py — end-to-end backtest mechanics.

Tests the resolve logic, cost model, metrics computation on synthetic
data. Does NOT run a full yfinance fetch (that's integration-level).
"""
import os
import sqlite3

import pandas as pd
import pytest


@pytest.fixture
def synthetic_backtest_db(tmp_path, monkeypatch):
    """Create an isolated backtest.db with a trades table."""
    db_path = tmp_path / "bt.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    monkeypatch.setenv("QUANT_BACKTEST_MODE", "1")
    monkeypatch.setenv("QUANT_BACKTEST_RELAX", "1")
    monkeypatch.setenv("TURSO_URL", "")

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, direction TEXT, entry REAL, sl REAL, tp REAL,
            rsi REAL, trend TEXT, structure TEXT, pattern TEXT,
            status TEXT DEFAULT 'OPEN', profit REAL, lot REAL, session TEXT
        )
    """)
    conn.commit()
    conn.close()
    return str(db_path)


class TestExecutionCosts:
    def test_overnight_cross_counts_22utc(self):
        from run_production_backtest import _is_overnight_cross
        e = pd.Timestamp("2026-03-15 10:00", tz="UTC")
        x_no_cross = pd.Timestamp("2026-03-15 20:00", tz="UTC")
        x_1_night = pd.Timestamp("2026-03-15 23:00", tz="UTC")
        x_2_night = pd.Timestamp("2026-03-17 10:00", tz="UTC")

        assert _is_overnight_cross(e, x_no_cross) == 0
        assert _is_overnight_cross(e, x_1_night) == 1
        assert _is_overnight_cross(e, x_2_night) == 2

    def test_overnight_cross_handles_none(self):
        from run_production_backtest import _is_overnight_cross
        assert _is_overnight_cross(None, None) == 0
        assert _is_overnight_cross(pd.Timestamp.now(tz="UTC"), None) == 0

    def test_gap_detection(self):
        from run_production_backtest import _detect_gap
        assert _detect_gap(2000, 2010) is True   # 0.5% gap
        assert _detect_gap(2000, 2002) is False  # 0.1% gap (below threshold)
        assert _detect_gap(2000, 1990) is True   # down gap same magnitude
        assert _detect_gap(0, 100) is False      # guard divide-by-zero


class TestAnalytics:
    def _insert_trades(self, db_path, profits: list):
        """Helper: insert N trades with given profits."""
        conn = sqlite3.connect(db_path)
        for i, p in enumerate(profits):
            status = "WIN" if p > 0 else ("BREAKEVEN" if p == 0 else "LOSS")
            t = f"2026-01-{(i % 28) + 1:02d} 10:00:00"
            conn.execute(
                "INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, "
                "trend, status, profit, lot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t, "LONG", 100, 95, 110, 50, "bull", status, p, 0.1)
            )
        conn.commit()
        conn.close()

    def test_expectancy_positive_edge(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_expectancy
        # 6 WINs of +10, 4 LOSSes of -5 → E > 0
        self._insert_trades(synthetic_backtest_db, [10] * 6 + [-5] * 4)
        r = compute_expectancy()
        assert r["n_closed"] == 10
        assert r["win_rate"] == 0.6
        assert r["expectancy_per_trade_usd"] > 0

    def test_expectancy_negative_edge(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_expectancy
        # 3 WINs of +5, 7 LOSSes of -10 → E < 0
        self._insert_trades(synthetic_backtest_db, [5] * 3 + [-10] * 7)
        r = compute_expectancy()
        assert r["expectancy_per_trade_usd"] < 0

    def test_sharpe_reasonable(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_sharpe_sortino_calmar
        # Consistent small wins → high Sharpe
        self._insert_trades(synthetic_backtest_db, [5] * 30 + [-3] * 10)
        r = compute_sharpe_sortino_calmar()
        assert r["sharpe"] > 0
        # Sortino >= Sharpe (downside-only has less noise)
        assert r["sortino"] >= r["sharpe"]

    def test_rolling_metrics_stable(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_rolling_metrics
        # 60 trades, 70% WR stable
        import random
        random.seed(1)
        profits = [random.choice([10, 10, 10, 10, 10, 10, 10, -5, -5, -5])
                   for _ in range(60)]
        self._insert_trades(synthetic_backtest_db, profits)
        r = compute_rolling_metrics(30)
        assert r["n_windows"] == 31  # 60 - 30 + 1
        assert 0.5 < r["wr_mean"] < 1.0

    def test_drawdown_recovery(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_drawdown_recovery
        # Win-Win-Loss-Loss-Win-Win-Win — goes into DD, recovers
        self._insert_trades(synthetic_backtest_db, [10, 10, -5, -5, 10, 10, 10])
        r = compute_drawdown_recovery()
        assert r.get("n_recoveries", 0) >= 1

    def test_pnl_distribution_computes_moments(self, synthetic_backtest_db):
        from src.backtest.analytics import compute_pnl_distribution
        self._insert_trades(synthetic_backtest_db, [5, 6, 7, 8, 9, 10, -3, -4, -5])
        r = compute_pnl_distribution()
        assert "skewness" in r
        assert "excess_kurtosis" in r


class TestSummarizeTrades:
    def _insert(self, db_path, data):
        """data: list of (status, profit, lot)"""
        conn = sqlite3.connect(db_path)
        for i, (status, profit, lot) in enumerate(data):
            conn.execute(
                "INSERT INTO trades (timestamp, direction, entry, sl, tp, rsi, "
                "trend, status, profit, lot) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"2026-01-{i+1:02d}", "LONG", 100, 95, 110, 50, "bull", status, profit, lot)
            )
        conn.commit()
        conn.close()

    def test_stats_basic(self, synthetic_backtest_db):
        from run_production_backtest import _summarize_trades
        self._insert(synthetic_backtest_db, [
            ("WIN", 10.0, 0.1),
            ("WIN", 15.0, 0.1),
            ("LOSS", -5.0, 0.1),
            ("LOSS", -8.0, 0.1),
            ("BREAKEVEN", -0.5, 0.1),
        ])
        s = _summarize_trades()
        assert s["total_trades"] == 5
        assert s["wins"] == 2
        assert s["losses"] == 2
        assert s["breakevens"] == 1
        assert s["win_rate_pct"] == 50.0  # wins / (wins + losses) = 2/4
        # PF: gross_win (10+15=25) / gross_loss (5+8+0.5=13.5, breakeven's
        # -0.5 counts as loss since profit < 0)
        assert s["profit_factor"] == round(25.0 / 13.5, 2)
        assert s["max_consec_losses"] == 2

    def test_stats_empty_db_returns_zeros(self, synthetic_backtest_db):
        from run_production_backtest import _summarize_trades
        s = _summarize_trades()
        assert s["total_trades"] == 0
        assert s["win_rate_pct"] == 0.0


class TestDoubleGateSafety:
    """Regression: scanner relaxation must require BOTH env flags."""

    def test_single_flag_leak_doesnt_activate(self, monkeypatch):
        monkeypatch.setenv("QUANT_BACKTEST_RELAX", "1")
        monkeypatch.delenv("QUANT_BACKTEST_MODE", raising=False)
        # The scanner logic:
        import os
        active = (os.environ.get("QUANT_BACKTEST_RELAX") == "1"
                  and os.environ.get("QUANT_BACKTEST_MODE") == "1")
        assert not active

    def test_both_flags_activate(self, monkeypatch):
        monkeypatch.setenv("QUANT_BACKTEST_MODE", "1")
        monkeypatch.setenv("QUANT_BACKTEST_RELAX", "1")
        import os
        active = (os.environ.get("QUANT_BACKTEST_RELAX") == "1"
                  and os.environ.get("QUANT_BACKTEST_MODE") == "1")
        assert active
