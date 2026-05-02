"""
grade_wr_analysis.py — empirical WR per setup_quality grade.

Setup quality grades (A+/A/B/C) are computed by smc_engine.score_setup_quality
based on factor confluence. The score-to-grade thresholds are different on
scalp vs HTF:
  Scalp (5m/15m/30m): A+>=65, A>=45, B>=25
  H1+:                A+>=75, A>=55, B>=40

This script reports actual WR per grade per direction per timeframe.
Helps decide:
  - Are grade thresholds correctly calibrated?
  - Is grade C ever profitable, or always-loss (justify auto-block)?
  - Direction-asymmetry per grade?

USAGE
    .venv/Scripts/python.exe scripts/grade_wr_analysis.py
"""
from __future__ import annotations

import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sentinel.db"
COHORT_CUTOFF = "2026-04-06"


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
            SELECT setup_grade, setup_score, direction, status, profit, pattern
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
        """, (COHORT_CUTOFF,))
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No resolved trades.")
        return 0

    # Aggregate by (grade, direction)
    grade_dir = {}
    grade_only = {}
    score_buckets = {  # score-bucket aggregation, independent of grade boundary
        "0-20":   {"n": 0, "wins": 0, "pnl": 0.0},
        "20-30":  {"n": 0, "wins": 0, "pnl": 0.0},
        "30-40":  {"n": 0, "wins": 0, "pnl": 0.0},
        "40-50":  {"n": 0, "wins": 0, "pnl": 0.0},
        "50-65":  {"n": 0, "wins": 0, "pnl": 0.0},
        "65-100": {"n": 0, "wins": 0, "pnl": 0.0},
    }

    def bucket(score):
        if score is None:
            return None
        if score < 20:
            return "0-20"
        if score < 30:
            return "20-30"
        if score < 40:
            return "30-40"
        if score < 50:
            return "40-50"
        if score < 65:
            return "50-65"
        return "65-100"

    for grade, score, direction, status, profit, pattern in rows:
        if not grade:
            grade = "?"
        e = grade_dir.setdefault((grade, direction), {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e["wins"] += 1
        e2 = grade_only.setdefault(grade, {"n": 0, "wins": 0, "pnl": 0.0})
        e2["n"] += 1
        e2["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e2["wins"] += 1
        b = bucket(score)
        if b:
            score_buckets[b]["n"] += 1
            score_buckets[b]["pnl"] += float(profit or 0.0)
            if status == "WIN":
                score_buckets[b]["wins"] += 1

    n_total = sum(e["n"] for e in grade_only.values())
    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}")
    print()
    print("=== Per-grade aggregate ===")
    print(f"{'grade':>8}{'n':>5}{'wins':>5}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    for grade in ["A+", "A", "B", "C", "?"]:
        if grade not in grade_only:
            continue
        e = grade_only[grade]
        wr = e["wins"] / e["n"] if e["n"] else 0
        wlow = wilson_lower(e["wins"], e["n"])
        avg_pnl = e["pnl"] / e["n"] if e["n"] else 0
        print(f"{grade:>8}{e['n']:>5}{e['wins']:>5}{wr:>7.1%}{wlow:>7.1%}{avg_pnl:>+10.2f}")

    print()
    print("=== Per-grade × direction ===")
    print(f"{'grade':>8}{'dir':>7}{'n':>5}{'wins':>5}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    for grade in ["A+", "A", "B", "C", "?"]:
        for direction in ["LONG", "SHORT"]:
            key = (grade, direction)
            if key not in grade_dir:
                continue
            e = grade_dir[key]
            wr = e["wins"] / e["n"] if e["n"] else 0
            wlow = wilson_lower(e["wins"], e["n"])
            avg_pnl = e["pnl"] / e["n"] if e["n"] else 0
            print(f"{grade:>8}{direction:>7}{e['n']:>5}{e['wins']:>5}"
                  f"{wr:>7.1%}{wlow:>7.1%}{avg_pnl:>+10.2f}")

    print()
    print("=== Per-score bucket (raw score, grade-independent) ===")
    print(f"{'bucket':>8}{'n':>5}{'wins':>5}{'WR':>7}{'wlow':>7}{'avg_pnl':>10}")
    for b in ["0-20", "20-30", "30-40", "40-50", "50-65", "65-100"]:
        e = score_buckets[b]
        if e["n"] == 0:
            continue
        wr = e["wins"] / e["n"] if e["n"] else 0
        wlow = wilson_lower(e["wins"], e["n"])
        avg_pnl = e["pnl"] / e["n"] if e["n"] else 0
        print(f"{b:>8}{e['n']:>5}{e['wins']:>5}{wr:>7.1%}{wlow:>7.1%}{avg_pnl:>+10.2f}")

    # Recommendation
    print()
    print("=== Verdict ===")
    if "C" in grade_only and grade_only["C"]["n"] >= 5:
        c = grade_only["C"]
        c_wr = c["wins"] / c["n"]
        if c_wr < 0.20:
            print(f"  [SUGGEST] Grade C WR={c_wr:.0%} (n={c['n']}) — consider auto-blocking")
        else:
            print(f"  Grade C WR={c_wr:.0%} (n={c['n']}) — borderline, no action")
    if "B" in grade_only and grade_only["B"]["n"] >= 5:
        b = grade_only["B"]
        b_wr = b["wins"] / b["n"]
        a_wr = grade_only.get("A", {"wins": 0, "n": 0}).get("wins", 0) / max(grade_only.get("A", {"n": 1})["n"], 1)
        if b_wr < a_wr - 0.10 and b_wr < 0.30:
            print(f"  [SUGGEST] Grade B WR={b_wr:.0%} (vs A {a_wr:.0%}) — consider tightening grade B threshold or adding ML filter")

    # Persist
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    path = report_dir / f"{today}_grade_wr.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Grade WR analysis — {today}\n\n")
        f.write(f"Cohort: {COHORT_CUTOFF} -> {today}, N={n_total}\n\n")
        f.write("## Per-grade aggregate\n\n")
        f.write("| grade | n | wins | WR | wilson_low | avg_pnl |\n")
        f.write("|---:|---:|---:|---:|---:|---:|\n")
        for g in ["A+", "A", "B", "C", "?"]:
            if g not in grade_only:
                continue
            e = grade_only[g]
            wr = e["wins"] / e["n"] if e["n"] else 0
            wlow = wilson_lower(e["wins"], e["n"])
            f.write(f"| {g} | {e['n']} | {e['wins']} | {wr:.1%} | {wlow:.1%} | {e['pnl']/max(e['n'],1):+.2f} |\n")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
