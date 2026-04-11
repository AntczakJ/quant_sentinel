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
import calendar
from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse, Response

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.logger import logger

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
    from src.core.database import NewsDB
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
    from src.core.database import NewsDB
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
    from src.core.database import NewsDB
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
    from src.core.database import NewsDB
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
    from src.ops.compliance import verify_audit_chain
    return verify_audit_chain()


@router.get("/execution-quality", summary="Trade execution quality report")
async def execution_quality(days: int = Query(30, ge=1, le=365)):
    """Analyze fill rate, slippage, win rate by grade over last N days."""
    from src.ops.compliance import get_execution_quality_report
    return get_execution_quality_report(days)


@router.get("/monthly-report", summary="Download monthly PDF report")
async def monthly_report(
    month: str = Query(None, description="Month (YYYY-MM), default=current month"),
):
    """
    Generate a comprehensive monthly PDF report with trade summary,
    performance metrics, and full trade table.  Returns a downloadable PDF.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    from src.core.database import NewsDB

    # ---- resolve month ----
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    try:
        year, mon = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        return {"error": "Invalid month format. Use YYYY-MM."}

    month_name = f"{calendar.month_name[mon]} {year}"
    start = f"{year}-{mon:02d}-01"
    _, last_day = calendar.monthrange(year, mon)
    end = f"{year}-{mon:02d}-{last_day} 23:59:59"

    db = NewsDB()
    rows = db._query(
        """
        SELECT timestamp, direction, entry, sl, tp, status, profit
        FROM trades
        WHERE timestamp >= ? AND timestamp <= ?
              AND status IN ('WIN', 'LOSS')
        ORDER BY timestamp ASC
        """,
        (start, end),
    )

    # ---- compute stats ----
    trades = rows or []
    total = len(trades)
    wins = sum(1 for r in trades if r[5] == "WIN")
    losses = total - wins
    win_rate = (wins / total * 100) if total else 0.0
    pnls = [float(r[6]) if r[6] else 0.0 for r in trades]
    total_pnl = sum(pnls)
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss else float("inf") if gross_profit else 0.0
    expectancy = (total_pnl / total) if total else 0.0
    best_trade = max(pnls) if pnls else 0.0
    worst_trade = min(pnls) if pnls else 0.0

    # max drawdown from running equity
    peak = 0.0
    dd = 0.0
    running = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        cur_dd = peak - running
        if cur_dd > dd:
            dd = cur_dd
    max_drawdown = dd

    # ---- build PDF ----
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "QSTitle", parent=styles["Title"], fontSize=18, leading=22,
        alignment=TA_CENTER, textColor=colors.HexColor("#1a1a2e"),
    )
    subtitle_style = ParagraphStyle(
        "QSSub", parent=styles["Normal"], fontSize=11, leading=14,
        alignment=TA_CENTER, textColor=colors.HexColor("#555555"),
    )
    section_style = ParagraphStyle(
        "QSSection", parent=styles["Heading2"], fontSize=13, leading=16,
        textColor=colors.HexColor("#0f3460"), spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "QSBody", parent=styles["Normal"], fontSize=9, leading=12,
        alignment=TA_LEFT,
    )

    elements: list = []

    # -- header --
    elements.append(Paragraph("QUANT SENTINEL &mdash; Monthly Report", title_style))
    elements.append(Paragraph(month_name, subtitle_style))
    elements.append(Spacer(1, 10 * mm))

    # -- summary box --
    elements.append(Paragraph("Summary", section_style))
    summary_data = [
        ["Total Trades", str(total)],
        ["Wins", str(wins)],
        ["Losses", str(losses)],
        ["Win Rate", f"{win_rate:.1f}%"],
        ["Total P&L", f"${total_pnl:,.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[80 * mm, 60 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eaf6")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 6 * mm))

    # -- trade table --
    elements.append(Paragraph("Trade Log", section_style))
    table_header = ["Date", "Dir", "Entry", "SL", "TP", "Result", "P&L"]
    table_rows = [table_header]
    for ts, direction, entry, sl, tp, status, profit in trades:
        date_str = str(ts)[:16] if ts else ""
        pnl_val = float(profit) if profit else 0.0
        table_rows.append([
            date_str,
            str(direction or ""),
            f"{float(entry):.2f}" if entry else "",
            f"{float(sl):.2f}" if sl else "",
            f"{float(tp):.2f}" if tp else "",
            str(status or ""),
            f"${pnl_val:,.2f}",
        ])

    col_w = [32 * mm, 14 * mm, 22 * mm, 22 * mm, 22 * mm, 16 * mm, 22 * mm]
    trade_table = Table(table_rows, colWidths=col_w, repeatRows=1)
    trade_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3460")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(trade_table)
    elements.append(Spacer(1, 6 * mm))

    # -- performance metrics --
    elements.append(Paragraph("Performance Metrics", section_style))
    pf_display = f"{profit_factor:.2f}" if profit_factor != float("inf") else "N/A (no losses)"
    metrics_data = [
        ["Profit Factor", pf_display],
        ["Expectancy", f"${expectancy:,.2f}"],
        ["Max Drawdown", f"${max_drawdown:,.2f}"],
        ["Best Trade", f"${best_trade:,.2f}"],
        ["Worst Trade", f"${worst_trade:,.2f}"],
    ]
    metrics_table = Table(metrics_data, colWidths=[80 * mm, 60 * mm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8f5e9")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1a1a2e")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdbdbd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 8 * mm))

    # -- footer --
    generated_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(
        f"<i>Generated: {generated_ts} &mdash; Quant Sentinel Automated Report</i>",
        ParagraphStyle("QSFooter", parent=styles["Normal"], fontSize=8,
                       alignment=TA_CENTER, textColor=colors.HexColor("#999999")),
    ))

    doc.build(elements)
    buf.seek(0)
    filename = f"qs-monthly-report-{month}.pdf"

    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/daily-report", summary="Get daily P&L report")
async def daily_report(date: str = Query(None, description="Date (YYYY-MM-DD), default=today")):
    """Retrieve or generate daily P&L report for a specific date."""
    from src.ops.compliance import generate_daily_report, get_daily_report

    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    # Try to get cached report first
    existing = get_daily_report(date)
    if existing:
        return existing

    # Generate fresh
    return generate_daily_report(date)
