"""
factor_edge_report.py — Empirical factor -> outcome correlation.

For each scanner factor (bos, choch, fvg, order_block, ichimoku_*, macro,
pin_bar, engulfing, etc.), compute:
  - n_trades where factor present
  - WR with factor present vs. baseline WR
  - Lift = WR_with - WR_baseline
  - Statistical significance (Wilson 95% CI)

Reads `trades.factors` (JSON column populated by smc_engine.score_setup_quality)
joined with trades.status. Output sorts by lift; positive-lift factors
deserve weight bumps, negative-lift factors deserve weight reductions or
removal.

Limitation: factors column may be missing for older trades (pre-2026-04-15).
Filter cohort to post-cutoff per CLAUDE.md `data_cohort_cutoff.md`.

USAGE
    .venv/Scripts/python.exe scripts/factor_edge_report.py

Read-only against data/sentinel.db. Writes report to
reports/<DATE>_factor_edge.md
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# DB path overridable via --db flag (default sentinel.db; pass
# data/backtest.db to analyze backtest cohort with same query).
# --cutoff ISO date filters trades to >= this date (default 2026-04-06,
# which is the post-scalp-first-rework live cohort start). Use
# 2020-01-01 to include all backtest periods.
import argparse as _argparse
_ap = _argparse.ArgumentParser()
_ap.add_argument("--db", default="data/sentinel.db")
_ap.add_argument("--cutoff", default="2026-04-06")
_args, _ = _ap.parse_known_args()
DB = REPO / _args.db if not Path(_args.db).is_absolute() else Path(_args.db)
COHORT_CUTOFF = _args.cutoff  # default 2026-04-06; override --cutoff


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    """Wilson 95% CI lower bound for win rate."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return max(0.0, center - margin)


def main() -> int:
    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        # Check if trades has a factors column
        cur.execute("PRAGMA table_info(trades)")
        cols = {c[1] for c in cur.fetchall()}
        if "factors" not in cols:
            # Try alternate column name
            for alt in ("factors_json", "setup_factors", "score_factors"):
                if alt in cols:
                    factor_col = alt
                    break
            else:
                print("ERR: no factors column in trades table")
                return 1
        else:
            factor_col = "factors"

        cur.execute(
            f"SELECT id, direction, status, profit, {factor_col} "
            "FROM trades "
            "WHERE status IN ('WIN', 'LOSS') AND timestamp >= ?",
            (COHORT_CUTOFF,)
        )
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No resolved trades in cohort.")
        return 0

    # Aggregate baseline
    n_total = len(rows)
    wins_total = sum(1 for r in rows if r[2] == "WIN")
    baseline_wr = wins_total / n_total if n_total else 0.0
    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}, WR_baseline={baseline_wr:.1%}")

    # Per-factor stats
    factor_stats: dict[str, dict] = {}
    for trade_id, direction, status, profit, factors_raw in rows:
        if not factors_raw:
            continue
        try:
            factors = json.loads(factors_raw) if isinstance(factors_raw, str) else factors_raw
        except Exception:
            continue
        # factors may be list of strings OR dict {factor: value}
        if isinstance(factors, dict):
            factor_keys = list(factors.keys())
        elif isinstance(factors, list):
            factor_keys = [str(f) for f in factors]
        else:
            continue
        for f in factor_keys:
            entry = factor_stats.setdefault(f, {"n": 0, "wins": 0, "long_n": 0, "long_wins": 0,
                                                "short_n": 0, "short_wins": 0, "pnl": 0.0})
            entry["n"] += 1
            entry["pnl"] += float(profit or 0.0)
            if status == "WIN":
                entry["wins"] += 1
            if direction == "LONG":
                entry["long_n"] += 1
                if status == "WIN":
                    entry["long_wins"] += 1
            else:
                entry["short_n"] += 1
                if status == "WIN":
                    entry["short_wins"] += 1

    rows_out = []
    for f, e in factor_stats.items():
        n = e["n"]
        if n < 5:
            continue
        wr = e["wins"] / n
        lift = wr - baseline_wr
        wlow = wilson_lower(e["wins"], n)
        rows_out.append({
            "factor": f, "n": n, "wins": e["wins"], "wr": wr, "lift": lift,
            "wilson_low": wlow, "long_n": e["long_n"], "long_wr": (e["long_wins"] / e["long_n"]) if e["long_n"] else 0,
            "short_n": e["short_n"], "short_wr": (e["short_wins"] / e["short_n"]) if e["short_n"] else 0,
            "avg_pnl": e["pnl"] / n,
        })

    rows_out.sort(key=lambda r: r["lift"], reverse=True)

    print()
    print("=" * 120)
    print(f"{'factor':38}{'n':>5}{'wins':>5}{'WR':>7}{'lift':>8}{'wlow':>8}"
          f"{'L n':>5}{'L WR':>7}{'S n':>5}{'S WR':>7}{'avg_pnl':>10}")
    print("=" * 120)
    for r in rows_out:
        verdict = "BUMP" if r["lift"] > 0.10 else ("CUT" if r["lift"] < -0.10 else "OK  ")
        print(f"{r['factor']:38}{r['n']:>5}{r['wins']:>5}"
              f"{r['wr']:>7.1%}{r['lift']:>+8.2%}{r['wilson_low']:>8.1%}"
              f"{r['long_n']:>5}{r['long_wr']:>7.1%}"
              f"{r['short_n']:>5}{r['short_wr']:>7.1%}"
              f"{r['avg_pnl']:>+10.2f}  {verdict}")

    # Persist report
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = report_dir / f"{today}_factor_edge.md"
    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"# Factor edge report — cohort {COHORT_CUTOFF} -> {today}\n\n")
        f.write(f"N={n_total}, baseline_wr={baseline_wr:.1%}\n\n")
        f.write("| factor | n | wins | WR | lift | wilson_low | L n | L WR | S n | S WR | avg_pnl | verdict |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for r in rows_out:
            verdict = "BUMP" if r["lift"] > 0.10 else ("CUT" if r["lift"] < -0.10 else "OK")
            f.write(f"| {r['factor']} | {r['n']} | {r['wins']} | "
                    f"{r['wr']:.1%} | {r['lift']:+.2%} | {r['wilson_low']:.1%} | "
                    f"{r['long_n']} | {r['long_wr']:.1%} | "
                    f"{r['short_n']} | {r['short_wr']:.1%} | "
                    f"{r['avg_pnl']:+.2f} | {verdict} |\n")
    print(f"\nReport written: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
