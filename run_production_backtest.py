#!/usr/bin/env python3
"""
run_production_backtest.py — Walk-forward backtest of the REAL production
pipeline (scanner + SMC + ML ensemble + risk manager + calculate_position)
on historical data.

**CRITICAL**: this script writes simulated trades to `data/backtest.db`,
NEVER to `data/sentinel.db`. Enforced by src/backtest/isolation.py at
startup. Also disables Turso cloud sync.

Usage:
    python run_production_backtest.py                       # 30 days
    python run_production_backtest.py --days 60
    python run_production_backtest.py --symbol XAU/USD --yf GC=F
    python run_production_backtest.py --step-minutes 15     # scan every 15m
    python run_production_backtest.py --reset               # wipe backtest.db first

Output:
  - data/backtest.db (all sim trades, separate from prod)
  - stdout: per-day progress + final stats
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════
# STEP 1: ISOLATION — MUST run BEFORE any src.* imports
# ═══════════════════════════════════════════════════════════════════════
from src.backtest.isolation import enforce_isolation
enforce_isolation("data/backtest.db")

# Suppress TF noise
import os
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

# ═══════════════════════════════════════════════════════════════════════
# STEP 2: Now safe to import the rest
# ═══════════════════════════════════════════════════════════════════════
import argparse
import asyncio
import sqlite3
import time as _time
from pathlib import Path
from typing import Optional

import pandas as pd

from src.backtest.historical_provider import HistoricalProvider, install_historical_provider
from src.backtest.isolation import assert_not_production_db
from src.core.logger import logger


# ── Execution cost model ─────────────────────────────────────────────
# Realistic XAU/USD broker costs. Applied on entry + exit.
#   commission: typical ~$0.50-1.00 per 0.01 lot round-trip on gold CFDs.
#   slippage_base: flat component (market impact always present).
#   slippage_atr_coef: multiplier on ATR for volatility-scaled slippage.
#     High ATR (news events, thin liquidity) → worse fill quality.
#   swap_per_lot_day: overnight financing cost for holding positions
#     through 22:00-22:05 UTC (typical rollover window).
#   gap_slippage_factor: Sunday/news gap open fills at worst price.
COMMISSION_PER_LOT = 1.0         # USD round-trip per 0.01 lot
SLIPPAGE_EXIT_USD = 0.40         # base market impact on exit fill
SLIPPAGE_ATR_COEF = 0.03         # additional slip = ATR * coef
SWAP_PER_LOT_DAY = 0.50          # USD/day overnight on 1 lot (XAU CFD ~$0.50)
GAP_HIT_MULTIPLIER = 1.4         # multiply SL/TP miss by this when gap-filled


def _is_overnight_cross(entry_time, exit_time) -> int:
    """Count number of overnight rollovers (22:00 UTC crossings) between times.

    Each crossing = 1 day of swap cost. Held 2 nights = 2× swap.
    """
    if not entry_time or not exit_time:
        return 0
    import datetime as _dt
    import pandas as _pd
    try:
        e = _pd.to_datetime(entry_time, utc=True)
        x = _pd.to_datetime(exit_time, utc=True)
    except Exception:
        return 0
    # Count 22:00 UTC crossings between e and x
    count = 0
    cur = e.normalize() + _pd.Timedelta(hours=22)
    if cur < e:
        cur += _pd.Timedelta(days=1)
    while cur <= x:
        count += 1
        cur += _pd.Timedelta(days=1)
    return count


def _detect_gap(prev_close: float, curr_open: float, threshold_pct: float = 0.3) -> bool:
    """True if the current bar opens with > threshold_pct gap from prev close.
    Common on Sunday open XAU/USD (Fri close → Sun open).
    """
    if prev_close <= 0:
        return False
    gap_pct = abs(curr_open - prev_close) / prev_close * 100
    return gap_pct > threshold_pct


class _UnlimitedRateLimiter:
    """Stub for backtest — no real rate limits on local data."""
    def can_use_credits(self, n):
        return True, 0
    def use_credits(self, n, endpoint="", symbol=""):
        return True
    def wait_for_credits(self, n, max_wait_seconds=10):
        return True
    def validate_endpoint_cost(self, endpoint, num_symbols=1):
        return True, 1, None
    def get_stats(self):
        return {"available": 999999, "total": 999999, "used_pct": 0}


def _reset_backtest_db() -> None:
    """Wipe data/backtest.db for a clean run."""
    assert_not_production_db()
    path = Path(os.environ["DATABASE_URL"])
    if path.exists():
        path.unlink()
        print(f"[backtest] Reset: removed {path}")


def _summarize_trades() -> dict:
    """Query backtest.db trades table for final stats + quant metrics."""
    assert_not_production_db()
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        row = cur.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status IN ('WIN','PROFIT') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status IN ('LOSS','LOSE') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END), "
            "AVG(profit), "
            "SUM(CASE WHEN status = 'BREAKEVEN' THEN 1 ELSE 0 END) "
            "FROM trades"
        ).fetchone()
        total, wins, losses, still_open, avg_profit, breakevens = row
        breakevens = breakevens or 0
        total = total or 0
        wins = wins or 0
        losses = losses or 0
        still_open = still_open or 0
        closed = (wins + losses)
        wr = (wins / closed * 100) if closed else 0.0

        # Cumulative profit (any closed trade, including breakeven + trailed)
        cum_row = cur.execute(
            "SELECT SUM(profit) FROM trades "
            "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') AND profit IS NOT NULL"
        ).fetchone()
        cum_profit = cum_row[0] or 0.0

        # ── Quant metrics: profit factor, max consecutive losses, max DD ──
        closed_rows = cur.execute(
            "SELECT status, profit FROM trades "
            "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') AND profit IS NOT NULL "
            "ORDER BY id ASC"
        ).fetchall()
        gross_win = sum(float(p) for s, p in closed_rows if p and float(p) > 0)
        gross_loss = abs(sum(float(p) for s, p in closed_rows if p and float(p) < 0))
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

        # Consecutive loss streak (longest)
        max_streak = cur_streak = 0
        for s, p in closed_rows:
            if s in ("LOSS", "LOSE"):
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = 0

        # Equity curve from compounding (lot-aware) profits.
        # profit column is in price units per 1 lot; actual $ = profit * lot_size * 100
        # (1 standard gold lot = 100 oz, so $1 price move × 100 oz × lot = $1 * 100 * lot)
        # For XTB micro: 1 lot = 10 oz, so multiplier = 10.
        lot_rows = cur.execute(
            "SELECT status, profit, lot FROM trades "
            "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') AND profit IS NOT NULL "
            "ORDER BY id ASC"
        ).fetchall()
        OZ_PER_LOT = 100  # standard gold spec
        equity = [10_000.0]
        peak = 10_000.0
        max_dd = 0.0
        for _status, p, lot in lot_rows:
            if p is None:
                continue
            lot_size = float(lot) if lot else 0.01
            dollar_pnl = float(p) * OZ_PER_LOT * lot_size
            equity.append(equity[-1] + dollar_pnl)
            peak = max(peak, equity[-1])
            dd = (equity[-1] - peak) / peak * 100
            max_dd = min(max_dd, dd)

        return {
            "total_trades": total,
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "breakevens": breakevens,
            "still_open": still_open,
            "win_rate_pct": round(wr, 1),
            "avg_profit": round(avg_profit, 2) if avg_profit is not None else 0.0,
            "cumulative_profit": round(cum_profit, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "max_consec_losses": max_streak,
            "max_drawdown_pct": round(max_dd, 2),
            "final_equity": round(equity[-1], 2),
            "return_pct": round((equity[-1] / 10_000.0 - 1) * 100, 2),
        }
    finally:
        conn.close()


def _buy_and_hold_benchmark(provider) -> dict:
    """Compare strategy return to simple buy-and-hold of the underlying.

    If strategy returns +3% but buy-and-hold returns +8%, strategy has
    negative alpha (i.e. you'd be better off just holding). If strategy
    = +5% in a -10% down market, strategy genuinely added value.
    """
    cache = provider._cache.get("1h") or provider._cache.get("15m")
    if cache is None or cache.empty:
        return {}
    first_price = float(cache["close"].iloc[0])
    last_price = float(cache["close"].iloc[-1])
    bh_return_pct = (last_price / first_price - 1) * 100
    return {
        "bh_first_price": round(first_price, 2),
        "bh_last_price": round(last_price, 2),
        "bh_return_pct": round(bh_return_pct, 2),
    }


def _monte_carlo_analysis(n_simulations: int = 1000) -> dict:
    """Shuffle trade order N times — show distribution of outcomes.

    If strategy has real edge, outcomes should be consistently positive
    regardless of order. High variance across shuffles = order-dependent
    = probably lucky on the real-order realization.

    Returns percentiles of final return + max drawdown.
    """
    assert_not_production_db()
    import random
    import statistics as stats_mod

    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    rows = conn.execute(
        "SELECT profit FROM trades "
        "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') AND profit IS NOT NULL"
    ).fetchall()
    conn.close()
    profits = [float(p) for (p,) in rows]
    if len(profits) < 5:
        return {"n_trades": len(profits), "note": "too few trades for MC"}

    # Bootstrap with replacement: each simulation draws N trades from the
    # observed distribution. This varies FINAL return too (vs plain shuffle
    # which preserves sum). If p5 of final return is still positive, edge
    # is robust to bad-luck sequences. If p5 is deeply negative, the real
    # outcome was probably a lucky draw.
    returns = []
    max_dds = []
    n_trades = len(profits)
    for _ in range(n_simulations):
        sampled = [random.choice(profits) for _ in range(n_trades)]
        equity = [10_000.0]
        peak = 10_000.0
        dd = 0.0
        for p in sampled:
            equity.append(equity[-1] + p)
            peak = max(peak, equity[-1])
            dd = min(dd, (equity[-1] - peak) / peak * 100)
        returns.append((equity[-1] / 10_000.0 - 1) * 100)
        max_dds.append(dd)

    def _pctl(vs, q):
        s = sorted(vs)
        return s[max(0, min(len(s) - 1, int(len(s) * q / 100)))]

    return {
        "n_simulations": n_simulations,
        "n_trades": len(profits),
        "return_p5": round(_pctl(returns, 5), 2),
        "return_p50": round(_pctl(returns, 50), 2),
        "return_p95": round(_pctl(returns, 95), 2),
        "return_mean": round(stats_mod.mean(returns), 2),
        "return_stdev": round(stats_mod.stdev(returns) if len(returns) > 1 else 0, 2),
        "max_dd_p5": round(_pctl(max_dds, 5), 2),   # worst 5% case
        "max_dd_p50": round(_pctl(max_dds, 50), 2), # median
        "prob_profitable": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
    }


def _export_equity_curve(path: str) -> int:
    """Save equity curve PNG (or HTML fallback) for visual analysis."""
    assert_not_production_db()
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    rows = conn.execute(
        "SELECT timestamp, status, profit FROM trades "
        "WHERE status IN ('WIN','PROFIT','LOSS','LOSE','BREAKEVEN') AND profit IS NOT NULL "
        "ORDER BY id ASC"
    ).fetchall()
    conn.close()
    if not rows:
        return 0

    # Build equity curve
    equity = [10_000.0]
    times = [None]
    for ts, _status, p in rows:
        equity.append(equity[-1] + float(p))
        times.append(ts)
    peak = pd.Series(equity).cummax()
    dd = (pd.Series(equity) - peak) / peak * 100

    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    # Try matplotlib for PNG, fallback to HTML if unavailable
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                        gridspec_kw={"height_ratios": [3, 1]})
        x = list(range(len(equity)))
        ax1.plot(x, equity, linewidth=1.5, color="#2e7d32")
        ax1.fill_between(x, equity, 10_000, where=[e >= 10_000 for e in equity],
                         alpha=0.15, color="#2e7d32")
        ax1.fill_between(x, equity, 10_000, where=[e < 10_000 for e in equity],
                         alpha=0.15, color="#c62828")
        ax1.axhline(y=10_000, color="gray", linestyle="--", linewidth=0.8)
        ax1.set_title(f"Equity Curve — {len(rows)} trades")
        ax1.set_ylabel("Balance ($)")
        ax1.grid(alpha=0.3)

        ax2.fill_between(x, dd, 0, color="#c62828", alpha=0.4)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Trade #")
        ax2.grid(alpha=0.3)

        plt.tight_layout()
        plt.savefig(path, dpi=110, bbox_inches="tight")
        plt.close()
        return len(rows)
    except ImportError:
        # HTML fallback — simple SVG line chart
        svg_points = " ".join(f"{i*5},{200 - (e - 10000)*0.1}" for i, e in enumerate(equity))
        html = f"""<!DOCTYPE html><html><head><title>Equity Curve</title></head>
<body><h2>Equity Curve ({len(rows)} trades)</h2>
<svg width="{len(equity)*5+40}" height="220" style="background:#f5f5f5">
<polyline fill="none" stroke="#2e7d32" stroke-width="2" points="{svg_points}"/>
</svg></body></html>"""
        Path(path).write_text(html, encoding="utf-8")
        return len(rows)


def _export_trades_csv(path: str) -> int:
    """Dump all backtest trades to CSV for external analysis. Returns row count."""
    assert_not_production_db()
    import csv
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    try:
        rows = conn.execute(
            "SELECT id, timestamp, direction, entry, sl, tp, status, profit, "
            "lot, rsi, trend, structure, pattern, session "
            "FROM trades ORDER BY id ASC"
        ).fetchall()
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "timestamp", "direction", "entry", "sl", "tp", "status",
                        "profit", "lot", "rsi", "trend", "structure", "pattern", "session"])
            w.writerows(rows)
        return len(rows)
    finally:
        conn.close()


async def _resolve_open_trades(db, provider: HistoricalProvider) -> None:
    """Bar-by-bar SL/TP check for any OPEN trades.

    Walks forward from each trade's entry bar to simulated_now, marks WIN
    if TP hit, LOSS if SL hit. Writes profit in absolute-price terms to
    match the production resolver output format.
    """
    assert_not_production_db()

    # Fast path: no open trades = nothing to resolve (saves DB hit on every cycle)
    open_rows = db._query(
        "SELECT id, direction, entry, sl, tp, timestamp FROM trades WHERE status='OPEN'"
    )
    if not open_rows:
        return

    # Use the 5m cache for highest-resolution SL/TP detection
    tf_cache = provider._cache.get("5m")
    if tf_cache is None or tf_cache.empty:
        tf_cache = provider._cache.get("15m")
    if tf_cache is None or tf_cache.empty:
        return
    now_ts = provider.simulated_now
    if now_ts is None:
        return
    for row in open_rows:
        t_id, direction, entry, sl, tp, ts_str = row
        try:
            entry_time = pd.to_datetime(ts_str, utc=True)
        except (ValueError, TypeError):
            continue
        # Bars strictly after entry up to now
        mask = (tf_cache["timestamp"] > entry_time) & (tf_cache["timestamp"] <= now_ts)
        window = tf_cache.loc[mask]
        if window.empty:
            continue

        is_long = "LONG" in (direction or "").upper()
        hit_status: Optional[str] = None
        hit_price: Optional[float] = None

        # Trailing stop state — matches production resolve_trades_task logic:
        #   r_mult >= 1.0  → SL to breakeven (entry)
        #   r_mult >= 1.5  → SL to entry + 1R (lock profit)
        #   r_mult >= 2.0  → SL trails at +1.5R (walk-up)
        if is_long:
            r_dist = entry - sl  # positive risk distance
        else:
            r_dist = sl - entry  # positive risk distance
        active_sl = sl  # starts at original SL, may be raised

        # P8.21 PARTIAL CLOSE: optional — close half position at 1R, run rest.
        # Enable via QUANT_BACKTEST_PARTIAL=1. Reduces win size but drastically
        # reduces loss rate on pullbacks → typically improves expectancy on
        # trending strategies. Tracked as separate 'partial_profit' field
        # credited when price crosses 1R.
        use_partial = os.environ.get("QUANT_BACKTEST_PARTIAL") == "1"
        partial_taken = False
        partial_profit = 0.0

        for _, bar in window.iterrows():
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])

            # 1. Update trailing SL based on excursion
            if r_dist > 0:
                if is_long:
                    excursion_r = (bar_high - entry) / r_dist
                    # Partial close at 1R (half position, locked profit)
                    if use_partial and not partial_taken and excursion_r >= 1.0:
                        partial_profit = 0.5 * r_dist  # half position × 1R profit
                        partial_taken = True
                    if excursion_r >= 2.0:
                        new_sl = entry + 1.5 * r_dist
                        active_sl = max(active_sl, new_sl)
                    elif excursion_r >= 1.5:
                        new_sl = entry + 1.0 * r_dist
                        active_sl = max(active_sl, new_sl)
                    elif excursion_r >= 1.0:
                        active_sl = max(active_sl, entry)  # breakeven
                else:  # SHORT
                    excursion_r = (entry - bar_low) / r_dist
                    if use_partial and not partial_taken and excursion_r >= 1.0:
                        partial_profit = 0.5 * r_dist
                        partial_taken = True
                    if excursion_r >= 2.0:
                        new_sl = entry - 1.5 * r_dist
                        active_sl = min(active_sl, new_sl)
                    elif excursion_r >= 1.5:
                        new_sl = entry - 1.0 * r_dist
                        active_sl = min(active_sl, new_sl)
                    elif excursion_r >= 1.0:
                        active_sl = min(active_sl, entry)

            # 2. Check TP/SL (using trailing SL)
            if is_long:
                if bar_high >= tp:
                    hit_status, hit_price = "WIN", tp
                    break
                if bar_low <= active_sl:
                    # Determine status: SL at or above entry = trail exit (WIN-ish)
                    if active_sl > entry:
                        hit_status, hit_price = "WIN", active_sl  # trailed profit
                    elif active_sl == entry:
                        hit_status, hit_price = "BREAKEVEN", active_sl
                    else:
                        hit_status, hit_price = "LOSS", active_sl
                    break
            else:  # SHORT
                if bar_low <= tp:
                    hit_status, hit_price = "WIN", tp
                    break
                if bar_high >= active_sl:
                    if active_sl < entry:
                        hit_status, hit_price = "WIN", active_sl  # trailed profit
                    elif active_sl == entry:
                        hit_status, hit_price = "BREAKEVEN", active_sl
                    else:
                        hit_status, hit_price = "LOSS", active_sl
                    break
        if hit_status and hit_price is not None:
            # Compute gross P&L in price units
            if is_long:
                gross = hit_price - entry
            else:
                gross = entry - hit_price

            # ── P6 Execution costs ──
            # 1. Exit slippage (flat + ATR-scaled): SL/TP rarely fills exactly.
            #    High vol = worse fill.
            exit_bar_atr = 0.0
            try:
                exit_bar_atr = float(bar["high"]) - float(bar["low"])
            except Exception:
                pass
            exit_slip = SLIPPAGE_EXIT_USD + exit_bar_atr * SLIPPAGE_ATR_COEF

            # 2. Gap detection on exit bar — if high - low ratio is unusual vs
            #    open, likely a gap fill (worse than expected).
            try:
                bar_range = float(bar["high"]) - float(bar["low"])
                bar_open = float(bar["open"])
                # If bar opened far from prev close, apply gap penalty
                # (approximation; proper check needs prior bar)
                if bar_range > 0 and abs(bar_open - hit_price) / max(bar_range, 0.01) > 0.7:
                    exit_slip *= GAP_HIT_MULTIPLIER
            except Exception:
                pass

            # 3. Commission: fixed per round-trip
            commission = COMMISSION_PER_LOT

            # 4. Swap (overnight financing): count 22:00 UTC crossings
            entry_time = pd.to_datetime(ts_str, utc=True)
            try:
                exit_time = pd.to_datetime(bar["timestamp"], utc=True)
            except Exception:
                exit_time = now_ts
            nights = _is_overnight_cross(entry_time, exit_time)
            swap_cost = SWAP_PER_LOT_DAY * nights  # in $USD terms per lot

            # If partial close taken at 1R, credit it and halve remainder P&L
            if use_partial and partial_taken:
                # Half position earned +1R locked, remainder earns gross/2
                net = partial_profit + (gross / 2) - exit_slip - commission - swap_cost
            else:
                net = gross - exit_slip - commission - swap_cost
            profit = round(net, 2)
            db._execute("UPDATE trades SET status=?, profit=? WHERE id=?",
                        (hit_status, profit, t_id))
            logger.debug(f"[backtest] Trade #{t_id} resolved {hit_status} "
                         f"gross={gross:+.2f} net={profit:+.2f} "
                         f"(slip={exit_slip:.2f} + comm={commission} + "
                         f"swap={swap_cost:.2f} [{nights}n])")


async def _run_backtest(args) -> dict:
    # ── 1. Load historical data ───────────────────────────────────────
    print(f"[backtest] Loading {args.yf} ({args.days} days of 5m/15m/1h/4h)...", flush=True)
    period_for_fetch = f"{max(args.days, 60)}d"  # yfinance 5m max 60d anyway
    provider = HistoricalProvider.from_yfinance(
        symbol=args.symbol, yf_symbol=args.yf, period=period_for_fetch,
        intervals=("5m", "15m", "1h", "4h"),
        use_cache=not getattr(args, "no_cache", False),
    )
    install_historical_provider(provider)

    # ── 2. Import scanner AFTER provider is installed ─────────────────
    from src.trading import scanner as scanner_mod
    from src.trading import smc_engine
    from src.core.database import NewsDB

    # Override is_market_open to always return True in backtest.
    # Original signature: is_market_open(dt_cet=None) — accept optional arg.
    smc_engine.is_market_open = lambda dt_cet=None: True  # type: ignore[assignment]
    # Skip cooldown in backtest (we simulate time, not wall-clock)
    scanner_mod._check_trade_cooldown = lambda db, min_hours=None: True  # type: ignore[assignment]
    # Unlimited API credits in backtest — data is local, no external rate limit
    try:
        from src import api_optimizer
        api_optimizer.get_rate_limiter = lambda: _UnlimitedRateLimiter()  # type: ignore[assignment]
    except ImportError:
        pass

    db = NewsDB()

    # ── 3. Build timestamp grid ───────────────────────────────────────
    grid_cache = provider._cache.get("15m")
    if grid_cache is None:
        raise RuntimeError("15m cache required for simulation grid")
    data_start = grid_cache["timestamp"].iloc[0]
    data_end = grid_cache["timestamp"].iloc[-1]

    # Prefer --start/--end over --days when given
    if getattr(args, "start", None):
        start_ts = pd.Timestamp(args.start, tz="UTC")
    else:
        start_ts = data_end - pd.Timedelta(days=args.days)
    if getattr(args, "end", None):
        end_ts = pd.Timestamp(args.end, tz="UTC")
    else:
        end_ts = data_end

    # Clamp to data range
    start_ts = max(start_ts, data_start)
    end_ts = min(end_ts, data_end)
    if start_ts >= end_ts:
        raise ValueError(f"Empty time range: start={start_ts} >= end={end_ts}")

    step = pd.Timedelta(minutes=args.step_minutes)
    timestamps = pd.date_range(start_ts, end_ts, freq=step, tz="UTC")
    # Require at least 50 prior bars for warmup — drop earliest if not enough
    min_start = data_start + pd.Timedelta(hours=50)
    timestamps = timestamps[timestamps >= min_start]
    if len(timestamps) == 0:
        raise ValueError(f"No timestamps after warmup filter. Data starts {data_start}, "
                         f"earliest usable {min_start}, requested end {end_ts}")

    # Resume: skip timestamps up to last checkpoint if --resume given
    if getattr(args, "resume", False):
        try:
            last_ts_row = db._query_one("SELECT param_value FROM dynamic_params "
                                         "WHERE param_name='backtest_last_checkpoint_ts'")
            if last_ts_row and last_ts_row[0]:
                resume_ts = pd.Timestamp(last_ts_row[0], tz="UTC")
                before = len(timestamps)
                timestamps = timestamps[timestamps > resume_ts]
                print(f"[backtest] Resuming from {resume_ts} "
                      f"({before - len(timestamps)} cycles skipped)", flush=True)
        except Exception as e:
            logger.debug(f"Resume check failed: {e}")

    print(f"[backtest] Simulating {len(timestamps)} scan cycles from "
          f"{timestamps[0] if len(timestamps) else 'nothing'} to "
          f"{timestamps[-1] if len(timestamps) else 'nothing'} "
          f"(step {args.step_minutes}m)", flush=True)

    # ── 4. Walk forward ───────────────────────────────────────────────
    t0 = _time.time()
    last_day_logged = None
    last_trade_count = 0
    skipped_weekend = 0
    skipped_no_setup = 0
    for i, ts in enumerate(timestamps):
        provider.set_simulated_now(ts)

        # Weekend skip — gold market closed Fri 22:00 UTC -> Sun 23:00 UTC.
        # Matches production is_market_open() which we bypassed globally.
        wd = ts.weekday()  # Mon=0 .. Sun=6
        hh = ts.hour
        is_weekend = (wd == 5) or (wd == 6 and hh < 23) or (wd == 4 and hh >= 22)
        if is_weekend:
            skipped_weekend += 1
            continue

        # Run one scan cycle (production path)
        try:
            trade = scanner_mod.cascade_mtf_scan(db, balance=10_000.0, currency="USD")
        except Exception as e:
            logger.debug(f"[backtest] scan at {ts} failed: {e}")
            trade = None
        if trade is None:
            skipped_no_setup += 1

        # Persist trade (same path as production log_trade)
        if trade:
            # Avoid look-ahead bias: scanner returns entry = current bar's close,
            # but realistically you can only execute on the NEXT bar's open.
            # Shift entry to next bar's open on the decision TF; keep SL/TP
            # distances from original entry so R:R stays the same.
            tf_for_entry = trade.get("tf", "15m")
            tf_bars = provider._cache.get(tf_for_entry)
            original_entry = trade["entry"]
            actual_entry = original_entry
            if tf_bars is not None and not tf_bars.empty:
                future_bars = tf_bars[tf_bars["timestamp"] > ts]
                if not future_bars.empty:
                    actual_entry = float(future_bars.iloc[0]["open"])
                    # Preserve SL/TP $ distance from the decision price
                    gap = actual_entry - original_entry
                    trade["entry"] = actual_entry
                    trade["sl"] = trade["sl"] + gap
                    trade["tp"] = trade["tp"] + gap
            try:
                db.log_trade(
                    direction=trade["direction"],
                    price=trade["entry"],
                    sl=trade["sl"],
                    tp=trade["tp"],
                    rsi=trade.get("rsi", 0),
                    trend=trade.get("trend", ""),
                    structure=f"[backtest] {trade.get('tf_label', trade.get('tf',''))}",
                    pattern=trade.get("pattern", "backtest"),
                    lot=trade.get("lot", 0.01),
                    factors={},
                    profit=None,
                )
                # CRITICAL: db.log_trade uses datetime.now() for timestamp.
                # In backtest that's wall-clock (today), but we need SIMULATED
                # time so _resolve_open_trades can walk bars from entry to now.
                # Patch the just-inserted row to use simulated_now.
                sim_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
                db._execute(
                    "UPDATE trades SET timestamp=? WHERE id=(SELECT MAX(id) FROM trades)",
                    (sim_ts,)
                )
            except Exception as e:
                logger.debug(f"[backtest] log_trade failed: {e}")

        # Resolve any OPEN trades against bars since entry
        await _resolve_open_trades(db, provider)

        # Checkpoint: save last-processed timestamp every N cycles so
        # --resume can pick up from here if process crashes.
        ckpt_interval = getattr(args, "checkpoint_every", 100)
        if (i + 1) % ckpt_interval == 0:
            try:
                db.set_param("backtest_last_checkpoint_ts",
                             ts.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass

        # Progress every 50 cycles (flushes immediately for tail -f)
        if (i + 1) % 50 == 0 or i == len(timestamps) - 1:
            stats = _summarize_trades()
            elapsed = _time.time() - t0
            pct = (i + 1) / len(timestamps) * 100
            eta = (elapsed / (i + 1)) * (len(timestamps) - i - 1)
            print(f"[backtest] {ts.date()} | cycle {i+1}/{len(timestamps)} "
                  f"({pct:.0f}%) | trades={stats['total_trades']} "
                  f"WR={stats['win_rate_pct']:.1f}% | "
                  f"weekend_skip={skipped_weekend} | no_setup={skipped_no_setup} | "
                  f"elapsed {elapsed:.0f}s ETA {eta:.0f}s", flush=True)

        # Daily marker (for day-change announcement, lightweight)
        day = ts.date()
        if day != last_day_logged:
            last_day_logged = day
            last_trade_count = _summarize_trades()["total_trades"]

    # ── 5. Final forced resolution (close any still-open on last bar) ──
    # Leave still_open as-is; stats show them separately.

    # ── 6. Diagnostic: grab ensemble + rejection stats for post-run analysis ──
    stats = _summarize_trades()
    stats["cycles_total"] = len(timestamps)
    stats["weekend_skipped"] = skipped_weekend
    stats["no_setup"] = skipped_no_setup

    # Ensemble confidence distribution (populated via scanner instrumentation)
    try:
        from src.ops.metrics import get_all_metrics
        m = get_all_metrics()
        stats["ensemble_confidence_avg"] = m.get("ensemble", {}).get("confidence_avg", 0)
        stats["ensemble_sample_count"] = m.get("ensemble", {}).get("sample_count", 0)
        stats["ensemble_signals_long"] = m.get("ensemble", {}).get("signals_long", 0)
        stats["ensemble_signals_short"] = m.get("ensemble", {}).get("signals_short", 0)
        stats["ensemble_signals_wait"] = m.get("ensemble", {}).get("signals_wait", 0)
    except Exception:
        pass

    # Top rejection reasons (diagnostic only)
    try:
        conn = sqlite3.connect(os.environ["DATABASE_URL"])
        rows = conn.execute(
            "SELECT filter_name, rejection_reason, COUNT(*) "
            "FROM rejected_setups GROUP BY filter_name, rejection_reason "
            "ORDER BY COUNT(*) DESC LIMIT 5"
        ).fetchall()
        stats["top_rejections"] = [(r[0], r[1], r[2]) for r in rows]
        conn.close()
    except Exception:
        pass

    # Buy-and-hold benchmark for context (did strategy beat passive?)
    try:
        bh = _buy_and_hold_benchmark(provider)
        stats.update(bh)
        stats["alpha_vs_bh_pct"] = round(
            stats.get("return_pct", 0) - bh.get("bh_return_pct", 0), 2
        )
    except Exception:
        pass

    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAU/USD", help="display symbol")
    ap.add_argument("--yf", default="GC=F", help="yfinance ticker to fetch")
    ap.add_argument("--days", type=int, default=30, help="simulation window in days (from end of data)")
    ap.add_argument("--start", default=None, help="start date ISO (overrides --days), e.g. 2026-03-15")
    ap.add_argument("--end", default=None, help="end date ISO (overrides --days)")
    ap.add_argument("--step-minutes", type=int, default=15,
                    help="scan cadence in minutes (production: 15)")
    ap.add_argument("--reset", action="store_true",
                    help="wipe data/backtest.db before running")
    ap.add_argument("--no-cache", action="store_true",
                    help="bypass yfinance disk cache")
    ap.add_argument("--output", default=None,
                    help="save final stats JSON to this path")
    ap.add_argument("--export-csv", default=None,
                    help="dump all trades to CSV for Excel/pandas analysis")
    ap.add_argument("--plot-equity", default=None,
                    help="save equity curve PNG (e.g. reports/equity.png)")
    ap.add_argument("--walk-forward", type=int, default=0,
                    help="split data into N non-overlapping windows, run each "
                         "and aggregate. Exposes consistency of edge across time.")
    ap.add_argument("--monte-carlo", type=int, default=0,
                    help="shuffle trade order N times, report return / DD "
                         "percentiles. Tests whether edge depends on trade order.")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"),
                    help="compare two --output JSON files side-by-side")
    ap.add_argument("--seed", type=int, default=42,
                    help="random seed for determinism (default 42)")
    ap.add_argument("--analytics", action="store_true",
                    help="print advanced analytics (Sharpe/Sortino/Calmar, "
                         "expectancy, rolling metrics, temporal heatmap, "
                         "P&L distribution)")
    ap.add_argument("--partial-close", action="store_true",
                    help="close 50% of position at 1R, trail remainder. "
                         "Reduces avg win but dramatically lowers risk of "
                         "reversal-to-loss after good initial move.")
    ap.add_argument("--resume", action="store_true",
                    help="resume from last checkpoint (skip --reset). Reads "
                         "data/backtest.db current state; continues from last "
                         "timestamp where trades were recorded.")
    ap.add_argument("--checkpoint-every", type=int, default=100,
                    help="save progress marker every N cycles (default 100)")
    ap.add_argument("--strict", action="store_true",
                    help="disable relaxed filters — run with PRODUCTION confluence "
                         "threshold (3+) and Stable=blocked. Useful for apples-to-"
                         "apples comparison vs live.")
    args = ap.parse_args()

    # Determinism — seed random + numpy for reproducible backtest
    import random as _random
    _random.seed(args.seed)
    try:
        import numpy as _np
        _np.random.seed(args.seed)
    except ImportError:
        pass

    if args.compare:
        import json
        from pathlib import Path
        a_path, b_path = args.compare
        a = json.loads(Path(a_path).read_text())
        b = json.loads(Path(b_path).read_text())
        keys = ["total_trades", "win_rate_pct", "profit_factor",
                "return_pct", "max_drawdown_pct", "max_consec_losses",
                "alpha_vs_bh_pct", "breakevens"]
        print(f"{'Metric':<22} {'A: '+Path(a_path).stem[:12]:>16} {'B: '+Path(b_path).stem[:12]:>16} {'Δ (B-A)':>12}")
        print("-" * 70)
        for k in keys:
            va = a.get(k, "—")
            vb = b.get(k, "—")
            if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                delta = vb - va
                print(f"{k:<22} {va:>16} {vb:>16} {delta:>+12.2f}")
            else:
                print(f"{k:<22} {str(va):>16} {str(vb):>16} {'—':>12}")
        return

    if args.strict:
        os.environ.pop("QUANT_BACKTEST_RELAX", None)
        print("[backtest] --strict: production filters active (confluence>=3, Stable blocked)")

    if args.partial_close:
        os.environ["QUANT_BACKTEST_PARTIAL"] = "1"
        print("[backtest] --partial-close: 50% locked at 1R, remainder trails")

    if args.reset:
        _reset_backtest_db()

    if args.walk_forward and args.walk_forward > 1:
        # Split the --days window into N non-overlapping chunks and run each
        import datetime as _dt
        total_days = args.days
        chunk = max(total_days // args.walk_forward, 1)
        print(f"[walk-forward] {args.walk_forward} windows x {chunk} days each\n")
        window_results = []
        for w in range(args.walk_forward):
            _reset_backtest_db()
            # Fresh args with shifted dates
            end_offset_days = total_days - w * chunk
            start_offset_days = end_offset_days - chunk
            # Use --start/--end via computed dates
            end_date = _dt.date.today() - _dt.timedelta(days=start_offset_days)
            start_date = _dt.date.today() - _dt.timedelta(days=end_offset_days)
            args.start = start_date.isoformat()
            args.end = end_date.isoformat()
            print(f"\n[window {w+1}/{args.walk_forward}] {args.start} -> {args.end}")
            s = asyncio.run(_run_backtest(args))
            window_results.append({"window": f"{args.start}→{args.end}", **s})
        # Aggregate
        print("\n" + "=" * 70)
        print("WALK-FORWARD AGGREGATE")
        print("=" * 70)
        print(f"{'Window':<28} {'Trades':>7} {'WR%':>6} {'PF':>6} {'Return%':>9} {'MaxDD%':>8}")
        for r in window_results:
            print(f"{r['window']:<28} {r['total_trades']:>7} {r['win_rate_pct']:>6.1f} "
                  f"{r['profit_factor']:>6} {r['return_pct']:>9.2f} {r['max_drawdown_pct']:>8.2f}")
        # Summary stats
        returns = [r["return_pct"] for r in window_results]
        if returns:
            import statistics
            print(f"{'Mean':<28} {'-':>7} {'-':>6} {'-':>6} {statistics.mean(returns):>9.2f} "
                  f"{'(stdev ' + f'{statistics.stdev(returns) if len(returns)>1 else 0:.2f}' + ')':>20}")
        if args.output:
            import json
            from pathlib import Path
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps({"walk_forward": window_results}, indent=2, default=str))
            print(f"[walk-forward] saved {args.output}")
        return

    stats = asyncio.run(_run_backtest(args))

    print("\n" + "=" * 62)
    print("PRODUCTION BACKTEST — FINAL RESULTS")
    print("=" * 62)
    for k, v in stats.items():
        print(f"  {k:<22} {v}")
    print("=" * 62)
    print(f"[backtest] DB at: {os.environ['DATABASE_URL']}")
    print(f"[backtest] Production DB UNTOUCHED (data/sentinel.db)")

    if args.output:
        import json
        from pathlib import Path
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(stats, indent=2, default=str))
        print(f"[backtest] Stats saved to {args.output}")

    if args.export_csv:
        n = _export_trades_csv(args.export_csv)
        print(f"[backtest] Exported {n} trades to {args.export_csv}")

    if args.plot_equity:
        n = _export_equity_curve(args.plot_equity)
        if n:
            print(f"[backtest] Equity curve saved ({n} trades) to {args.plot_equity}")
        else:
            print(f"[backtest] No closed trades — equity curve not plotted")

    if args.monte_carlo > 0:
        mc = _monte_carlo_analysis(args.monte_carlo)
        print(f"\n[monte-carlo] {mc.get('n_simulations', 0)} simulations on "
              f"{mc.get('n_trades', 0)} trades:")
        for k, v in mc.items():
            if k in ("n_simulations", "n_trades"):
                continue
            print(f"  {k:<20} {v}")
        # Save to JSON so UI/downstream tools can read
        if args.output:
            import json
            from pathlib import Path
            try:
                existing = json.loads(Path(args.output).read_text())
            except Exception:
                existing = {}
            existing["monte_carlo"] = mc
            Path(args.output).write_text(json.dumps(existing, indent=2, default=str))

    if args.analytics:
        from src.backtest.analytics import full_analytics_report
        report = full_analytics_report()
        print("\n" + "=" * 62)
        print("ADVANCED ANALYTICS (P5)")
        print("=" * 62)
        import json as _json
        for section, data in report.items():
            print(f"\n─── {section} ───")
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        print(f"  {k}:")
                        if len(v) <= 10:
                            for k2, v2 in v.items():
                                print(f"    {k2}: {v2}")
                        else:
                            print(f"    ({len(v)} entries — see JSON output)")
                    else:
                        print(f"  {k:<26} {v}")
            else:
                print(f"  {data}")
        # Include in JSON output
        if args.output:
            import json
            from pathlib import Path
            existing = {}
            try:
                existing = json.loads(Path(args.output).read_text())
            except Exception:
                pass
            existing["analytics"] = report
            Path(args.output).write_text(json.dumps(existing, indent=2, default=str))


if __name__ == "__main__":
    main()
