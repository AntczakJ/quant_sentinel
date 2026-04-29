"""
sim_time.py — single source of truth for "current UTC time" in scanner code paths.

Production: returns wall-clock UTC.
Backtest: when QUANT_BACKTEST_MODE=1 AND scanner._SIM_CURRENT_TS is bound to a
non-None cell (the harness in run_production_backtest.py installs this), returns
the simulated bar timestamp. Falls back to wall-clock if anything is unset.

Use this anywhere a scanner-side filter needs "what time is it?" — session
classification, ORB anchoring, killzone gating, etc. Routes that already
receive an explicit timestamp argument should keep using that — this helper
is for the default-argument path only.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return current UTC datetime — sim-time in backtest, wall-clock otherwise.

    Always returns a tz-aware datetime in UTC.
    """
    if os.environ.get("QUANT_BACKTEST_MODE") == "1":
        try:
            from src.trading import scanner as _scanner
            cell = getattr(_scanner, "_SIM_CURRENT_TS", None)
            if cell is not None and cell[0] is not None:
                ts = cell[0]
                if isinstance(ts, datetime):
                    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def in_backtest() -> bool:
    """True iff QUANT_BACKTEST_MODE=1 is set by enforce_isolation()."""
    return os.environ.get("QUANT_BACKTEST_MODE") == "1"
