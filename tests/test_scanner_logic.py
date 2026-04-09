"""
tests/test_scanner_logic.py — Tests for scanner filters, cooldown, session logic
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAdaptiveCooldown:
    def test_cooldown_varies_by_session(self):
        from src.scanner import _get_adaptive_cooldown_hours

        class MockDB:
            def _query(self, *a, **kw): return []

        db = MockDB()
        hours = _get_adaptive_cooldown_hours(db)
        assert isinstance(hours, float)
        assert hours >= 0.5


class TestSessionDetection:
    def test_get_session_from_timestamp(self):
        from src.database import NewsDB
        db = NewsDB()
        assert db.get_session("2026-04-09 03:00:00") == "asian"
        assert db.get_session("2026-04-09 09:00:00") == "london"
        assert db.get_session("2026-04-09 15:00:00") == "overlap"
        assert db.get_session("2026-04-09 19:00:00") == "new_york"
        assert db.get_session("2026-04-09 23:30:00") == "off_hours"

    def test_get_active_session(self):
        from src.smc_engine import get_active_session
        session = get_active_session()
        assert "session" in session
        assert "is_killzone" in session
        assert session["session"] in ("asian", "london", "overlap", "new_york", "off_hours", "weekend")


class TestSessionWinRate:
    def test_returns_dict(self):
        from src.database import NewsDB
        db = NewsDB()
        result = db.get_session_win_rate("london")
        assert isinstance(result, dict)
        assert "session" in result
        assert "sufficient_data" in result

    def test_all_session_performance(self):
        from src.database import NewsDB
        db = NewsDB()
        result = db.get_all_session_performance(min_trades=1)
        assert isinstance(result, list)


class TestMarketOpen:
    def test_is_market_open_returns_bool(self):
        from src.smc_engine import is_market_open
        result = is_market_open()
        assert isinstance(result, bool)
