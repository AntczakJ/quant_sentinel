"""
pattern_rolling_wr.py — Rolling 30-day vs all-time WR per pattern.

pattern_stats aggregates count/wins/losses ALL-TIME. That's brittle when
the regime shifts: a pattern that worked 3 months ago in trending markets
may fail in a squeeze. The toxic_pattern blocker (count>=20, WR<30%)
sees the all-time aggregate, which can mask current-regime behavior.

This script reports per-pattern:
  - all-time count, WR
  - rolling 30d count, WR
  - delta (current - all-time)
  - flag if delta < -10pp AND rolling_n >= 5 (regime drift warning)

USAGE
    .venv/Scripts/python.exe scripts/pattern_rolling_wr.py

Read-only against data/sentinel.db. Output to stdout + report file.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sentinel.db"


def main() -> int:
    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1

    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        # All-time per-pattern
        cur.execute("""
            SELECT pattern,
                   COUNT(*) as n,
                   SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
                   ROUND(100.0 * SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1) as wr
            FROM trades
            WHERE status IN ('WIN','LOSS')
            GROUP BY pattern
            ORDER BY n DESC
        """)
        all_time = {row[0]: {"n": row[1], "wins": row[2], "wr": row[3]} for row in cur.fetchall()}

        # Rolling 30d
        cur.execute("""
            SELECT pattern,
                   COUNT(*) as n,
                   SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) as wins,
                   ROUND(100.0 * SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) / NULLIF(COUNT(*),0), 1) as wr
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
            GROUP BY pattern
            ORDER BY n DESC
        """, (cutoff_30d,))
        rolling = {row[0]: {"n": row[1], "wins": row[2], "wr": row[3]} for row in cur.fetchall()}
    finally:
        con.close()

    if not all_time:
        print("No resolved trades.")
        return 0

    print(f"{'pattern':40}{'all_n':>7}{'all_WR':>8}{'30d_n':>7}{'30d_WR':>8}"
          f"{'delta':>8}  flag")
    print("-" * 90)

    drift_warnings = []
    for pat, at in all_time.items():
        roll = rolling.get(pat, {"n": 0, "wins": 0, "wr": None})
        delta = (roll["wr"] or 0) - (at["wr"] or 0) if (roll["n"] >= 1 and at["wr"] is not None) else None
        flag = ""
        if roll["n"] >= 5 and delta is not None and delta < -10:
            flag = "DRIFT_DOWN"
            drift_warnings.append((pat, at["n"], at["wr"], roll["n"], roll["wr"], delta))
        elif roll["n"] >= 5 and delta is not None and delta > 10:
            flag = "DRIFT_UP"
        roll_wr_str = f"{roll['wr']:.1f}%" if roll["wr"] is not None else "n/a"
        delta_str = f"{delta:+.1f}pp" if delta is not None else "n/a"
        print(f"{pat[:40]:40}{at['n']:>7}{at['wr'] or 0:>7.1f}%"
              f"{roll['n']:>7}{roll_wr_str:>8}{delta_str:>8}  {flag}")

    if drift_warnings:
        print()
        print("⚠️  DRIFT_DOWN warnings (rolling WR << all-time WR; n>=5):")
        for pat, all_n, all_wr, roll_n, roll_wr, delta in drift_warnings:
            print(f"  {pat}: all={all_n}@{all_wr:.0f}% vs 30d={roll_n}@{roll_wr:.0f}% (Δ{delta:+.0f}pp)")
        print("\nConsider: lowering pattern weight via update_pattern_weight, or")
        print("running scripts/apply_factor_weight_tuning.py based on these signals.")

    # Write report
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = report_dir / f"{today}_pattern_rolling.md"
    with report_path.open("w", encoding="utf-8") as f:
        f.write(f"# Pattern rolling 30d vs all-time WR — {today}\n\n")
        f.write("| pattern | all_n | all_WR | 30d_n | 30d_WR | delta | flag |\n")
        f.write("|---|---:|---:|---:|---:|---:|---|\n")
        for pat, at in all_time.items():
            roll = rolling.get(pat, {"n": 0, "wr": None})
            delta = (roll["wr"] or 0) - (at["wr"] or 0) if (roll["n"] >= 1 and at["wr"] is not None) else None
            flag = ""
            if roll["n"] >= 5 and delta is not None and delta < -10:
                flag = "DRIFT_DOWN"
            elif roll["n"] >= 5 and delta is not None and delta > 10:
                flag = "DRIFT_UP"
            roll_wr_str = f"{roll['wr']:.1f}%" if roll["wr"] is not None else "n/a"
            delta_str = f"{delta:+.1f}pp" if delta is not None else "n/a"
            f.write(f"| {pat} | {at['n']} | {at['wr']:.1f}% | {roll['n']} | "
                    f"{roll_wr_str} | {delta_str} | {flag} |\n")
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
