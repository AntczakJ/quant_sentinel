"""
scripts/factor_attribution.py — split cohort P&L by factor presence.

For each factor, compute:
  - Cumulative profit when present
  - Cumulative profit when absent
  - Per-trade $ impact when present
  - WR delta vs cohort baseline

Differs from factor_predictive_power.py (chi-square WR) by focusing on
DOLLAR impact, not just win rate. A factor can be -EV in WR but +EV in
$ if its rare wins are large.

Usage:
    python scripts/factor_attribution.py [--db both]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT direction, status, profit, factors FROM trades "
        "WHERE status IN ('WIN','LOSS') AND factors IS NOT NULL"
    ).fetchall()
    out = []
    for r in rows:
        try:
            f = json.loads(r[3]) if r[3] else {}
        except Exception:
            f = {}
        out.append({
            "direction": r[0], "status": r[1], "profit": r[2] or 0,
            "factors": set(k for k, v in f.items() if v and not k.endswith("_penalty")),
        })
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=5)
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db"))

    n = len(trades)
    if not n:
        print("No trades.")
        return

    cohort_pl = sum(t["profit"] for t in trades)
    cohort_wr = sum(1 for t in trades if t["status"] == "WIN") / n * 100
    print(f"COHORT: N={n}, WR={cohort_wr:.1f}%, total P/L ${cohort_pl:+.2f}\n")

    all_factors = set()
    for t in trades:
        all_factors.update(t["factors"])

    rows = []
    for f in all_factors:
        with_f = [t for t in trades if f in t["factors"]]
        without_f = [t for t in trades if f not in t["factors"]]
        if len(with_f) < args.min_n:
            continue
        n_w = len(with_f)
        n_wo = len(without_f)
        wr_w = sum(1 for t in with_f if t["status"] == "WIN") / n_w * 100
        wr_wo = sum(1 for t in without_f if t["status"] == "WIN") / max(1, n_wo) * 100 if n_wo else 0
        pl_w = sum(t["profit"] for t in with_f)
        avg_pl_w = pl_w / n_w
        avg_pl_wo = sum(t["profit"] for t in without_f) / max(1, n_wo)
        rows.append({
            "factor": f, "n_w": n_w, "wr_w": wr_w, "wr_wo": wr_wo,
            "wr_delta": wr_w - wr_wo,
            "pl_w": pl_w, "avg_pl_w": avg_pl_w,
            "avg_pl_delta": avg_pl_w - avg_pl_wo,
        })

    # Sort by total $ impact when present (positive first)
    rows.sort(key=lambda r: r["pl_w"], reverse=True)
    print(f"{'factor':<25} {'N':>4} {'WR_w':>6} {'WRdelta':>7} {'$cumPL':>9} {'avg$':>8} {'avg$delta':>10}")
    print("-" * 80)
    for r in rows:
        print(f"{r['factor']:<25} {r['n_w']:>4} {r['wr_w']:>5.1f}% "
              f"{r['wr_delta']:>+6.1f} ${r['pl_w']:>+8.2f} ${r['avg_pl_w']:>+7.2f} "
              f"${r['avg_pl_delta']:>+9.2f}")

    print("\n=== INTERPRETATION ===")
    print("$cumPL: total P&L of trades where this factor fired")
    print("avg$ delta: avg P&L per trade WITH factor minus AVG P&L without")
    print("(positive $ delta = factor pays per-trade, even if WR low)")

    # Surface anomalies
    print("\n=== ANOMALIES ===")
    for r in rows:
        if r["wr_delta"] < -5 and r["pl_w"] > 0:
            print(f"  {r['factor']}: WR delta {r['wr_delta']:+.1f}pp but +${r['pl_w']:.0f} cum — "
                  f"big rare wins, small frequent losses")
        if r["wr_delta"] > 5 and r["pl_w"] < 0:
            print(f"  {r['factor']}: WR delta {r['wr_delta']:+.1f}pp but -${abs(r['pl_w']):.0f} cum — "
                  f"often wins small, occasional big losses")


if __name__ == "__main__":
    main()
