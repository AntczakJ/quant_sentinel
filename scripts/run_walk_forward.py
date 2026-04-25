#!/usr/bin/env python3
"""
run_walk_forward.py — Convenience wrapper to run walk-forward backtest.

Usage:
    python scripts/run_walk_forward.py
    python scripts/run_walk_forward.py --start 2024-01-01 --end 2026-04-01 --train 90 --test 7 --step 7
    python scripts/run_walk_forward.py --quick  # 30/7/14 short test

Requires v1 production scanner (no v2 retraining done in walk-forward —
each window uses CURRENT live models). Useful to:
  - Verify edge stability across regimes
  - Identify weak periods (regime breakdowns)
  - Generate per-window report for shadow rollout decision
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backtest.walk_forward import walk_forward, print_summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-04-01")
    ap.add_argument("--train", type=int, default=90, help="train window days")
    ap.add_argument("--test", type=int, default=7, help="test window days")
    ap.add_argument("--step", type=int, default=7, help="step between windows")
    ap.add_argument("--quick", action="store_true",
                    help="quick mode: 30/7/14 (smaller windows + bigger steps)")
    ap.add_argument("--out", default="docs/walk_forward_results.json")
    args = ap.parse_args()

    if args.quick:
        args.train = 30
        args.test = 7
        args.step = 14

    print(f"Starting walk-forward: train={args.train}d, test={args.test}d, step={args.step}d")
    print(f"Period: {args.start} -> {args.end}")
    print(f"Output: {args.out}")
    print()

    results = walk_forward(
        start_date=args.start, end_date=args.end,
        train_days=args.train, test_days=args.test, step_days=args.step,
    )
    print_summary(results)
    results.save(args.out)
    print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
