"""
scripts/wr_cube.py — multidimensional WR breakdown with Wilson confidence
intervals.

Slices the closed-trade cohort by:
  - timeframe (M5, M15, M30, H1, H4) — derived from pattern prefix
  - direction (LONG, SHORT)
  - session (asian, london, overlap, new_york, off_hours)
  - vol_regime (low, normal, high — if populated)
  - setup_grade (A+, A, B, C)

For each slice with N>=5 emits: n, wins, WR, Wilson 95% CI, avg P&L.

Surfaces the highest-WR and worst-WR slices so we know where to:
  - tighten filters (worst slices with N>=10)
  - allocate more risk (best slices with significant CI separation)
  - retire entirely (slices with confidence interval below 30% upper bound)

Usage:
    python scripts/wr_cube.py [--db both] [--min-n 5] [--output path.md]
"""
from __future__ import annotations

import argparse
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_TF_PATTERN = re.compile(r"\[(M5|M15|M30|H1|H4)\]")


def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% CI for binomial proportion. Robust on small n."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def derive_tf(pattern: str | None) -> str:
    if not pattern:
        return "?"
    m = _TF_PATTERN.search(pattern)
    return m.group(1) if m else "?"


def fetch_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, direction, status, profit, setup_grade, setup_score,
               pattern, session, vol_regime
        FROM trades
        WHERE status IN ('WIN', 'LOSS')
    """).fetchall()
    cols = ["id", "direction", "status", "profit", "setup_grade",
            "setup_score", "pattern", "session", "vol_regime"]
    out = [dict(zip(cols, r)) for r in rows]
    conn.close()
    return out


def slice_table(trades, key_fn, label_fn=None):
    """Group trades by key_fn(trade), return list of slice rows."""
    label_fn = label_fn or (lambda k: k)
    by_key = defaultdict(list)
    for t in trades:
        k = key_fn(t)
        if k is None:
            k = "?"
        by_key[k].append(t)
    rows = []
    for k, ts in by_key.items():
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        wr = w / n * 100 if n else 0
        ci_lo, ci_hi = wilson_ci(w, n)
        pl = sum(t.get("profit") or 0 for t in ts)
        rows.append({
            "key": label_fn(k),
            "n": n,
            "wins": w,
            "wr": wr,
            "ci_lo_pct": ci_lo * 100,
            "ci_hi_pct": ci_hi * 100,
            "ci_width_pp": (ci_hi - ci_lo) * 100,
            "total_pl": pl,
            "avg_pl": pl / n if n else 0,
        })
    rows.sort(key=lambda r: r["wr"], reverse=True)
    return rows


def cross_slice(trades, key1_fn, key2_fn, min_n=5):
    """Cross-tab: returns dict[(k1, k2)] -> stats."""
    by = defaultdict(list)
    for t in trades:
        k1, k2 = key1_fn(t) or "?", key2_fn(t) or "?"
        by[(k1, k2)].append(t)
    rows = []
    for (k1, k2), ts in by.items():
        n = len(ts)
        if n < min_n:
            continue
        w = sum(1 for t in ts if t["status"] == "WIN")
        ci_lo, ci_hi = wilson_ci(w, n)
        pl = sum(t.get("profit") or 0 for t in ts)
        rows.append({
            "k1": k1, "k2": k2, "n": n, "wins": w,
            "wr": w / n * 100,
            "ci_lo_pct": ci_lo * 100,
            "ci_hi_pct": ci_hi * 100,
            "total_pl": pl,
        })
    return rows


def print_table(title, rows, min_n):
    print(f"\n=== {title} ===")
    print(f"{'key':<22} {'N':>4} {'WR':>6} {'CI_lo':>6} {'CI_hi':>6} {'avg P/L':>9} {'tot P/L':>9}")
    print("-" * 80)
    for r in rows:
        if r["n"] < min_n:
            continue
        print(f"{str(r['key']):<22} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['ci_lo_pct']:>5.1f}% {r['ci_hi_pct']:>5.1f}% "
              f"${r.get('avg_pl', 0):>+8.2f} ${r.get('total_pl', 0):>+8.2f}")


def find_actionable(rows, min_n=10):
    """Return slices with stats actionable for filter tuning."""
    actionable = []
    for r in rows:
        if r["n"] < min_n:
            continue
        # Strong losing slice — upper bound below 35%
        if r["ci_hi_pct"] < 35:
            actionable.append((r, "BLOCK", f"upper-CI {r['ci_hi_pct']:.1f}% < 35%"))
        # Strong winning slice — lower bound above 50%
        elif r["ci_lo_pct"] > 50:
            actionable.append((r, "BOOST", f"lower-CI {r['ci_lo_pct']:.1f}% > 50%"))
    return actionable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=5)
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
    ci_lo, ci_hi = wilson_ci(wins, n)
    print(f"COHORT: {n} trades, WR {wins/n*100:.1f}% "
          f"[Wilson 95% CI {ci_lo*100:.1f}-{ci_hi*100:.1f}%]")

    # 1D slices
    slices = {
        "by direction": slice_table(trades, lambda t: t["direction"]),
        "by TF": slice_table(trades, lambda t: derive_tf(t.get("pattern"))),
        "by session": slice_table(trades, lambda t: t.get("session")),
        "by setup_grade": slice_table(trades, lambda t: t.get("setup_grade")),
        "by vol_regime": slice_table(trades, lambda t: t.get("vol_regime")),
    }
    for title, rows in slices.items():
        print_table(title, rows, args.min_n)

    # 2D cross-slices (highlight worst combinations)
    print("\n=== Cross: TF × direction (n>=5) ===")
    print(f"{'TF':<5} {'dir':<6} {'N':>4} {'WR':>6} {'CI_lo':>6} {'CI_hi':>6} {'P/L':>10}")
    cross = cross_slice(
        trades,
        lambda t: derive_tf(t.get("pattern")),
        lambda t: t["direction"],
        min_n=args.min_n,
    )
    cross.sort(key=lambda r: r["wr"], reverse=True)
    for r in cross:
        print(f"{r['k1']:<5} {r['k2']:<6} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['ci_lo_pct']:>5.1f}% {r['ci_hi_pct']:>5.1f}% "
              f"${r['total_pl']:>+8.2f}")

    print("\n=== Cross: TF × session (n>=5) ===")
    cross = cross_slice(
        trades,
        lambda t: derive_tf(t.get("pattern")),
        lambda t: t.get("session"),
        min_n=args.min_n,
    )
    cross.sort(key=lambda r: r["wr"], reverse=True)
    print(f"{'TF':<5} {'session':<12} {'N':>4} {'WR':>6} {'CI_lo':>6} {'CI_hi':>6} {'P/L':>10}")
    for r in cross:
        print(f"{r['k1']:<5} {str(r['k2']):<12} {r['n']:>4} {r['wr']:>5.1f}% "
              f"{r['ci_lo_pct']:>5.1f}% {r['ci_hi_pct']:>5.1f}% "
              f"${r['total_pl']:>+8.2f}")

    # Actionable findings
    print("\n=== ACTIONABLE (n>=10, CI separated) ===")
    all_slices = []
    for title, rows in slices.items():
        for r in rows:
            r["_origin"] = title
            all_slices.append(r)
    actions = find_actionable(all_slices, min_n=10)
    if not actions:
        print("None — sample too small or no clear separation yet.")
    for r, action, why in actions:
        print(f"  {action:<6} {r['_origin']:<18} '{r['key']}' (N={r['n']}, {why})")

    if args.output:
        out = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
        out.parent.mkdir(exist_ok=True, parents=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# WR Cube — {n} trades, WR {wins/n*100:.1f}% [Wilson 95% CI {ci_lo*100:.1f}-{ci_hi*100:.1f}%]\n\n")
            for title, rows in slices.items():
                f.write(f"## {title}\n\n| Key | N | WR | CI lo | CI hi | avg P/L | tot P/L |\n|---|---|---|---|---|---|---|\n")
                for r in rows:
                    if r["n"] < args.min_n:
                        continue
                    f.write(f"| {r['key']} | {r['n']} | {r['wr']:.1f}% | "
                            f"{r['ci_lo_pct']:.1f}% | {r['ci_hi_pct']:.1f}% | "
                            f"${r.get('avg_pl', 0):+.2f} | ${r.get('total_pl', 0):+.2f} |\n")
                f.write("\n")
        print(f"\nWritten -> {out}")


if __name__ == "__main__":
    main()
