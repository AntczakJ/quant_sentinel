"""
scripts/hourly_heatmap.py — WR by hour-of-day + day-of-week heatmap.

Slices closed trades by:
  - hour of day (UTC) 0-23
  - day of week 0-6 (Mon=0)
  - hour × day cross

Wilson 95% CIs per cell. Surfaces the best/worst time windows.

Usage:
    python scripts/hourly_heatmap.py [--db both] [--min-n 3] [--output path.md]
"""
from __future__ import annotations

import argparse
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts.split("+")[0], fmt)
        except ValueError:
            continue
    return None


def fetch_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, timestamp, direction, status, profit
        FROM trades
        WHERE status IN ('WIN','LOSS')
    """).fetchall()
    out = []
    for r in rows:
        ts = parse_ts(r[1])
        if ts is None:
            continue
        out.append({
            "id": r[0], "ts": ts, "direction": r[2],
            "status": r[3], "profit": r[4] or 0,
        })
    conn.close()
    return out


def hourly_table(trades):
    by_hour = defaultdict(list)
    for t in trades:
        by_hour[t["ts"].hour].append(t)
    rows = []
    for h in range(24):
        ts = by_hour.get(h, [])
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        ci_lo, ci_hi = wilson_ci(w, n)
        pl = sum(t["profit"] for t in ts)
        rows.append({
            "hour": h, "n": n, "wins": w,
            "wr": w / n * 100 if n else 0,
            "ci_lo": ci_lo * 100, "ci_hi": ci_hi * 100,
            "total_pl": pl,
        })
    return rows


def dow_table(trades):
    by_dow = defaultdict(list)
    for t in trades:
        by_dow[t["ts"].weekday()].append(t)
    rows = []
    for d in range(7):
        ts = by_dow.get(d, [])
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        ci_lo, ci_hi = wilson_ci(w, n)
        pl = sum(t["profit"] for t in ts)
        rows.append({
            "day": DAYS[d], "n": n, "wins": w,
            "wr": w / n * 100 if n else 0,
            "ci_lo": ci_lo * 100, "ci_hi": ci_hi * 100,
            "total_pl": pl,
        })
    return rows


def hour_dow_grid(trades):
    """Returns dict[(dow, hour)] -> stats."""
    by = defaultdict(list)
    for t in trades:
        by[(t["ts"].weekday(), t["ts"].hour)].append(t)
    grid = {}
    for k, ts in by.items():
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        grid[k] = {"n": n, "wins": w, "wr": w/n*100 if n else 0,
                   "pl": sum(t["profit"] for t in ts)}
    return grid


def find_actionable(rows, label, min_n=10):
    out = []
    for r in rows:
        if r["n"] < min_n:
            continue
        if r["ci_hi"] < 35:
            out.append((label, r, "BLOCK", f"upper-CI {r['ci_hi']:.1f}% < 35%"))
        elif r["ci_lo"] > 50:
            out.append((label, r, "BOOST", f"lower-CI {r['ci_lo']:.1f}% > 50%"))
    return out


def print_hour_table(rows, min_n):
    print(f"{'hour (UTC)':<11} {'N':>4} {'wins':>5} {'WR':>6} {'CI_lo':>6} {'CI_hi':>6} {'P/L':>10}")
    for r in rows:
        if r["n"] < min_n:
            continue
        print(f"{r['hour']:>10}h {r['n']:>4} {r['wins']:>5} {r['wr']:>5.1f}% "
              f"{r['ci_lo']:>5.1f}% {r['ci_hi']:>5.1f}% ${r['total_pl']:>+8.2f}")


def print_dow_table(rows, min_n):
    print(f"{'day':<5} {'N':>4} {'wins':>5} {'WR':>6} {'CI_lo':>6} {'CI_hi':>6} {'P/L':>10}")
    for r in rows:
        if r["n"] < min_n:
            continue
        print(f"{r['day']:<5} {r['n']:>4} {r['wins']:>5} {r['wr']:>5.1f}% "
              f"{r['ci_lo']:>5.1f}% {r['ci_hi']:>5.1f}% ${r['total_pl']:>+8.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=3)
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch_trades("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch_trades("data/backtest.db"))

    n = len(trades)
    if not n:
        print("No trades.")
        return
    wins = sum(1 for t in trades if t["status"] == "WIN")
    print(f"COHORT: {n} trades, WR {wins/n*100:.1f}%\n")

    print("=" * 60)
    print("WR by hour of day (UTC)")
    print("=" * 60)
    hr = hourly_table(trades)
    print_hour_table(hr, args.min_n)

    print("\n" + "=" * 60)
    print("WR by day of week")
    print("=" * 60)
    dow = dow_table(trades)
    print_dow_table(dow, args.min_n)

    print("\n" + "=" * 60)
    print("WR by hour x DoW grid (n>=2)")
    print("=" * 60)
    grid = hour_dow_grid(trades)
    # Print compact heatmap: rows = hour, cols = day
    print(f"{'hour':<5}", *[f"{d:>5}" for d in DAYS])
    for h in range(24):
        cells = []
        for d in range(7):
            stats = grid.get((d, h))
            if stats and stats["n"] >= 2:
                cells.append(f"{stats['wr']:>4.0f}%")
            else:
                cells.append("    -")
        print(f"{h:>3}h ", " ".join(cells))

    # Actionable
    print("\n" + "=" * 60)
    print("ACTIONABLE (n>=10, CI separated)")
    print("=" * 60)
    actions = find_actionable(hr, "hour", min_n=10) + find_actionable(dow, "dow", min_n=10)
    if not actions:
        print("None — sample too small or no clear separation.")
    for label, r, action, why in actions:
        key = r.get("hour", r.get("day"))
        print(f"  {action:<6} {label:<6} '{key}' (N={r['n']}, {why}, total P/L ${r['total_pl']:+.2f})")

    if args.output:
        out = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
        out.parent.mkdir(exist_ok=True, parents=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# Hourly Heatmap — {n} trades, WR {wins/n*100:.1f}%\n\n")
            f.write("## Hour of day (UTC)\n\n| Hour | N | WR | CI lo | CI hi | P/L |\n|---|---|---|---|---|---|\n")
            for r in hr:
                if r["n"] < args.min_n:
                    continue
                f.write(f"| {r['hour']:02d}h | {r['n']} | {r['wr']:.1f}% | "
                        f"{r['ci_lo']:.1f}% | {r['ci_hi']:.1f}% | ${r['total_pl']:+.2f} |\n")
            f.write("\n## Day of week\n\n| Day | N | WR | CI lo | CI hi | P/L |\n|---|---|---|---|---|---|\n")
            for r in dow:
                if r["n"] < args.min_n:
                    continue
                f.write(f"| {r['day']} | {r['n']} | {r['wr']:.1f}% | "
                        f"{r['ci_lo']:.1f}% | {r['ci_hi']:.1f}% | ${r['total_pl']:+.2f} |\n")
        print(f"\nWritten -> {out}")


if __name__ == "__main__":
    main()
