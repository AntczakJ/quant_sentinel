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

    print(f"[backtest] Simulating {len(timestamps)} scan cycles from "
          f"{timestamps[0]} to {timestamps[-1]} (step {args.step_minutes}m)", flush=True)

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

    if args.output:
        import json
        from pathlib import Path
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(stats, indent=2, default=str))
        print(f"[backtest] Stats saved to {args.output}")


if __name__ == "__main__":
    main()
