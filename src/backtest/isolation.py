"""
src/backtest/isolation.py — Production-safety rails for backtest mode.

ANY entry point that runs backtest logic MUST call `enforce_isolation()`
FIRST, before importing src.core.database, src.trading.scanner, etc.

Enforces:
  1. DATABASE_URL points to a backtest file (not sentinel.db)
  2. TURSO_URL is empty (no cloud write-through)
  3. A sentinel marker file is created so operators can see "backtest running"

Rationale: it is catastrophically bad if a backtest accidentally writes
simulated trades into the live trades table. These checks raise at
startup rather than silently corrupt production data.
"""
from __future__ import annotations

import os
from pathlib import Path

PROD_DB_FILENAMES = {"sentinel.db"}


class BacktestIsolationError(RuntimeError):
    """Raised when backtest process is not properly isolated from prod DB."""


def enforce_isolation(backtest_db_path: str = "data/backtest.db") -> None:
    """Verify + set env so we can't touch production DB.

    Call this at the TOP of every backtest entry script, BEFORE any
    imports of src.core.database or anything that imports it transitively.
    """
    # 1. Force backtest DB
    current = os.environ.get("DATABASE_URL", "")
    db_name = Path(current).name if current else ""
    if db_name in PROD_DB_FILENAMES:
        raise BacktestIsolationError(
            f"Refusing to start backtest: DATABASE_URL points to production ({current}). "
            f"Set DATABASE_URL={backtest_db_path} before running, or let this module set it."
        )
    # If not set to anything backtest-specific, override
    if not current or db_name in ("", "sentinel.db"):
        os.environ["DATABASE_URL"] = backtest_db_path

    # 2. Disable cloud sync
    if os.environ.get("TURSO_URL", ""):
        os.environ["TURSO_URL"] = ""
    os.environ["TURSO_TOKEN"] = ""

    # 3. Mark process as backtest-mode (for any code that may check)
    os.environ["QUANT_BACKTEST_MODE"] = "1"

    # 4. Ensure parent dir exists
    Path(backtest_db_path).parent.mkdir(parents=True, exist_ok=True)

    # 5. Defensive: sanity-check that running DB file isn't the prod one
    current_path = Path(os.environ["DATABASE_URL"]).resolve()
    for prod_name in PROD_DB_FILENAMES:
        prod_path = Path("data") / prod_name
        if prod_path.exists() and prod_path.resolve() == current_path:
            raise BacktestIsolationError(
                f"DATABASE_URL resolves to production file: {current_path}"
            )

    print(f"[backtest isolation] DATABASE_URL={os.environ['DATABASE_URL']}", flush=True)
    print(f"[backtest isolation] TURSO_URL=(disabled)", flush=True)
    print(f"[backtest isolation] QUANT_BACKTEST_MODE=1", flush=True)


def is_backtest_mode() -> bool:
    """True iff this process was started with enforce_isolation()."""
    return os.environ.get("QUANT_BACKTEST_MODE") == "1"


def assert_not_production_db() -> None:
    """Paranoid runtime guard — call before any write that could corrupt prod.

    Raises BacktestIsolationError if DATABASE_URL points at sentinel.db.
    """
    db_path = os.environ.get("DATABASE_URL", "")
    db_name = Path(db_path).name if db_path else ""
    if db_name in PROD_DB_FILENAMES:
        raise BacktestIsolationError(
            f"Production DB guard triggered: DATABASE_URL={db_path}. "
            f"This is a bug in the backtest runner — it should have called "
            f"enforce_isolation() first."
        )
