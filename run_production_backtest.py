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


def _reset_backtest_db() -> None:
    """Wipe data/backtest.db for a clean run."""
    assert_not_production_db()
    path = Path(os.environ["DATABASE_URL"])
    if path.exists():
        path.unlink()
        print(f"[backtest] Reset: removed {path}")


def _summarize_trades() -> dict:
    """Query backtest.db trades table for final stats."""
    assert_not_production_db()
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        row = cur.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN status IN ('WIN','PROFIT') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status IN ('LOSS','LOSE') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END), "
            "AVG(profit) "
            "FROM trades"
        ).fetchone()
        total, wins, losses, still_open, avg_profit = row
        total = total or 0
        wins = wins or 0
        losses = losses or 0
        still_open = still_open or 0
        closed = (wins + losses)
        wr = (wins / closed * 100) if closed else 0.0

        # Cumulative profit (closed trades only)
        cum_row = cur.execute(
            "SELECT SUM(profit) FROM trades "
            "WHERE status IN ('WIN','PROFIT','LOSS','LOSE') AND profit IS NOT NULL"
        ).fetchone()
        cum_profit = cum_row[0] or 0.0

        return {
            "total_trades": total,
            "closed": closed,
            "wins": wins,
            "losses": losses,
            "still_open": still_open,
            "win_rate_pct": round(wr, 1),
            "avg_profit": round(avg_profit, 2) if avg_profit is not None else 0.0,
            "cumulative_profit": round(cum_profit, 2),
        }
    finally:
        conn.close()


async def _resolve_open_trades(db, provider: HistoricalProvider) -> None:
    """Bar-by-bar SL/TP check for any OPEN trades.

    Walks forward from each trade's entry bar to simulated_now, marks WIN
    if TP hit, LOSS if SL hit. Writes profit in absolute-price terms to
    match the production resolver output format.
    """
    assert_not_production_db()
    # Use the 5m cache for highest-resolution SL/TP detection
    tf_cache = provider._cache.get("5m")
    if tf_cache is None or tf_cache.empty:
        tf_cache = provider._cache.get("15m")
    if tf_cache is None or tf_cache.empty:
        return
    now_ts = provider.simulated_now
    if now_ts is None:
        return

    open_rows = db._query(
        "SELECT id, direction, entry, sl, tp, timestamp FROM trades WHERE status='OPEN'"
    )
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
        for _, bar in window.iterrows():
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            if is_long:
                if bar_high >= tp:
                    hit_status, hit_price = "WIN", tp
                    break
                if bar_low <= sl:
                    hit_status, hit_price = "LOSS", sl
                    break
            else:  # SHORT
                if bar_low <= tp:
                    hit_status, hit_price = "WIN", tp
                    break
                if bar_high >= sl:
                    hit_status, hit_price = "LOSS", sl
                    break
        if hit_status and hit_price is not None:
            # Compute profit in price units (matches production log_trade style)
            if is_long:
                profit = round(hit_price - entry, 2)
            else:
                profit = round(entry - hit_price, 2)
            db._execute("UPDATE trades SET status=?, profit=? WHERE id=?",
                        (hit_status, profit, t_id))
            logger.debug(f"[backtest] Trade #{t_id} resolved {hit_status} profit={profit}")


async def _run_backtest(args) -> dict:
    # ── 1. Load historical data ───────────────────────────────────────
    print(f"[backtest] Loading {args.yf} ({args.days} days of 5m/15m/1h/4h)...", flush=True)
    period_for_fetch = f"{max(args.days, 60)}d"  # yfinance 5m max 60d anyway
    provider = HistoricalProvider.from_yfinance(
        symbol=args.symbol, yf_symbol=args.yf, period=period_for_fetch,
        intervals=("5m", "15m", "1h", "4h"),
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

    db = NewsDB()

    # ── 3. Build timestamp grid ───────────────────────────────────────
    grid_cache = provider._cache.get("15m")
    if grid_cache is None:
        raise RuntimeError("15m cache required for simulation grid")
    end_ts = grid_cache["timestamp"].iloc[-1]
    start_ts = end_ts - pd.Timedelta(days=args.days)
    # Align to step (e.g. every 15 min)
    step = pd.Timedelta(minutes=args.step_minutes)
    timestamps = pd.date_range(start_ts, end_ts, freq=step, tz="UTC")
    # Require at least 100 prior bars for warmup — drop earliest if not enough
    min_start = provider.min_bar_time("15m") + pd.Timedelta(hours=50) if provider.min_bar_time("15m") else start_ts
    timestamps = timestamps[timestamps >= min_start]

    print(f"[backtest] Simulating {len(timestamps)} scan cycles from "
          f"{timestamps[0]} to {timestamps[-1]} (step {args.step_minutes}m)", flush=True)

    # ── 4. Walk forward ───────────────────────────────────────────────
    t0 = _time.time()
    last_day_logged = None
    last_trade_count = 0
    for i, ts in enumerate(timestamps):
        provider.set_simulated_now(ts)
        # Run one scan cycle
        try:
            # Use cascade_mtf_scan directly — avoids weekend guard + heartbeat
            # which are wall-clock dependent and not useful in backtest.
            trade = scanner_mod.cascade_mtf_scan(db, balance=10_000.0, currency="USD")
        except Exception as e:
            logger.debug(f"[backtest] scan at {ts} failed: {e}")
            trade = None

        # Persist trade (same path as production log_trade)
        if trade:
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
            except Exception as e:
                logger.debug(f"[backtest] log_trade failed: {e}")

        # Resolve any OPEN trades against bars since entry
        await _resolve_open_trades(db, provider)

        # Daily progress log
        day = ts.date()
        if day != last_day_logged:
            stats = _summarize_trades()
            new_trades = stats["total_trades"] - last_trade_count
            last_trade_count = stats["total_trades"]
            elapsed = _time.time() - t0
            print(f"[backtest] {day} — trades so far: {stats['total_trades']} "
                  f"(+{new_trades} today), WR: {stats['win_rate_pct']:.1f}%, "
                  f"cum_profit: {stats['cumulative_profit']:+.2f} "
                  f"(elapsed {elapsed:.0f}s)", flush=True)
            last_day_logged = day

    # ── 5. Final forced resolution (close any still-open on last bar) ──
    # Leave still_open as-is; stats show them separately.

    return _summarize_trades()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAU/USD", help="display symbol")
    ap.add_argument("--yf", default="GC=F", help="yfinance ticker to fetch")
    ap.add_argument("--days", type=int, default=30, help="simulation window in days")
    ap.add_argument("--step-minutes", type=int, default=15,
                    help="scan cadence in minutes (production: 15)")
    ap.add_argument("--reset", action="store_true",
                    help="wipe data/backtest.db before running")
    args = ap.parse_args()

    if args.reset:
        _reset_backtest_db()

    stats = asyncio.run(_run_backtest(args))

    print("\n" + "=" * 62)
    print("PRODUCTION BACKTEST — FINAL RESULTS")
    print("=" * 62)
    for k, v in stats.items():
        print(f"  {k:<22} {v}")
    print("=" * 62)
    print(f"[backtest] DB at: {os.environ['DATABASE_URL']}")
    print(f"[backtest] Production DB UNTOUCHED (data/sentinel.db)")


if __name__ == "__main__":
    main()
