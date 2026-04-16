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
def _reset_backtest_env(monkeypatch):
    """Clear backtest-isolation env vars AND pin DATABASE_URL to test DB.

    Original purpose (2026-04-13): prevent enforce_isolation() state leaks
    between tests — env vars set by one test were polluting later tests
    that expected default behavior.

    Extended 2026-04-16: now ALSO pins DATABASE_URL to data/test_sentinel.db.
    Without this, tests that instantiate NewsDB() without going through
    enforce_isolation() were writing to data/sentinel.db (production).
    Symptom: 6 fake OPEN trades with entry=$2350 appeared in prod after
    a pytest run, plus #125/#126 got set to status=WIN profit=None by a
    test fixture. Prod DB is now defended at the conftest level.
    """
    for var in ("QUANT_BACKTEST_MODE", "QUANT_BACKTEST_RELAX",
                "QUANT_BACKTEST_PARTIAL", "QUANT_BACKTEST_MIN_CONF"):
        monkeypatch.delenv(var, raising=False)
    # Pin to test DB — tests that need a specific DB can override with
    # their own monkeypatch.setenv AFTER this fixture runs.
    monkeypatch.setenv("DATABASE_URL", "data/test_sentinel.db")
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

