"""
api/routers/export.py — Data Export Endpoints

Provides CSV and JSON downloads for:
  - Trade history (with all fields)
  - Equity curve
  - Signal history
  - Model predictions log
"""

import sys
import os
import io
import csv
import json
from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.logger import logger

router = APIRouter()


def _make_csv_response(rows: list, headers: list, filename: str) -> StreamingResponse:
    """Create a CSV streaming response from rows and headers."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/trades", summary="Export trade history")
async def export_trades(
    format: str = Query("csv", description="Export format: csv or json"),
    status: str = Query("all", description="Filter: all, open, win, loss"),
    limit: int = Query(500, ge=1, le=5000, description="Max rows"),
):
    """
    Export complete trade history with all fields.
    Supports CSV download or JSON response.
    """
    from src.database import NewsDB
    db = NewsDB()

    where = ""
    if status == "open":
        where = "WHERE status = 'OPEN'"
    elif status == "win":
        where = "WHERE status = 'WIN'"
    elif status == "loss":
        where = "WHERE status = 'LOSS'"

    rows = db._query(f"""
        SELECT id, timestamp, direction, entry, sl, tp, rsi, trend, structure,
               status, pattern, lot, profit, session, setup_grade, setup_score,
               trailing_sl, failure_reason, vol_regime
        FROM trades {where}
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    headers = [
        "id", "timestamp", "direction", "entry", "sl", "tp", "rsi", "trend",
        "structure", "status", "pattern", "lot", "profit", "session",
        "setup_grade", "setup_score", "trailing_sl", "failure_reason", "vol_regime"
    ]

    if format == "json":
        return [dict(zip(headers, row)) for row in (rows or [])]

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return _make_csv_response(rows or [], headers, f"trades_{ts}.csv")


@router.get("/equity", summary="Export equity curve")
async def export_equity(
    format: str = Query("csv", description="Export format: csv or json"),
):
    """Export equity curve computed from trade history."""
    from src.database import NewsDB
    db = NewsDB()

    rows = db._query("""
        SELECT timestamp, profit, status, direction, entry, lot
        FROM trades
        WHERE status IN ('WIN', 'LOSS') AND profit IS NOT NULL
        ORDER BY timestamp ASC
    """)

    if not rows:
        return [] if format == "json" else _make_csv_response([], [], "equity_empty.csv")

    # Compute running equity
    try:
        balance_raw = db.get_param("portfolio_balance", 10000)
        initial = float(balance_raw) if balance_raw else 10000.0
    except (TypeError, ValueError):
        initial = 10000.0

    equity_data = []
    running = initial
    for ts, profit, status, direction, entry, lot in rows:
        pnl = float(profit) if profit else 0.0
        running += pnl
        equity_data.append((ts, round(running, 2), round(pnl, 2), status, direction))

    headers = ["timestamp", "equity", "pnl", "status", "direction"]

    if format == "json":
        return [dict(zip(headers, row)) for row in equity_data]

    ts_str = datetime.now().strftime("%Y%m%d_%H%M")
    return _make_csv_response(equity_data, headers, f"equity_{ts_str}.csv")


@router.get("/signals", summary="Export signal history")
async def export_signals(
    format: str = Query("csv", description="Export format: csv or json"),
    limit: int = Query(500, ge=1, le=5000, description="Max rows"),
):
    """Export scanner signal history."""
    from src.database import NewsDB
    db = NewsDB()

    rows = db._query("""
        SELECT id, timestamp, direction, entry_price, sl, tp, rsi, trend,
               structure, status
        FROM scanner_signals
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))

    headers = ["id", "timestamp", "direction", "entry_price", "sl", "tp",
               "rsi", "trend", "structure", "status"]

    if format == "json":
        return [dict(zip(headers, row)) for row in (rows or [])]

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return _make_csv_response(rows or [], headers, f"signals_{ts}.csv")


@router.get("/audit", summary="Export audit trail")
async def export_audit(
    trade_id: int = Query(0, description="Filter by trade ID (0 = all)"),
    format: str = Query("json", description="Export format: json or csv"),
):
    """Export tamper-proof audit trail with hash chain."""
    from src.database import NewsDB
    db = NewsDB()

    if trade_id > 0:
        rows = db._query(
            "SELECT id, trade_id, old_status, new_status, field_changed, "
            "old_value, new_value, reason, timestamp, prev_hash, entry_hash "
            "FROM trades_audit WHERE trade_id = ? ORDER BY id",
            (trade_id,)
        )
    else:
        rows = db._query(
            "SELECT id, trade_id, old_status, new_status, field_changed, "
            "old_value, new_value, reason, timestamp, prev_hash, entry_hash "
            "FROM trades_audit ORDER BY id DESC LIMIT 500"
        )

    headers = ["id", "trade_id", "old_status", "new_status", "field_changed",
               "old_value", "new_value", "reason", "timestamp", "prev_hash", "entry_hash"]

    if format == "json":
        return [dict(zip(headers, row)) for row in (rows or [])]

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return _make_csv_response(rows or [], headers, f"audit_{ts}.csv")


@router.get("/audit/verify", summary="Verify audit chain integrity")
async def verify_audit():
    """Verify tamper-proof hash chain. Returns True if no records were modified."""
    from src.compliance import verify_audit_chain
    return verify_audit_chain()


@router.get("/execution-quality", summary="Trade execution quality report")
async def execution_quality(days: int = Query(30, ge=1, le=365)):
    """Analyze fill rate, slippage, win rate by grade over last N days."""
    from src.compliance import get_execution_quality_report
    return get_execution_quality_report(days)


@router.get("/daily-report", summary="Get daily P&L report")
async def daily_report(date: str = Query(None, description="Date (YYYY-MM-DD), default=today")):
    """Retrieve or generate daily P&L report for a specific date."""
    from src.compliance import generate_daily_report, get_daily_report

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # Try to get cached report first
    existing = get_daily_report(date)
    if existing:
        return existing

    # Generate fresh
    return generate_daily_report(date)
