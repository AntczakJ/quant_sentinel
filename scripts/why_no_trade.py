"""
scripts/why_no_trade.py — explain why the scanner has not opened a trade.

Aggregates rejected_setups + scanner log filters over a recent window and
summarises which defenses are blocking the most setups. Helps the operator
diagnose "no trades for 6 hours — bug or correct conservatism?"

Output sections:
  1. Activity counts (cycles, trades, rejections) over window
  2. Top rejection reasons (filter_name + reason text)
  3. Per-direction split (LONG vs SHORT)
  4. Per-TF split (M5, M15, M30, H1, H4)
  5. Time-of-day clustering (hour-bins)
  6. Verdict: most likely cause

Usage:
    python scripts/why_no_trade.py [--hours 24]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24, help="Lookback window")
    ap.add_argument("--db", default="data/sentinel.db")
    args = ap.parse_args()

    cutoff = datetime.now() - timedelta(hours=args.hours)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(ROOT / args.db)

    # Activity
    n_rejections = conn.execute(
        "SELECT COUNT(*) FROM rejected_setups WHERE timestamp >= ?", (cutoff_str,)
    ).fetchone()[0]
    n_trades = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE timestamp >= ?", (cutoff_str,)
    ).fetchone()[0]
    last_trade = conn.execute(
        "SELECT id, timestamp, direction, status FROM trades "
        "ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    print(f"=== WHY NO TRADE — last {args.hours}h (since {cutoff_str}) ===\n")
    print(f"Trades opened: {n_trades}")
    print(f"Rejections logged: {n_rejections}")
    if last_trade:
        last_dt = datetime.strptime(last_trade[1].split('+')[0].split('.')[0],
                                     "%Y-%m-%d %H:%M:%S")
        age = datetime.now() - last_dt
        print(f"Last trade: #{last_trade[0]} {last_trade[2]} {last_trade[3]} "
              f"at {last_trade[1]} ({age.days}d {age.seconds//3600}h ago)")

    if n_rejections == 0:
        print("\nNo rejections logged — scanner may be paused or not running.")
        # Pause flag
        if (ROOT / "data" / "SCANNER_PAUSED").exists():
            print("  /!\\  SCANNER_PAUSED file exists — scanner paused on purpose")
        return

    # Top filters
    print("\n=== Top rejection FILTERS (window) ===")
    rows = conn.execute(
        """SELECT filter_name, COUNT(*) as n
           FROM rejected_setups WHERE timestamp >= ?
           GROUP BY filter_name ORDER BY n DESC LIMIT 12""",
        (cutoff_str,)
    ).fetchall()
    for filter_name, n in rows:
        pct = n / max(1, n_rejections) * 100
        print(f"  {filter_name:<35} {n:>6} ({pct:>5.1f}%)")

    # Top reasons
    print("\n=== Top rejection REASONS (text) ===")
    rows = conn.execute(
        """SELECT rejection_reason, COUNT(*) as n
           FROM rejected_setups WHERE timestamp >= ?
           GROUP BY rejection_reason ORDER BY n DESC LIMIT 15""",
        (cutoff_str,)
    ).fetchall()
    for reason, n in rows:
        if reason:
            print(f"  {reason[:58]:<58} {n:>5}")

    # Direction
    print("\n=== Direction split ===")
    rows = conn.execute(
        """SELECT direction, COUNT(*) FROM rejected_setups
           WHERE timestamp >= ? GROUP BY direction""",
        (cutoff_str,)
    ).fetchall()
    for d, n in rows:
        print(f"  {d:<10} {n}")

    # Per-TF
    print("\n=== Per-timeframe split ===")
    rows = conn.execute(
        """SELECT timeframe, COUNT(*) FROM rejected_setups
           WHERE timestamp >= ? GROUP BY timeframe ORDER BY 2 DESC""",
        (cutoff_str,)
    ).fetchall()
    for tf, n in rows:
        print(f"  {tf:<5} {n}")

    # Hour clustering
    print("\n=== Per-hour split (rejections) ===")
    rows = conn.execute(
        """SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr, COUNT(*) as n
           FROM rejected_setups WHERE timestamp >= ?
           GROUP BY hr ORDER BY hr DESC LIMIT 24""",
        (cutoff_str,)
    ).fetchall()
    for hr, n in rows:
        bar = "#" * min(50, n // 5)
        print(f"  {hr}  {n:>4} {bar}")

    # Verdict
    print("\n=== VERDICT ===")
    if rows := conn.execute(
        """SELECT filter_name, COUNT(*) FROM rejected_setups
           WHERE timestamp >= ? GROUP BY filter_name ORDER BY 2 DESC LIMIT 1""",
        (cutoff_str,)
    ).fetchone():
        top_filter, top_n = rows
        if top_n / max(1, n_rejections) > 0.5:
            print(f"  MAIN BLOCKER: {top_filter} ({top_n}/{n_rejections} = "
                  f"{top_n/n_rejections*100:.0f}% of rejections)")
        else:
            print(f"  Mixed blockers — top filter is {top_filter} but only "
                  f"{top_n/n_rejections*100:.0f}% of rejections")

    if n_trades == 0 and n_rejections > 100:
        print("  Scanner running but ALL setups blocked. System may be over-tight.")
    elif n_trades > 0:
        print(f"  Scanner found {n_trades} trades. Operating normally.")

    conn.close()


if __name__ == "__main__":
    main()
