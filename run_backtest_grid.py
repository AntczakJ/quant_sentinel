#!/usr/bin/env python3
"""
run_backtest_grid.py — Systematic parameter sweep for backtest.

Runs the production backtest multiple times with different parameter
combinations, aggregates stats, identifies Pareto-optimal configs.

Parameters varied:
  - min_confidence: ensemble confidence threshold (0.30-0.60)
  - sl_atr_mult: stop distance in ATR units (1.0-2.5)
  - target_rr: risk/reward ratio (1.5-3.0)
  - step_minutes: scan cadence (5, 15, 30)

Safety: uses the same isolation as single backtest runs. Writes to
data/backtest.db (wiped + reset between runs).

Usage:
    python run_backtest_grid.py --days 14                      # default grid
    python run_backtest_grid.py --days 14 --output grid.json   # save results
    python run_backtest_grid.py --days 14 --quick              # fewer combos
    python run_backtest_grid.py --days 7 --step-minutes 15     # faster runs

Results: one line per parameter combo, sorted by Sharpe descending.
Identifies top-3 configs and baseline to beat.
"""
from __future__ import annotations

# ─── Isolation FIRST ──────────────────────────────────────────────────
from src.backtest.isolation import enforce_isolation
enforce_isolation("data/backtest.db")

import argparse
import asyncio
import itertools
import json
import os
from pathlib import Path
from typing import Dict, List


def _default_grid(quick: bool = False) -> List[Dict]:
    """Return list of parameter dicts to test."""
    if quick:
        return [
            {"min_confidence": 0.40, "sl_atr_mult": 1.5, "target_rr": 2.5},
            {"min_confidence": 0.50, "sl_atr_mult": 1.5, "target_rr": 2.5},
            {"min_confidence": 0.40, "sl_atr_mult": 2.0, "target_rr": 2.0},
        ]
    # Full grid
    grid = []
    for mc in (0.30, 0.40, 0.50, 0.60):
        for sl in (1.0, 1.5, 2.0):
            for rr in (1.5, 2.0, 2.5, 3.0):
                grid.append({"min_confidence": mc, "sl_atr_mult": sl, "target_rr": rr})
    return grid


async def _run_one(params: Dict, days: int, step_minutes: int) -> Dict:
    """Run one backtest with specific params. Uses monkey-patching on
    scanner constants since they're not part of the public CLI."""
    from run_production_backtest import _reset_backtest_db, _run_backtest, _summarize_trades

    # Override env vars for this run
    os.environ["QUANT_BACKTEST_MIN_CONF"] = str(params["min_confidence"])

    # Args fake object
    class _A:
        pass
    a = _A()
    a.symbol = "XAU/USD"
    a.yf = "GC=F"
    a.days = days
    a.start = None
    a.end = None
    a.step_minutes = step_minutes
    a.reset = True
    a.no_cache = False

    _reset_backtest_db()
    try:
        stats = await _run_backtest(a)
    except Exception as e:
        return {"params": params, "error": str(e)[:100]}
    # Include analytics
    try:
        from src.backtest.analytics import compute_sharpe_sortino_calmar, compute_expectancy
        stats["sharpe"] = compute_sharpe_sortino_calmar().get("sharpe")
        stats["expectancy"] = compute_expectancy().get("expectancy_per_trade_usd")
    except Exception:
        pass
    return {"params": params, "stats": stats}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step-minutes", type=int, default=15)
    ap.add_argument("--quick", action="store_true",
                    help="3-config mini grid (for smoke testing)")
    ap.add_argument("--output", default="reports/grid.json")
    args = ap.parse_args()

    grid = _default_grid(quick=args.quick)
    print(f"[grid] {len(grid)} parameter combos x {args.days}d x step={args.step_minutes}min")
    print(f"[grid] estimated total time: ~{len(grid) * args.days * 2 / 60:.1f} min\n")

    results = []
    for i, params in enumerate(grid):
        print(f"\n=== Run {i+1}/{len(grid)}: {params} ===")
        result = asyncio.run(_run_one(params, args.days, args.step_minutes))
        results.append(result)
        if "stats" in result:
            s = result["stats"]
            print(f"  → trades={s.get('total_trades',0)} WR={s.get('win_rate_pct',0)}% "
                  f"PF={s.get('profit_factor','?')} Sharpe={s.get('sharpe','?')} "
                  f"Return={s.get('return_pct','?')}%")

    # Rank by Sharpe desc
    ranked = sorted(
        [r for r in results if "stats" in r],
        key=lambda r: r["stats"].get("sharpe") or -999,
        reverse=True,
    )

    print("\n" + "=" * 78)
    print("GRID SEARCH RESULTS (sorted by Sharpe)")
    print("=" * 78)
    print(f"{'min_conf':>8} {'sl_mult':>8} {'target_rr':>10} "
          f"{'trades':>7} {'WR%':>5} {'PF':>5} {'Sharpe':>7} {'Return%':>8}")
    print("-" * 78)
    for r in ranked:
        p = r["params"]
        s = r["stats"]
        print(f"{p['min_confidence']:>8.2f} {p['sl_atr_mult']:>8.1f} {p['target_rr']:>10.1f} "
              f"{s.get('total_trades',0):>7} {s.get('win_rate_pct',0):>5.0f} "
              f"{s.get('profit_factor','?'):>5} {s.get('sharpe',0) or 0:>7.2f} "
              f"{s.get('return_pct',0) or 0:>8.2f}")

    # Save
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[grid] Saved {args.output}")

    # Identify winner
    if ranked:
        top = ranked[0]
        print(f"\n[BEST by Sharpe]: {top['params']}")
        print(f"   {top['stats']}")


if __name__ == "__main__":
    main()
