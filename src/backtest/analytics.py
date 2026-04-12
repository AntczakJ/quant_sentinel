"""
src/backtest/analytics.py — Advanced quant metrics for backtest analysis.

Operates on data/backtest.db after a run completes. All functions are
read-only on the DB (isolated from production via enforce_isolation).

Includes:
  - Sharpe, Sortino, Calmar ratios (risk-adjusted returns)
  - Expectancy (WR * avg_win - (1-WR) * avg_loss)
  - Trade duration stats
  - Rolling WR / PF over last N trades
  - Drawdown recovery time
  - Time-of-day + day-of-week P&L heatmap
  - P&L distribution (histogram, skewness, kurtosis)
"""
from __future__ import annotations

import math
import os
import sqlite3
import statistics
from typing import Dict, List, Optional, Tuple

from src.backtest.isolation import assert_not_production_db


def _connect() -> sqlite3.Connection:
    assert_not_production_db()
    return sqlite3.connect(os.environ["DATABASE_URL"])


def _fetch_closed_trades() -> List[Tuple]:
    """Return list of (id, timestamp, direction, profit, lot, status)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, direction, profit, lot, status "
            "FROM trades "
            "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') "
            "AND profit IS NOT NULL "
            "ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()
    return rows


# ── Risk-adjusted returns ──────────────────────────────────────────────

def compute_sharpe_sortino_calmar(initial_balance: float = 10_000.0,
                                   oz_per_lot: int = 100,
                                   periods_per_year: int = 252) -> Dict:
    """
    Sharpe:   (mean_return - rf) / stdev_return
    Sortino:  (mean_return - rf) / downside_stdev
    Calmar:   annualized_return / max_dd
    All annualized assuming periods_per_year trading days.
    Risk-free rate assumed 0 (for simplicity on short windows).
    """
    rows = _fetch_closed_trades()
    if len(rows) < 2:
        return {"note": "insufficient trades"}

    # Per-trade % return on rolling balance (compounding)
    balance = initial_balance
    pct_returns: List[float] = []
    equity_curve: List[float] = [initial_balance]
    for _id, _ts, _dir, profit, lot, _status in rows:
        lot_size = float(lot) if lot else 0.01
        dollar_pnl = float(profit) * oz_per_lot * lot_size
        ret = dollar_pnl / balance  # fractional return
        pct_returns.append(ret)
        balance += dollar_pnl
        equity_curve.append(balance)

    mean_r = statistics.mean(pct_returns)
    std_r = statistics.stdev(pct_returns) if len(pct_returns) > 1 else 0.0
    downside = [r for r in pct_returns if r < 0]
    down_std = statistics.stdev(downside) if len(downside) > 1 else 0.0

    # Annualize (assuming trades are roughly evenly spread; trades/year scaling)
    trades_per_year = periods_per_year
    ann_factor = math.sqrt(trades_per_year)
    sharpe = (mean_r / std_r * ann_factor) if std_r > 0 else 0.0
    sortino = (mean_r / down_std * ann_factor) if down_std > 0 else 0.0

    # Max DD for Calmar
    peak = initial_balance
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (eq - peak) / peak
        max_dd = min(max_dd, dd)

    total_return = (equity_curve[-1] / initial_balance - 1)
    calmar = (total_return / abs(max_dd)) if max_dd < 0 else float("inf") if total_return > 0 else 0.0

    return {
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3) if calmar != float("inf") else "inf",
        "mean_pct_return_per_trade": round(mean_r * 100, 4),
        "stdev_pct_return": round(std_r * 100, 4),
    }


# ── Expectancy ─────────────────────────────────────────────────────────

def compute_expectancy(oz_per_lot: int = 100) -> Dict:
    """
    E = WR × avg_win_$ + (1-WR) × avg_loss_$
    Positive E = positive expected value per trade (edge exists).
    """
    rows = _fetch_closed_trades()
    wins_usd, losses_usd = [], []
    for _id, _ts, _dir, profit, lot, _status in rows:
        lot_size = float(lot) if lot else 0.01
        dollar = float(profit) * oz_per_lot * lot_size
        if dollar > 0:
            wins_usd.append(dollar)
        elif dollar < 0:
            losses_usd.append(dollar)
    n_closed = len(wins_usd) + len(losses_usd)
    if n_closed == 0:
        return {"note": "no closed trades"}
    wr = len(wins_usd) / n_closed
    avg_win = statistics.mean(wins_usd) if wins_usd else 0.0
    avg_loss = statistics.mean(losses_usd) if losses_usd else 0.0
    expectancy_per_trade = wr * avg_win + (1 - wr) * avg_loss
    return {
        "n_closed": n_closed,
        "win_rate": round(wr, 3),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "expectancy_per_trade_usd": round(expectancy_per_trade, 2),
        "payoff_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss < 0 else None,
    }


# ── Trade duration ─────────────────────────────────────────────────────

def compute_trade_duration_stats() -> Dict:
    """
    Duration = hold time of each trade (now approximated since we don't
    have exit_time in schema; fallback: return None).
    TODO: add exit_time column to trades table for proper computation.
    """
    # Check if exit_time column exists
    conn = _connect()
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()]
    finally:
        conn.close()
    if "exit_time" not in cols:
        return {"note": "trades.exit_time not in schema — duration stats disabled"}
    # (implementation stub for future schema extension)
    return {"note": "TODO — schema extension needed"}


# ── Rolling WR / PF ────────────────────────────────────────────────────

def compute_rolling_metrics(window_n: int = 30) -> Dict:
    """Rolling win rate + profit factor over last N trades (sliding).

    Shows whether strategy edge is stable or degrading over time.
    """
    rows = _fetch_closed_trades()
    if len(rows) < window_n:
        return {"note": f"need >= {window_n} trades (have {len(rows)})"}
    windows = []
    for end_i in range(window_n, len(rows) + 1):
        window = rows[end_i - window_n:end_i]
        wins = sum(1 for r in window if r[5] in ("WIN", "PROFIT"))
        losses = sum(1 for r in window if r[5] in ("LOSS", "LOSE"))
        gross_win = sum(float(r[3]) for r in window if r[3] and float(r[3]) > 0)
        gross_loss = abs(sum(float(r[3]) for r in window if r[3] and float(r[3]) < 0))
        wr = wins / (wins + losses) if (wins + losses) > 0 else 0
        pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
        windows.append({"end_trade": end_i, "wr": round(wr, 3),
                        "pf": round(pf, 2) if pf != float("inf") else "inf"})
    wrs = [w["wr"] for w in windows]
    return {
        "window_size": window_n,
        "n_windows": len(windows),
        "wr_min": round(min(wrs), 3),
        "wr_max": round(max(wrs), 3),
        "wr_mean": round(statistics.mean(wrs), 3),
        "wr_stdev": round(statistics.stdev(wrs) if len(wrs) > 1 else 0, 3),
        "latest_window": windows[-1] if windows else None,
    }


# ── DD recovery time ───────────────────────────────────────────────────

def compute_drawdown_recovery(initial_balance: float = 10_000.0,
                              oz_per_lot: int = 100) -> Dict:
    """Time (in trades) from drawdown troughs to new equity peaks.

    Helps size max-DD risk: if DD typically recovers in 5 trades, that's
    tolerable; if avg recovery = 50 trades, position sizing was too big.
    """
    rows = _fetch_closed_trades()
    if not rows:
        return {"note": "no trades"}
    balance = initial_balance
    peak = initial_balance
    in_dd_since = None
    recoveries = []
    for i, r in enumerate(rows):
        profit = float(r[3])
        lot_size = float(r[4]) if r[4] else 0.01
        balance += profit * oz_per_lot * lot_size
        if balance > peak:
            peak = balance
            if in_dd_since is not None:
                recoveries.append(i - in_dd_since)
                in_dd_since = None
        elif in_dd_since is None:
            in_dd_since = i
    if not recoveries:
        return {"note": "no completed drawdown cycles (still in DD or all-time high)"}
    return {
        "n_recoveries": len(recoveries),
        "avg_recovery_trades": round(statistics.mean(recoveries), 1),
        "max_recovery_trades": max(recoveries),
        "min_recovery_trades": min(recoveries),
    }


# ── Time-of-day / day-of-week heatmap ──────────────────────────────────

def compute_temporal_heatmap(oz_per_lot: int = 100) -> Dict:
    """Aggregate P&L by hour-of-day and day-of-week.

    Reveals time-of-day biases (e.g. "most losses happen in Asian session").
    """
    rows = _fetch_closed_trades()
    if not rows:
        return {"note": "no trades"}
    import datetime as _dt
    by_hour: Dict[int, List[float]] = {}
    by_wday: Dict[int, List[float]] = {}
    for _id, ts_str, _dir, profit, lot, _status in rows:
        lot_size = float(lot) if lot else 0.01
        dollar = float(profit) * oz_per_lot * lot_size
        try:
            dt = _dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        by_hour.setdefault(dt.hour, []).append(dollar)
        by_wday.setdefault(dt.weekday(), []).append(dollar)

    def _summary(d):
        return {h: {"n": len(v), "sum": round(sum(v), 2),
                    "avg": round(statistics.mean(v), 2)}
                for h, v in sorted(d.items())}

    wday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "by_hour": _summary(by_hour),
        "by_day_of_week": {wday_names[k]: v for k, v in sorted(by_wday.items())
                           for _k2, v in [(k, {"n": len(by_wday[k]),
                                                "sum": round(sum(by_wday[k]), 2),
                                                "avg": round(statistics.mean(by_wday[k]), 2)})]},
    }


# ── P&L distribution stats ─────────────────────────────────────────────

def compute_pnl_distribution(oz_per_lot: int = 100) -> Dict:
    """Skewness + kurtosis of trade P&L distribution.

    Positive skew = occasional big wins, many small losses (good).
    Negative skew = many small wins, occasional big loss (bad).
    High kurtosis = fat tails (extreme outcomes more common).
    """
    rows = _fetch_closed_trades()
    if len(rows) < 4:
        return {"note": "need >= 4 trades"}
    pnls = []
    for _id, _ts, _dir, profit, lot, _status in rows:
        lot_size = float(lot) if lot else 0.01
        pnls.append(float(profit) * oz_per_lot * lot_size)
    n = len(pnls)
    mean = statistics.mean(pnls)
    std = statistics.stdev(pnls)
    if std == 0:
        return {"note": "zero variance"}
    m3 = sum((x - mean) ** 3 for x in pnls) / n
    m4 = sum((x - mean) ** 4 for x in pnls) / n
    skew = m3 / (std ** 3)
    kurt = m4 / (std ** 4) - 3  # excess kurtosis (0 for normal)
    return {
        "n": n,
        "mean_pnl_usd": round(mean, 2),
        "stdev_pnl_usd": round(std, 2),
        "min_pnl_usd": round(min(pnls), 2),
        "max_pnl_usd": round(max(pnls), 2),
        "skewness": round(skew, 3),
        "excess_kurtosis": round(kurt, 3),
        "skew_interpretation": ("positive (good — right tail)" if skew > 0.5 else
                                "negative (concerning — left tail)" if skew < -0.5 else
                                "near-symmetric"),
    }


# ── Full report ────────────────────────────────────────────────────────

def full_analytics_report() -> Dict:
    """Run all advanced analytics in one call."""
    return {
        "risk_adjusted": compute_sharpe_sortino_calmar(),
        "expectancy": compute_expectancy(),
        "duration": compute_trade_duration_stats(),
        "rolling_30": compute_rolling_metrics(30),
        "drawdown_recovery": compute_drawdown_recovery(),
        "temporal": compute_temporal_heatmap(),
        "pnl_distribution": compute_pnl_distribution(),
    }
