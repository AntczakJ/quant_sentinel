#!/usr/bin/env python3
"""
compare_sweep_2026-04-26.py — produce side-by-side comparison of all
backtest variants run during the 2026-04-26 session.

Reads reports/2026-04-26/*.json and emits a delta table showing which
single-variable changes moved which metrics. Built specifically for
small-sample (n<50) honesty: prints sample sizes prominently and warns
when comparisons fall below statistical-power thresholds.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPORT_DIR = Path("reports/2026-04-26")

# Order matters: baseline first, others below it sorted by intervention type
EXPECTED_VARIANTS = [
    "baseline",
    "trailing_off",
    "timeexit_prodparity",
    "long_risk_half",
    "combo_trailoff_timeexit",
]

KEY_METRICS = [
    "total_trades",
    "win_rate_pct",
    "profit_factor",
    "return_pct",
    "max_drawdown_pct",
    "max_consec_losses",
    "breakevens",
    "ensemble_signals_long",
    "ensemble_signals_short",
]


def load_variant(name: str) -> dict | None:
    path = REPORT_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:+.2f}" if abs(v) > 0.01 else "0"
    if v == "inf":
        return "∞"
    return str(v)


def main():
    results = {}
    for v in EXPECTED_VARIANTS:
        d = load_variant(v)
        if d is not None:
            results[v] = d

    if "baseline" not in results:
        print("ERROR: baseline.json missing — run baseline first")
        sys.exit(1)

    baseline = results["baseline"]
    n_base = baseline.get("total_trades", 0)

    print()
    print(f"{'='*90}")
    print(f"BACKTEST SWEEP COMPARISON — 2026-04-26 (30-day window, deterministic seed)")
    print(f"{'='*90}")
    print(f"Baseline trades: {n_base}")
    if n_base < 30:
        print("[!] SAMPLE-SIZE WARNING: < 30 trades — single-variable")
        print("    direction-of-effect is the signal; absolute deltas are noisy.")
    print()

    # Wide table: one column per variant
    cols = list(results.keys())
    width_metric = 22
    width_col = 14
    header = f"{'metric':<{width_metric}}" + "".join(f"{c:>{width_col}}" for c in cols)
    print(header)
    print("-" * len(header))
    for m in KEY_METRICS:
        row = f"{m:<{width_metric}}"
        for c in cols:
            v = results[c].get(m, None)
            row += f"{fmt(v):>{width_col}}"
        print(row)
    print()

    # Deltas vs baseline
    print(f"{'='*90}")
    print("DELTAS vs baseline (B - baseline)")
    print(f"{'='*90}")
    print(f"{'variant':<28}", end="")
    for m in ("win_rate_pct", "profit_factor", "return_pct", "max_drawdown_pct"):
        print(f"{'Δ ' + m:>16}", end="")
    print()
    print("-" * 92)
    for c in cols:
        if c == "baseline":
            continue
        print(f"{c:<28}", end="")
        for m in ("win_rate_pct", "profit_factor", "return_pct", "max_drawdown_pct"):
            b = baseline.get(m)
            v = results[c].get(m)
            try:
                if b == "inf" or v == "inf":
                    print(f"{'inf':>16}", end="")
                    continue
                d = float(v) - float(b)
                print(f"{d:>+16.2f}", end="")
            except (TypeError, ValueError):
                print(f"{'—':>16}", end="")
        print()
    print()

    # Per-direction split (LONG vs SHORT) using export CSV — only baseline + first 2 variants
    print(f"{'='*90}")
    print("PER-DIRECTION SPLIT (LONG/SHORT) — read from *_trades.csv")
    print(f"{'='*90}")
    for c in cols:
        csv_path = REPORT_DIR / f"{c}_trades.csv"
        if not csv_path.exists():
            continue
        try:
            import csv as _csv
            rows = list(_csv.DictReader(open(csv_path, encoding="utf-8")))
            longs = [r for r in rows if "LONG" in (r.get("direction") or "").upper()]
            shorts = [r for r in rows if "SHORT" in (r.get("direction") or "").upper()]

            def stats(grp, label):
                if not grp:
                    return f"  {label:<18} no trades"
                wins = sum(1 for r in grp if r.get("status") in ("WIN", "PROFIT"))
                losses = sum(1 for r in grp if r.get("status") in ("LOSS", "LOSE"))
                closed = wins + losses
                wr = (wins / closed * 100) if closed else 0
                pnl = sum(float(r.get("profit") or 0) for r in grp if r.get("profit"))
                return (f"  {label:<18} n={len(grp)} closed={closed} "
                        f"WR={wr:.0f}% pnl={pnl:+.1f}")
            print(f"\n{c}:")
            print(stats(longs, "LONG"))
            print(stats(shorts, "SHORT"))
        except Exception as e:
            print(f"{c}: csv read failed: {e}")
    print()

    # Honest conclusion guide
    print(f"{'='*90}")
    print("HONEST INTERPRETATION GUIDE (small-sample regime)")
    print(f"{'='*90}")
    print("- A delta is a HYPOTHESIS, not a verdict, until walk-forward confirms")
    print("- Direction matters more than magnitude when n < 30")
    print("- If Δ PF < 0.2 with n < 30, treat as 'no signal'")
    print("- If LONG/SHORT split shows asymmetry, that's signal even at small n")


if __name__ == "__main__":
    main()
