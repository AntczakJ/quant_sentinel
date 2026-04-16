#!/usr/bin/env python3
"""tests/conftest.py - Pytest configuration and fixtures"""

import pytest
import sys
import io
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Fix Windows console encoding — prevent UnicodeEncodeError on emoji/unicode
if sys.platform == "win32":
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

@pytest.fixture(autouse=True)
def _reset_backtest_env(monkeypatch, tmp_path_factory):
    """Clear backtest env vars + pin DATABASE_URL to a PER-TEST temp file.

    Evolution:
    2026-04-13: cleared QUANT_BACKTEST_* env to prevent state leaks.
    2026-04-16 AM: pinned DATABASE_URL to shared data/test_sentinel.db
      (stopped pytest writing to prod — 6 fake trades incident).
    2026-04-16 PM: extended to per-test temp DB. Shared test_sentinel.db
      still bled state between tests — compliance audit chain, stale
      OPEN trades [-1] grabs, pattern weights. Now each test gets a
      fresh SQLite via tmp_path_factory, so NO cross-test pollution
      possible.

    Tests that need a specific DB (e.g. test_backtest_grid's isolation
    harness) can override with their own monkeypatch.setenv AFTER this
    fixture runs.
    """
    for var in ("QUANT_BACKTEST_MODE", "QUANT_BACKTEST_RELAX",
                "QUANT_BACKTEST_PARTIAL", "QUANT_BACKTEST_MIN_CONF"):
        monkeypatch.delenv(var, raising=False)
    # Fresh temp DB per test — no shared state possible.
    test_db = tmp_path_factory.mktemp("db") / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(test_db))
    # KEY (2026-04-16 evening): monkeypatch.setenv alone is NOT enough
    # because database.py opens a module-level _conn at import time.
    # _reinit_connection_for_test() closes the stale _conn and reopens
    # against the new env. Without this, tests that instantiate NewsDB()
    # would still write to data/sentinel.db (prod) — discovered via ghost
    # trades #152/#156/#157 appearing in prod during pytest runs.
    try:
        from src.core.database import _reinit_connection_for_test
        _reinit_connection_for_test()
    except ImportError:
        pass  # pre-2026-04-16 test runs or module not yet loaded — OK
    yield


@pytest.fixture
def db():
    """Database fixture"""
    from src.core.database import NewsDB
    return NewsDB()

@pytest.fixture
def config():
    """Config fixture"""
    from src.core import config
    return config

@pytest.fixture
def logger():
    """Logger fixture"""
    from src.core.logger import logger
    return logger

@pytest.fixture
def sample_analysis():
    """Sample SMC analysis data"""
    return {
        'price': 2545.50,
        'rsi': 45.0,
        'trend': 'bull',
        'fvg_type': 'bullish',
        'ob_price': 2540.00,
        'swing_high': 2550.00,
        'swing_low': 2530.00,
        'atr': 15.0,
        'macro_regime': 'zielony',
    }

