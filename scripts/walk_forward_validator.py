"""
scripts/walk_forward_validator.py — anti-overfit walk-forward validator.

Run after EVERY retrain or factor weight change. Splits closed trades
chronologically into 4 equal windows, computes per-window WR, surfaces
"Did the most recent window perform like the others?"

If most-recent window WR drops by >5pp vs older windows, the recent
weight changes overfit the cohort. Don't promote.

Designed to be hooked into:
  - learning_health_check daily task
  - Pre-deploy of any QUANT_*_VETO env flag change
  - After self_learning.run_learning_cycle()

Usage:
    python scripts/walk_forward_validator.py [--db both] [--folds 4]
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_ts(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s.split("+")[0].split(".")[0], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, timestamp, status, profit FROM trades "
        "WHERE status IN ('WIN','LOSS') ORDER BY timestamp"
    ).fetchall()
    out = []
    for r in rows:
        ts = parse_ts(r[1])
        if ts:
            out.append({"id": r[0], "ts": ts, "status": r[2], "profit": r[3] or 0})
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--alarm-threshold-pp", type=float, default=5.0,
                    help="Alarm if recent fold WR is N pp below average of older folds")
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db"))
    trades.sort(key=lambda t: t["ts"])
    n = len(trades)

    if n < args.folds * 5:
        print(f"Too few trades for walk-forward: N={n}, need {args.folds * 5}+")
        return 0

    print(f"Walk-forward: N={n}, {args.folds} chronological folds")
    print(f"Range: {trades[0]['ts'].date()} -> {trades[-1]['ts'].date()}\n")

    fold_size = n // args.folds
    fold_wrs = []
    fold_pls = []
    for k in range(args.folds):
        start = k * fold_size
        end = (k + 1) * fold_size if k < args.folds - 1 else n
        fold = trades[start:end]
        wins = sum(1 for t in fold if t["status"] == "WIN")
        wr = wins / len(fold) * 100
        pl = sum(t["profit"] for t in fold)
        fold_wrs.append(wr)
        fold_pls.append(pl)
        date_lo = fold[0]["ts"].date()
        date_hi = fold[-1]["ts"].date()
        print(f"Fold {k+1}: {date_lo} -> {date_hi}  N={len(fold):>3}  "
              f"WR={wr:>5.1f}%  P/L=${pl:>+8.2f}")

    # Compute alarm: is the LAST fold significantly worse than the AVERAGE of earlier folds?
    recent_wr = fold_wrs[-1]
    older_wrs = fold_wrs[:-1]
    older_avg = sum(older_wrs) / len(older_wrs) if older_wrs else 0
    delta = recent_wr - older_avg

    print(f"\nRecent fold WR: {recent_wr:.1f}%")
    print(f"Older folds avg: {older_avg:.1f}%")
    print(f"Delta: {delta:+.1f}pp")

    print()
    if delta < -args.alarm_threshold_pp:
        print(f"  /!\\  ALARM — recent WR {recent_wr:.1f}% is {abs(delta):.1f}pp BELOW "
              f"older fold avg ({older_avg:.1f}%). Possible overfit on recent data.")
        print(f"  Threshold: -{args.alarm_threshold_pp}pp; actual delta: {delta:+.1f}pp")
        return 1
    elif delta > args.alarm_threshold_pp * 2:
        print(f"  Recent WR {recent_wr:.1f}% is +{delta:.1f}pp above older folds — "
              f"genuine improvement OR regime shift. Track.")
        return 0
    else:
        print(f"  OK — recent WR within ±{args.alarm_threshold_pp}pp of older folds.")
        return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
