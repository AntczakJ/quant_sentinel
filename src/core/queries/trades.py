"""
src/core/queries/trades.py — domain-split trade queries.

Extracted from NewsDB god module 2026-05-04. Functions here use the
shared module-level connection from src.core.database, so they're
thread-safe under the same lock as NewsDB.

External callers can use:
    from src.core.queries.trades import recent_trades, win_rate
instead of going through NewsDB().*. Backwards-compat: NewsDB methods
remain (delegate to these for new behavior).
"""
from __future__ import annotations

from typing import Optional


def _get_db():
    """Lazy import to avoid circular deps."""
    from src.core.database import NewsDB
    return NewsDB()


def recent_trades(limit: int = 50,
                  status_filter: Optional[str] = None,
                  direction_filter: Optional[str] = None) -> list[dict]:
    """List recent closed/open trades with filters.

    Returns list of dicts (not tuples) — easier for new code.
    """
    db = _get_db()
    where_parts = []
    params: list = []
    if status_filter:
        where_parts.append("status = ?")
        params.append(status_filter)
    if direction_filter:
        where_parts.append("direction LIKE ?")
        params.append(f"%{direction_filter}%")
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    rows = db._query(
        f"""SELECT id, timestamp, direction, entry, sl, tp, status, profit,
                   pattern, setup_grade, setup_score, factors, session
            FROM trades {where}
            ORDER BY id DESC
            LIMIT ?""",
        tuple(params + [limit])
    )
    cols = ["id", "timestamp", "direction", "entry", "sl", "tp", "status",
            "profit", "pattern", "setup_grade", "setup_score", "factors",
            "session"]
    return [dict(zip(cols, r)) for r in (rows or [])]


def win_rate(window_n: Optional[int] = None,
             direction_filter: Optional[str] = None,
             status_in: tuple[str, ...] = ("WIN", "LOSS")) -> dict:
    """Compute WR over recent N trades or whole cohort.

    Returns: {n, wins, wr_pct, total_pl}
    """
    db = _get_db()
    placeholders = ",".join("?" * len(status_in))
    where = f"status IN ({placeholders})"
    params: list = list(status_in)
    if direction_filter:
        where += " AND direction LIKE ?"
        params.append(f"%{direction_filter}%")
    sql = f"""
        SELECT id, status, profit FROM trades
        WHERE {where}
        ORDER BY id DESC
    """
    if window_n is not None:
        sql += " LIMIT ?"
        params.append(window_n)
    rows = db._query(sql, tuple(params)) or []
    n = len(rows)
    if n == 0:
        return {"n": 0, "wins": 0, "wr_pct": 0.0, "total_pl": 0.0}
    wins = sum(1 for r in rows if r[1] == "WIN")
    pl = sum(float(r[2] or 0) for r in rows)
    return {
        "n": n,
        "wins": wins,
        "wr_pct": round(wins / n * 100, 2),
        "total_pl": round(pl, 2),
    }


def open_trades_count() -> int:
    """How many trades are currently OPEN. Useful for gate at restart time."""
    db = _get_db()
    row = db._query_one(
        "SELECT COUNT(*) FROM trades WHERE status='OPEN'"
    )
    return int(row[0]) if row else 0


def trades_in_range(start_ts: str, end_ts: str) -> list[dict]:
    """Trades within timestamp range. start_ts <= timestamp < end_ts.

    Used by walk-forward validator + per-week analytics.
    """
    db = _get_db()
    rows = db._query(
        """SELECT id, timestamp, direction, status, profit, pattern,
                  setup_grade, factors, session
           FROM trades
           WHERE timestamp >= ? AND timestamp < ?
             AND status IN ('WIN','LOSS','TIMEOUT','BREAKEVEN')
           ORDER BY timestamp""",
        (start_ts, end_ts)
    ) or []
    cols = ["id", "timestamp", "direction", "status", "profit", "pattern",
            "setup_grade", "factors", "session"]
    return [dict(zip(cols, r)) for r in rows]
