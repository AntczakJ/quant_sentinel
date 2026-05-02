"""
hourly_edge_report.py — WR by hour-of-day to expose session-edge timing.

For each UTC hour, compute:
  - n_trades that fired
  - WR with Wilson 95% lower bound
  - LONG vs SHORT split
  - Lift over baseline

Drives the recommendation: which hours are systemically losing for our
strategy (block trades) vs which hours have edge (allow more aggressive
sizing).

USAGE
    .venv/Scripts/python.exe scripts/hourly_edge_report.py
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
            SELECT
                cast(strftime('%H', timestamp) as int) as hour,
                direction,
                status,
                profit
            FROM trades
            WHERE status IN ('WIN', 'LOSS') AND timestamp >= ?
        """, (COHORT_CUTOFF,))
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No trades in cohort.")
        return 0

    by_hour: dict[int, dict] = {}
    for hour, direction, status, profit in rows:
        h = by_hour.setdefault(hour, {"n": 0, "wins": 0,
                                       "long_n": 0, "long_wins": 0,
                                       "short_n": 0, "short_wins": 0,
                                       "pnl": 0.0})
        h["n"] += 1
        h["pnl"] += float(profit or 0.0)
        if status == "WIN":
            h["wins"] += 1
        if direction == "LONG":
            h["long_n"] += 1
            if status == "WIN":
                h["long_wins"] += 1
        else:
            h["short_n"] += 1
            if status == "WIN":
                h["short_wins"] += 1

    n_total = sum(h["n"] for h in by_hour.values())
    wins_total = sum(h["wins"] for h in by_hour.values())
    baseline_wr = wins_total / max(n_total, 1)

    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}, WR_baseline={baseline_wr:.1%}")
    print()
    print(f"{'h(UTC)':>7}  {'session':>10}  {'n':>4}  {'WR':>6}  {'wlow':>6}  "
          f"{'L n':>4}  {'L WR':>6}  {'S n':>4}  {'S WR':>6}  {'avg_pnl':>9}")
    print("-" * 90)

    def session_for_hour(h: int) -> str:
        if 0 <= h <= 6:
            return "asian"
        if 7 <= h <= 14:
            return "london"
        if 15 <= h <= 21:
            return "new_york"
        return "off_hours"

    for h in sorted(by_hour.keys()):
        d = by_hour[h]
        wr = d["wins"] / d["n"] if d["n"] else 0
        lift = wr - baseline_wr
        wlow = wilson_lower(d["wins"], d["n"])
        long_wr = (d["long_wins"] / d["long_n"]) if d["long_n"] else 0
        short_wr = (d["short_wins"] / d["short_n"]) if d["short_n"] else 0
        avg_pnl = d["pnl"] / d["n"] if d["n"] else 0
        sess = session_for_hour(h)
        flag = ""
        if d["n"] >= 5:
            if wr < 0.20 and lift < -0.05:
                flag = "  [BAD]"
            elif wr > 0.40 and lift > 0.10:
                flag = "  [GOOD]"
        print(f"{h:>7}  {sess:>10}  {d['n']:>4}  {wr:>6.1%}  {wlow:>6.1%}  "
              f"{d['long_n']:>4}  {long_wr:>6.1%}  {d['short_n']:>4}  {short_wr:>6.1%}  "
              f"{avg_pnl:>+9.2f}{flag}")

    # Persist report
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = report_dir / f"{today}_hourly_edge.md"
    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"# Hourly edge report — cohort {COHORT_CUTOFF} -> {today}\n\n")
        f.write(f"N={n_total}, baseline_wr={baseline_wr:.1%}\n\n")
        f.write("| hour (UTC) | session | n | WR | wlow | L n | L WR | S n | S WR | avg_pnl | flag |\n")
        f.write("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for h in sorted(by_hour.keys()):
            d = by_hour[h]
            wr = d["wins"] / d["n"] if d["n"] else 0
            wlow = wilson_lower(d["wins"], d["n"])
            long_wr = (d["long_wins"] / d["long_n"]) if d["long_n"] else 0
            short_wr = (d["short_wins"] / d["short_n"]) if d["short_n"] else 0
            avg_pnl = d["pnl"] / d["n"] if d["n"] else 0
            sess = session_for_hour(h)
            flag = ""
            if d["n"] >= 5 and wr < 0.20 and (wr - baseline_wr) < -0.05:
                flag = "BAD"
            elif d["n"] >= 5 and wr > 0.40 and (wr - baseline_wr) > 0.10:
                flag = "GOOD"
            f.write(f"| {h} | {sess} | {d['n']} | {wr:.1%} | {wlow:.1%} | "
                    f"{d['long_n']} | {long_wr:.1%} | {d['short_n']} | {short_wr:.1%} | "
                    f"{avg_pnl:+.2f} | {flag} |\n")
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
