"""
multi_dim_wr.py — multi-dimensional WR analytics for forward tuning.

Combines several analyses in one report:

1. Per-pattern × direction WR (full granular)
2. Per-pattern × factor presence WR (which factors HELP each pattern?)
3. Macro regime × pattern WR (does regime change pattern outcome?)
4. Vol regime × direction WR (does vol_regime align with direction edge?)

USAGE
    .venv/Scripts/python.exe scripts/multi_dim_wr.py

Read-only against data/sentinel.db.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
import argparse as _argparse
_ap = _argparse.ArgumentParser()
_ap.add_argument("--db", default="data/sentinel.db")
_ap.add_argument("--cutoff", default="2026-04-06")
_args, _ = _ap.parse_known_args()
DB = REPO / _args.db if not Path(_args.db).is_absolute() else Path(_args.db)
COHORT_CUTOFF = _args.cutoff


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
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
        cur.execute("""
            SELECT pattern, direction, status, profit, factors, vol_regime, model_agreement
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
        """, (COHORT_CUTOFF,))
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No resolved trades.")
        return 0

    n_total = len(rows)
    wins_total = sum(1 for r in rows if r[2] == "WIN")
    baseline = wins_total / n_total if n_total else 0
    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}, baseline_WR={baseline:.1%}\n")

    # ===== 1. Per-pattern × direction =====
    pat_dir = {}
    for pattern, direction, status, profit, _, _, _ in rows:
        e = pat_dir.setdefault((pattern, direction), {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e["wins"] += 1

    print("=== 1. Pattern × Direction (n>=2) ===")
    print(f"{'pattern':40}{'dir':>7}{'n':>4}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    pat_dir_list = sorted(pat_dir.items(), key=lambda kv: -kv[1]["n"])
    for (pat, direction), e in pat_dir_list:
        if e["n"] < 2:
            continue
        wr = e["wins"] / e["n"]
        print(f"{pat[:40]:40}{direction:>7}{e['n']:>4}"
              f"{wr:>7.1%}{wilson_lower(e['wins'], e['n']):>7.1%}"
              f"{e['pnl']/e['n']:>+10.2f}")

    # ===== 2. Per-pattern × factor =====
    print("\n=== 2. Top patterns × factor presence (n>=5 per pattern) ===")
    pattern_counts = {}
    for pattern, _, _, _, _, _, _ in rows:
        pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
    top_patterns = [p for p, n in pattern_counts.items() if n >= 5]
    for pat in top_patterns:
        print(f"\n  Pattern: {pat}")
        # Factor breakdown for this pattern
        factor_in_pat = {}
        n_pat = 0
        wins_pat = 0
        for pattern, direction, status, profit, factors_raw, _, _ in rows:
            if pattern != pat:
                continue
            n_pat += 1
            if status == "WIN":
                wins_pat += 1
            if not factors_raw:
                continue
            try:
                factors = json.loads(factors_raw) if isinstance(factors_raw, str) else factors_raw
            except Exception:
                continue
            keys = list(factors.keys()) if isinstance(factors, dict) else (factors if isinstance(factors, list) else [])
            for f in keys:
                e = factor_in_pat.setdefault(str(f), {"n": 0, "wins": 0})
                e["n"] += 1
                if status == "WIN":
                    e["wins"] += 1
        pat_wr = wins_pat / n_pat if n_pat else 0
        print(f"    pattern WR: {pat_wr:.1%} (n={n_pat})")
        print(f"    {'factor':30}{'n':>4}{'wins':>5}{'WR':>7}{'lift':>8}")
        for f, e in sorted(factor_in_pat.items(), key=lambda kv: -kv[1]["n"]):
            if e["n"] < 3:
                continue
            wr = e["wins"] / e["n"]
            lift = wr - pat_wr
            print(f"    {f[:30]:30}{e['n']:>4}{e['wins']:>5}{wr:>7.1%}{lift:>+8.2%}")

    # ===== 3. Vol regime × direction =====
    print("\n=== 3. Vol regime × direction ===")
    print(f"{'vol_regime':>10}{'dir':>7}{'n':>4}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    vol_dir = {}
    for _, direction, status, profit, _, vol_regime, _ in rows:
        vol_regime = vol_regime or "?"
        e = vol_dir.setdefault((vol_regime, direction), {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e["wins"] += 1
    for (regime, direction), e in sorted(vol_dir.items(), key=lambda kv: -kv[1]["n"]):
        if e["n"] < 2:
            continue
        wr = e["wins"] / e["n"]
        print(f"{regime:>10}{direction:>7}{e['n']:>4}{wr:>7.1%}"
              f"{wilson_lower(e['wins'], e['n']):>7.1%}{e['pnl']/e['n']:>+10.2f}")

    # ===== 4. Macro regime × pattern (extracted from confirmation_data or other) =====
    # Requires reading macro_snapshots table joined by timestamp — defer if not
    # populated. Most cohort lacks macro snapshots, so this section is best-
    # effort only.
    print("\n=== 4. macro_snapshots × pattern (best-effort) ===")
    con2 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur2 = con2.cursor()
        cur2.execute("""
            SELECT t.pattern, t.direction, t.status, m.macro_regime
            FROM trades t
            LEFT JOIN macro_snapshots m
              ON datetime(m.timestamp) BETWEEN datetime(t.timestamp, '-30 minutes')
                                            AND datetime(t.timestamp, '+5 minutes')
            WHERE t.status IN ('WIN','LOSS') AND t.timestamp >= ?
        """, (COHORT_CUTOFF,))
        macro_rows = cur2.fetchall()
    finally:
        con2.close()

    macro_pat = {}
    for pattern, direction, status, regime in macro_rows:
        regime = regime or "(no_snap)"
        e = macro_pat.setdefault((regime, pattern), {"n": 0, "wins": 0})
        e["n"] += 1
        if status == "WIN":
            e["wins"] += 1

    has_macro = sum(1 for _, _, _, regime in macro_rows if regime is not None)
    print(f"  Trades with macro snapshot match: {has_macro}/{len(macro_rows)}")
    print(f"{'regime':>12}{'pattern':30}{'n':>4}{'WR':>7}")
    for (regime, pat), e in sorted(macro_pat.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        if e["n"] < 2:
            continue
        wr = e["wins"] / e["n"]
        print(f"{regime:>12}{pat[:30]:30}{e['n']:>4}{wr:>7.1%}")

    # Persist consolidated report
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    path = report_dir / f"{today}_multi_dim_wr.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Multi-dimensional WR analytics — {today}\n\n")
        f.write(f"Cohort: {COHORT_CUTOFF} -> {today}, N={n_total}, baseline_WR={baseline:.1%}\n\n")
        f.write("Per-pattern × direction split saved per stdout above.\n")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
