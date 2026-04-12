"""tests/test_backtest_isolation.py — Production-safety guards for backtest.

CRITICAL: these tests verify the isolation module refuses to run when
DATABASE_URL points at production. A regression here could corrupt the
live trades table.
"""
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Clear relevant env vars before each test so state doesn't leak between tests."""
    for k in ("DATABASE_URL", "TURSO_URL", "TURSO_TOKEN", "QUANT_BACKTEST_MODE"):
        monkeypatch.delenv(k, raising=False)


class TestEnforceIsolation:
    def test_sets_backtest_db_env(self, tmp_path):
        from src.backtest.isolation import enforce_isolation
        db_path = tmp_path / "bt.db"
        enforce_isolation(str(db_path))
        assert os.environ["DATABASE_URL"] == str(db_path)

    def test_disables_turso(self, tmp_path, monkeypatch):
        from src.backtest.isolation import enforce_isolation
        monkeypatch.setenv("TURSO_URL", "libsql://somewhere")
        enforce_isolation(str(tmp_path / "bt.db"))
        assert os.environ["TURSO_URL"] == ""

    def test_marks_backtest_mode(self, tmp_path):
        from src.backtest.isolation import enforce_isolation, is_backtest_mode
        enforce_isolation(str(tmp_path / "bt.db"))
        assert is_backtest_mode()

    def test_refuses_production_db_path(self, monkeypatch):
        """The most important test: setting DATABASE_URL=data/sentinel.db must crash."""
        from src.backtest.isolation import enforce_isolation, BacktestIsolationError
        monkeypatch.setenv("DATABASE_URL", "data/sentinel.db")
        with pytest.raises(BacktestIsolationError, match="production"):
            enforce_isolation("data/backtest.db")

    def test_accepts_empty_database_url(self, tmp_path):
        """Unset DATABASE_URL should be accepted (fresh process)."""
        from src.backtest.isolation import enforce_isolation
        enforce_isolation(str(tmp_path / "bt.db"))
        # No exception — defaults were applied

    def test_creates_parent_directory(self, tmp_path):
        from src.backtest.isolation import enforce_isolation
        nested = tmp_path / "nested" / "deeper" / "bt.db"
        enforce_isolation(str(nested))
        assert nested.parent.exists()

    def test_refuses_symlink_to_production(self, tmp_path, monkeypatch):
        """Even via indirect paths, production DB must be refused.

        Skipped on Windows where symlinks require admin or dev mode.
        """
        prod_file = Path("data") / "sentinel.db"
        if not prod_file.exists():
            pytest.skip("Production DB not present in test env")
        try:
            alias = tmp_path / "pretend_backtest.db"
            alias.symlink_to(prod_file.resolve())
        except (OSError, NotImplementedError):
            pytest.skip("Symlink not available on this platform")
        from src.backtest.isolation import enforce_isolation, BacktestIsolationError
        monkeypatch.setenv("DATABASE_URL", str(alias))
        with pytest.raises(BacktestIsolationError, match="production"):
            enforce_isolation(str(alias))


class TestAssertNotProductionDB:
    def test_passes_for_backtest_db(self, tmp_path, monkeypatch):
        from src.backtest.isolation import assert_not_production_db
        monkeypatch.setenv("DATABASE_URL", str(tmp_path / "bt.db"))
        assert_not_production_db()  # no exception

    def test_crashes_for_sentinel_db(self, monkeypatch):
        from src.backtest.isolation import assert_not_production_db, BacktestIsolationError
        monkeypatch.setenv("DATABASE_URL", "data/sentinel.db")
        with pytest.raises(BacktestIsolationError, match="sentinel.db"):
            assert_not_production_db()

    def test_crashes_for_nested_sentinel_path(self, monkeypatch):
        from src.backtest.isolation import assert_not_production_db, BacktestIsolationError
        monkeypatch.setenv("DATABASE_URL", "some/other/path/sentinel.db")
        with pytest.raises(BacktestIsolationError):
            assert_not_production_db()


class TestBacktestMode:
    def test_false_by_default(self):
        from src.backtest.isolation import is_backtest_mode
        assert not is_backtest_mode()

    def test_true_after_enforce(self, tmp_path):
        from src.backtest.isolation import enforce_isolation, is_backtest_mode
        enforce_isolation(str(tmp_path / "bt.db"))
        assert is_backtest_mode()
