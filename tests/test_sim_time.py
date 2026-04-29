"""Unit tests for src.trading.sim_time helper and the four sim-time leak fixes."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

# Reset env between tests
@pytest.fixture(autouse=True)
def _reset_sim_state():
    prev = os.environ.get("QUANT_BACKTEST_MODE")
    yield
    if prev is None:
        os.environ.pop("QUANT_BACKTEST_MODE", None)
    else:
        os.environ["QUANT_BACKTEST_MODE"] = prev
    try:
        from src.trading import scanner as _s
        _s._SIM_CURRENT_TS = None
    except Exception:
        pass


def test_now_utc_returns_wall_clock_when_not_in_backtest():
    os.environ.pop("QUANT_BACKTEST_MODE", None)
    from src.trading.sim_time import now_utc
    t = now_utc()
    assert t.tzinfo == timezone.utc
    # within 5s of system clock
    diff = abs((t - datetime.now(timezone.utc)).total_seconds())
    assert diff < 5.0


def test_now_utc_returns_sim_ts_when_in_backtest():
    os.environ["QUANT_BACKTEST_MODE"] = "1"
    from src.trading import scanner as _s
    fixed = datetime(2024, 8, 15, 14, 30, tzinfo=timezone.utc)
    _s._SIM_CURRENT_TS = [fixed]
    from src.trading.sim_time import now_utc
    assert now_utc() == fixed


def test_now_utc_falls_back_when_sim_cell_unset():
    """QUANT_BACKTEST_MODE=1 but cell None → wall clock fallback (no crash)."""
    os.environ["QUANT_BACKTEST_MODE"] = "1"
    from src.trading import scanner as _s
    _s._SIM_CURRENT_TS = None
    from src.trading.sim_time import now_utc
    t = now_utc()
    assert t.tzinfo == timezone.utc


def test_in_backtest_flag():
    os.environ["QUANT_BACKTEST_MODE"] = "1"
    from src.trading.sim_time import in_backtest
    assert in_backtest() is True
    os.environ.pop("QUANT_BACKTEST_MODE", None)
    assert in_backtest() is False


def test_smc_get_active_session_uses_sim_time_in_backtest():
    """The 2024-08 historical session classification should not depend on
    today's wall clock when QUANT_BACKTEST_MODE=1."""
    os.environ["QUANT_BACKTEST_MODE"] = "1"
    from src.trading import scanner as _s
    _s._SIM_CURRENT_TS = [datetime(2024, 8, 15, 14, 0, tzinfo=timezone.utc)]
    from src.trading.smc_engine import get_active_session
    info = get_active_session()
    assert info["utc_hour"] == 14
    # Aug 15 2024 14:00 UTC was a Thursday — market should be open
    assert info["market_open"] is True


def test_asia_orb_uses_sim_time_when_no_reference():
    """get_asia_range / detect_orb_signal should anchor on sim time."""
    import pandas as pd
    os.environ["QUANT_BACKTEST_MODE"] = "1"
    from src.trading import scanner as _s
    _s._SIM_CURRENT_TS = [datetime(2024, 8, 15, 8, 0, tzinfo=timezone.utc)]

    # Build dummy OHLC covering a 24h window prior to 2024-08-15 08:00
    idx = pd.date_range("2024-08-14T00:00", "2024-08-15T08:00", freq="5min", tz="UTC")
    n = len(idx)
    df = pd.DataFrame({
        "high": [2500.0 + i * 0.1 for i in range(n)],
        "low": [2495.0 + i * 0.1 for i in range(n)],
        "close": [2497.5 + i * 0.1 for i in range(n)],
    }, index=idx)
    df["datetime"] = idx

    from src.trading.asia_orb import get_asia_range
    rng = get_asia_range(df)
    # Function should not throw and should produce a result anchored on sim time
    assert rng is not None
    assert rng["bars"] > 0
    # Asia window for 2024-08-15 anchor should be on 2024-08-14 / 2024-08-15
    assert rng["start"].date().isoformat().startswith("2024-08-1")
