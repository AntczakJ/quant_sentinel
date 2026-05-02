"""
confluence_sweep.py — empirical confluence-count threshold sweep.

For each confluence_count (0,1,2,3,...) compute:
  - n trades that fired with that confluence
  - WR
  - cumulative if-we-required-X WR

Drives recommendation: should min_conf change from 1 (scalp) / 3 (HTF)?

Reads trades.factors (counted as confluence proxy when factor_count
column unavailable) and pattern (TF prefix gives scalp vs HTF).

USAGE
    .venv/Scripts/python.exe scripts/confluence_sweep.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sentinel.db"
COHORT_CUTOFF = "2026-04-06"


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
    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT pattern, direction, status, profit, factors
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
        """, (COHORT_CUTOFF,))
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No trades.")
        return 0

    # Compute confluence proxy as count of factors
    by_conf = {}
    for pattern, direction, status, profit, factors_raw in rows:
        is_scalp = bool(pattern and ("[M5]" in pattern or "[M15]" in pattern or "[M30]" in pattern))
        n_factors = 0
        if factors_raw:
            try:
                f = json.loads(factors_raw) if isinstance(factors_raw, str) else factors_raw
                n_factors = len(f) if isinstance(f, (list, dict)) else 0
            except Exception:
                n_factors = 0
        # Subtract penalty factors which inflate count without confluence quality
        # Use a heuristic: count items NOT containing "_penalty" or "toxic_combo"
        if isinstance(factors_raw, str):
            try:
                f = json.loads(factors_raw)
                if isinstance(f, dict):
                    n_factors = sum(1 for k in f.keys() if "_penalty" not in k and "toxic_combo" not in k)
                elif isinstance(f, list):
                    n_factors = sum(1 for k in f if "_penalty" not in str(k) and "toxic_combo" not in str(k))
            except Exception:
                pass

        key = (n_factors, "scalp" if is_scalp else "htf")
        e = by_conf.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e["wins"] += 1

    n_total = sum(e["n"] for e in by_conf.values())
    wins_total = sum(e["wins"] for e in by_conf.values())
    baseline = wins_total / n_total if n_total else 0
    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}, baseline_WR={baseline:.1%}\n")

    print(f"{'tf_class':>10}{'conf_count':>11}{'n':>5}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    for key in sorted(by_conf.keys()):
        n_f, tf_class = key
        e = by_conf[key]
        wr = e["wins"] / e["n"] if e["n"] else 0
        wlow = wilson_lower(e["wins"], e["n"])
        avg_pnl = e["pnl"] / e["n"] if e["n"] else 0
        print(f"{tf_class:>10}{n_f:>11}{e['n']:>5}{wr:>7.1%}{wlow:>7.1%}{avg_pnl:>+10.2f}")

    # Cumulative — if we required confluence >= X
    print("\n=== Cumulative — if we required confluence >= X (scalp-only) ===")
    print(f"{'min_conf':>10}{'n_kept':>8}{'wins':>5}{'WR':>7}{'avg_pnl':>10}")
    for min_c in range(0, 8):
        n_k = 0
        w_k = 0
        pnl_k = 0.0
        for (nf, tfc), e in by_conf.items():
            if tfc != "scalp" or nf < min_c:
                continue
            n_k += e["n"]
            w_k += e["wins"]
            pnl_k += e["pnl"]
        if n_k == 0:
            continue
        wr = w_k / n_k
        avg_pnl = pnl_k / n_k
        print(f"{min_c:>10}{n_k:>8}{w_k:>5}{wr:>7.1%}{avg_pnl:>+10.2f}")

    # Persist
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    path = report_dir / f"{today}_confluence_sweep.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Confluence sweep — {today}\n\n")
        f.write(f"Cohort: {COHORT_CUTOFF} -> {today}, N={n_total}\n")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
