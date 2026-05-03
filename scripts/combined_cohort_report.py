"""
combined_cohort_report.py — UNION live + backtest cohorts for richer analytics.

Live trades (data/sentinel.db) + backtest trades (data/backtest.db) share
the same schema after the 2026-05-03 pattern-naming alignment fix.
Combining them gives a bigger N for factor/pattern WR analysis.

Tags each trade with `source` column:
  - 'live'     — data/sentinel.db trades
  - 'backtest' — data/backtest.db trades

Reports:
  - Pattern × direction × source WR
  - Factor edge across combined cohort
  - Per-source comparison (does backtest WR match live?)

USAGE
    .venv/Scripts/python.exe scripts/combined_cohort_report.py
    .venv/Scripts/python.exe scripts/combined_cohort_report.py --cutoff 2026-03-01
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SENTINEL_DB = REPO / "data" / "sentinel.db"
BACKTEST_DB = REPO / "data" / "backtest.db"


def wilson_lower(wins: int, n: int) -> float:
    if n == 0:
        return 0.0
    z = 1.96
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return max(0.0, center - margin)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="2026-03-01",
                    help="Trades from this date onwards (default 2026-03-01 to "
                         "include backtest period)")
    args = ap.parse_args()

    if not SENTINEL_DB.exists() or not BACKTEST_DB.exists():
        print(f"ERR: missing DB(s) — sentinel={SENTINEL_DB.exists()} backtest={BACKTEST_DB.exists()}")
        return 1

    # Open sentinel as primary, ATTACH backtest as 'bt'
    con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    con.execute(f"ATTACH DATABASE 'file:{BACKTEST_DB}?mode=ro' AS bt KEY ''")

    cur = con.cursor()
    # UNION query — tag each row with source
    cur.execute("""
        WITH unified AS (
            SELECT 'live' AS source, pattern, direction, status, profit, factors,
                   timestamp
            FROM main.trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
            UNION ALL
            SELECT 'backtest' AS source, pattern, direction, status, profit, factors,
                   timestamp
            FROM bt.trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
        )
        SELECT * FROM unified
    """, (args.cutoff, args.cutoff))
    rows = cur.fetchall()

    if not rows:
        print("No trades in either cohort.")
        return 0

    print(f"COHORT: {args.cutoff} -> present, total N={len(rows)}\n")

    # ===== Per-source breakdown =====
    src_totals = {}
    for row in rows:
        s = row[0]
        e = src_totals.setdefault(s, {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(row[4] or 0)
        if row[3] == "WIN":
            e["wins"] += 1
    print("=== Per-source ===")
    for s, e in src_totals.items():
        wr = e["wins"] / e["n"] if e["n"] else 0
        print(f"  {s:>10}: n={e['n']:>4}, wins={e['wins']}, WR={wr:.1%}, pnl={e['pnl']:+.2f}")
    print()

    # ===== Pattern × direction (combined) =====
    pat_dir = {}
    for row in rows:
        source, pattern, direction, status, profit, factors, ts = row
        key = (pattern, direction)
        e = pat_dir.setdefault(key, {"n": 0, "wins": 0, "live_n": 0, "bt_n": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0)
        if source == "live":
            e["live_n"] += 1
        else:
            e["bt_n"] += 1
        if status == "WIN":
            e["wins"] += 1

    print("=== Pattern x Direction (combined live+backtest, n>=3) ===")
    print(f"{'pattern':35}{'dir':>7}{'n':>4}{'wins':>5}{'WR':>7}{'wlow':>7}{'live':>5}{'bt':>5}{'avg_pnl':>10}")
    rows_pd = sorted(pat_dir.items(), key=lambda kv: -kv[1]["n"])
    for (pat, direction), e in rows_pd:
        if e["n"] < 3:
            continue
        wr = e["wins"] / e["n"]
        wlow = wilson_lower(e["wins"], e["n"])
        avg_pnl = e["pnl"] / e["n"]
        print(f"{pat[:35]:35}{direction:>7}{e['n']:>4}{e['wins']:>5}"
              f"{wr:>7.1%}{wlow:>7.1%}{e['live_n']:>5}{e['bt_n']:>5}{avg_pnl:>+10.2f}")
    print()

    # ===== Factor edge (combined) =====
    n_total = len(rows)
    wins_total = sum(1 for r in rows if r[3] == "WIN")
    baseline_wr = wins_total / n_total if n_total else 0
    factor_stats = {}
    for row in rows:
        _, _, direction, status, profit, factors_raw, _ = row
        if not factors_raw:
            continue
        try:
            factors = json.loads(factors_raw) if isinstance(factors_raw, str) else factors_raw
        except Exception:
            continue
        keys = list(factors.keys()) if isinstance(factors, dict) else (factors if isinstance(factors, list) else [])
        for f in keys:
            e = factor_stats.setdefault(str(f), {"n": 0, "wins": 0, "pnl": 0.0})
            e["n"] += 1
            e["pnl"] += float(profit or 0)
            if status == "WIN":
                e["wins"] += 1

    print(f"=== Factor edge (combined, baseline_WR={baseline_wr:.1%}) ===")
    print(f"{'factor':30}{'n':>4}{'wins':>5}{'WR':>7}{'lift':>8}{'wlow':>7}{'avg_pnl':>10}")
    rows_f = sorted(factor_stats.items(), key=lambda kv: kv[1]["wins"] / max(kv[1]["n"], 1) - baseline_wr, reverse=True)
    for f, e in rows_f:
        if e["n"] < 5:
            continue
        wr = e["wins"] / e["n"]
        lift = wr - baseline_wr
        wlow = wilson_lower(e["wins"], e["n"])
        verdict = "BUMP" if lift > 0.10 else ("CUT" if lift < -0.10 else "OK")
        print(f"{f[:30]:30}{e['n']:>4}{e['wins']:>5}{wr:>7.1%}{lift:>+8.2%}"
              f"{wlow:>7.1%}{e['pnl']/e['n']:>+10.2f}  {verdict}")

    # Persist
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = REPO / "reports" / f"{today}_combined_cohort.md"
    report.parent.mkdir(exist_ok=True)
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# Combined cohort report (live + backtest UNION) — {today}\n\n")
        f.write(f"Cutoff: {args.cutoff}, N={n_total}, baseline_WR={baseline_wr:.1%}\n\n")
        f.write("## Per-source\n\n")
        for s, e in src_totals.items():
            wr = e["wins"] / e["n"] if e["n"] else 0
            f.write(f"- **{s}**: n={e['n']}, wins={e['wins']}, WR={wr:.1%}, pnl={e['pnl']:+.2f}\n")
        f.write("\n## Pattern × Direction\n\n")
        f.write("| pattern | dir | n | wins | WR | wlow | live | bt | avg_pnl |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for (pat, dr), e in rows_pd:
            if e["n"] < 3:
                continue
            f.write(f"| {pat} | {dr} | {e['n']} | {e['wins']} | "
                    f"{e['wins']/e['n']:.1%} | {wilson_lower(e['wins'], e['n']):.1%} | "
                    f"{e['live_n']} | {e['bt_n']} | {e['pnl']/e['n']:+.2f} |\n")
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
