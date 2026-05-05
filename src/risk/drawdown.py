"""src/risk/drawdown.py — drawdown + risk-adjusted return metrics.

2026-05-05: shipped per comparative research (Grant *Trading Risk*,
Turtle rules) — replace count-based streak-pause with %-DD-based kill
switch. Industry standard:
  - DD > 6% from rolling-30d peak → soft pause
  - DD > 10% → halve risk (Turtle rule)
  - DD > 20% → hard halt (Turtle rule)

Also computes Calmar (CAGR/MaxDD) + Sortino (mean/downside-stdev)
on the 30-day cohort — exposed via Prometheus /metrics.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def _fetch_closed_pnls(db_path: str, days: int = 30) -> list[tuple[str, float]]:
    """Return list of (timestamp, profit) for closed trades within window."""
    conn = sqlite3.connect(db_path)
    cutoff = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT timestamp, profit FROM trades "
        "WHERE status IN ('WIN','LOSS','PROFIT') AND timestamp >= ? "
        "ORDER BY timestamp",
        (cutoff,),
    ).fetchall()
    conn.close()
    return [(r[0], float(r[1] or 0.0)) for r in rows]


def compute_drawdown_state(
    db_path: Optional[str] = None,
    starting_equity: float = 10000.0,
    days: int = 30,
) -> dict:
    """Compute current DD + risk-adjusted ratios from closed trades.

    Returns:
        dd_pct: positive % from rolling-{days} peak (0 means at peak)
        peak: rolling-{days} peak equity
        current_equity: current equity given starting_equity baseline
        calmar: annualized-return / max-DD ratio (None if insufficient)
        sortino: mean-return / downside-stdev ratio annualized (None if insufficient)
        max_dd_pct: worst DD in the window
        n_trades: closed trade count in window
    """
    db_path = db_path or str(ROOT / "data" / "sentinel.db")

    pnls = _fetch_closed_pnls(db_path, days=days)
    if not pnls:
        return {
            "dd_pct": 0.0, "peak": starting_equity, "current_equity": starting_equity,
            "calmar": None, "sortino": None, "max_dd_pct": 0.0, "n_trades": 0,
        }

    # Rolling equity curve from starting_equity
    equity = [starting_equity]
    for _, p in pnls:
        equity.append(equity[-1] + p)

    peak = max(equity)
    current = equity[-1]
    dd_pct = max(0.0, (peak - current) / peak * 100.0) if peak > 0 else 0.0

    # Max DD across the entire window
    running_peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > running_peak:
            running_peak = v
        dd = (running_peak - v) / running_peak * 100.0 if running_peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Calmar: annualized P&L return / max DD
    # P&L return per trade × trades_per_year_estimate
    trades_per_day = len(pnls) / max(days, 1)
    trades_per_year = trades_per_day * 365
    total_return_pct = (current - starting_equity) / starting_equity * 100.0
    annualized_return_pct = total_return_pct * (365.0 / max(days, 1))
    calmar = (annualized_return_pct / max_dd) if max_dd > 0.01 else None

    # Sortino: mean / downside_stdev (annualized assuming daily-equivalent samples)
    returns_pct = [p / starting_equity * 100.0 for _, p in pnls]
    if len(returns_pct) >= 5:
        mean_r = sum(returns_pct) / len(returns_pct)
        downside = [r for r in returns_pct if r < 0]
        if downside:
            ds_var = sum((r - 0.0) ** 2 for r in downside) / len(downside)
            ds_std = math.sqrt(ds_var)
            # annualize per trade-frequency
            annualization = math.sqrt(trades_per_year) if trades_per_year > 0 else 1.0
            sortino = (mean_r * annualization) / (ds_std * annualization) if ds_std > 0 else None
        else:
            sortino = None  # no losers — can't compute downside dev
    else:
        sortino = None

    return {
        "dd_pct": round(dd_pct, 2),
        "peak": round(peak, 2),
        "current_equity": round(current, 2),
        "calmar": round(calmar, 2) if calmar is not None else None,
        "sortino": round(sortino, 2) if sortino is not None else None,
        "max_dd_pct": round(max_dd, 2),
        "n_trades": len(pnls),
    }


# Soft / hard thresholds per Turtle rules + Grant Trading Risk
DD_SOFT_PAUSE_PCT = 6.0    # soft pause — wait for recovery
DD_HALVE_RISK_PCT = 10.0   # cut sizing in half (not yet implemented)
DD_HARD_HALT_PCT = 20.0    # hard halt (Turtle convention)


def dd_action(dd_pct: float) -> str:
    """Map current DD% to operational action label."""
    if dd_pct >= DD_HARD_HALT_PCT:
        return "halt"
    if dd_pct >= DD_HALVE_RISK_PCT:
        return "halve_risk"
    if dd_pct >= DD_SOFT_PAUSE_PCT:
        return "soft_pause"
    return "ok"


def cli_main():
    """Operator-friendly diagnostic. Prints current DD state."""
    import json
    state = compute_drawdown_state()
    print(json.dumps(state, indent=2))
    action = dd_action(state.get("dd_pct", 0.0))
    print(f"\nAction: {action}")
    return 0 if action == "ok" else 1


if __name__ == "__main__":
    import sys
    sys.exit(cli_main())
