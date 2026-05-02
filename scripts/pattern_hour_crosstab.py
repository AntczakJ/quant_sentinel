"""
pattern_hour_crosstab.py — pattern × hour-of-day cross-tabulated WR.

Combines pattern_rolling_wr.py + hourly_edge_report.py into a single
2D heatmap-style table. Drives time-of-day pattern blocking decisions:
  "block [M5] Trend Bull + FVG when hour in [4,7,8,9,10]"
  "allow [M5] Trend Bear + FVG always"

USAGE
    .venv/Scripts/python.exe scripts/pattern_hour_crosstab.py
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


def main() -> int:
    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT pattern,
                   cast(strftime('%H', timestamp) as int) as hour,
                   status,
                   profit
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
        """, (COHORT_CUTOFF,))
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No trades.")
        return 0

    # Aggregate
    pat_hour = {}
    pat_n = {}
    for pattern, hour, status, profit in rows:
        e = pat_hour.setdefault((pattern, hour), {"n": 0, "wins": 0, "pnl": 0.0})
        e["n"] += 1
        e["pnl"] += float(profit or 0.0)
        if status == "WIN":
            e["wins"] += 1
        pat_n[pattern] = pat_n.get(pattern, 0) + 1

    n_total = sum(e["n"] for e in pat_hour.values())
    print(f"COHORT: {COHORT_CUTOFF} -> present, N={n_total}\n")

    # Top patterns (n>=5)
    top_patterns = sorted([p for p, n in pat_n.items() if n >= 5],
                          key=lambda p: -pat_n[p])

    if not top_patterns:
        print("No patterns with n>=5.")
        return 0

    print("=== Pattern × Hour heatmap (n_trades / WR%) ===")
    print(f"  hour: " + "".join(f"{h:>5}" for h in range(0, 24)))
    for pat in top_patterns:
        row_str = f"{pat[:35]:35}"
        for h in range(0, 24):
            e = pat_hour.get((pat, h))
            if e is None or e["n"] == 0:
                row_str += f"{'.':>5}"
            else:
                wr = e["wins"] / e["n"]
                # Combo: "n/wr" in 5 chars
                cell = f"{e['n']}/{int(wr*100)}"
                row_str += f"{cell:>5}"
        print(row_str)

    # Hot spots — pattern × hour with n>=3 AND extreme WR
    print("\n=== Hot spots (n>=3 AND WR extreme) ===")
    hot = []
    for (pat, hour), e in pat_hour.items():
        if e["n"] < 3:
            continue
        wr = e["wins"] / e["n"]
        if wr == 0.0 or wr >= 0.50:
            hot.append((pat, hour, e["n"], e["wins"], wr, e["pnl"]))
    hot.sort(key=lambda x: (-x[2], x[4]))
    for pat, hour, n, wins, wr, pnl in hot:
        flag = "BLOCK" if wr == 0 and n >= 3 else "GOOD" if wr >= 0.50 else ""
        print(f"  {pat[:30]:30} h={hour:>2}  n={n:>2} wins={wins} WR={wr:.0%} pnl={pnl:+.2f}  {flag}")

    # Persist
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    path = report_dir / f"{today}_pattern_hour.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Pattern × Hour cross-tab — {today}\n\n")
        f.write(f"Cohort: {COHORT_CUTOFF} -> {today}, N={n_total}\n\n")
        f.write("Hot spots (n>=3, WR extreme):\n\n")
        f.write("| pattern | hour | n | wins | WR | pnl | flag |\n")
        f.write("|---|---:|---:|---:|---:|---:|---|\n")
        for pat, hour, n, wins, wr, pnl in hot:
            flag = "BLOCK" if wr == 0 and n >= 3 else "GOOD" if wr >= 0.50 else ""
            f.write(f"| {pat} | {hour} | {n} | {wins} | {wr:.0%} | {pnl:+.2f} | {flag} |\n")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
