"""
filter_precision_report.py — empirical precision per scanner filter.

Each rejected_setups row has would_have_won label (computed by
walk-forward simulation). Per filter_name we compute:

  - n_rejections
  - n_LOSS_saved (would_have_won=0): correct blocks
  - n_WIN_blocked (would_have_won=1): false positives
  - precision = LOSS_saved / (LOSS_saved + WIN_blocked)
  - block-cost ratio: how many wins did we lose per loss saved

Drives recommendation: which filters are reliable (high precision)
vs over-blocking (low precision = costing wins).

USAGE
    .venv/Scripts/python.exe scripts/filter_precision_report.py
    .venv/Scripts/python.exe scripts/filter_precision_report.py --db data/backtest.db
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


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
    ap.add_argument("--db", default="data/sentinel.db",
                    help="SQLite DB path (default: data/sentinel.db; use "
                         "data/backtest.db for backtest cohort)")
    args = ap.parse_args()
    db_path = REPO / args.db if not Path(args.db).is_absolute() else Path(args.db)
    if not db_path.exists():
        print(f"ERR: DB miss {db_path}")
        return 1
    print(f"DB: {db_path}\n")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        # would_have_won encoding (per docs/strategy/2026-04-29_rsi_extreme_audit.md):
        #   1 = TP hit (WIN)
        #   2 = time_win (WIN on time-exit)
        #   0 = SL hit (LOSS)
        #   3 = time_loss (LOSS on time-exit)
        #   NULL = not yet evaluated by daily replay
        cur.execute("""
            SELECT filter_name,
                   direction,
                   COUNT(*) as n,
                   SUM(CASE WHEN would_have_won IN (1, 2) THEN 1 ELSE 0 END) as n_win,
                   SUM(CASE WHEN would_have_won IN (0, 3) THEN 1 ELSE 0 END) as n_loss,
                   SUM(CASE WHEN would_have_won IS NULL THEN 1 ELSE 0 END) as n_null
            FROM rejected_setups
            GROUP BY filter_name, direction
            HAVING n >= 5
            ORDER BY n DESC
        """)
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No rejection data.")
        return 0

    print("=== Filter precision per direction ===")
    print(f"{'filter':28}{'dir':>7}{'n':>7}{'evald':>7}"
          f"{'loss_sav':>10}{'win_blk':>9}{'precision':>11}{'cost_ratio':>12}")
    print("-" * 100)

    summary = []
    for filter_name, direction, n, n_win, n_loss, n_null in rows:
        evald = n - n_null
        if evald == 0:
            continue
        precision = n_loss / evald
        cost_ratio = n_win / max(n_loss, 1)  # wins blocked per loss saved
        summary.append({
            "filter": filter_name, "direction": direction,
            "n": n, "evald": evald, "n_win": n_win, "n_loss": n_loss,
            "precision": precision, "cost_ratio": cost_ratio,
        })

    # Sort by precision asc — worst filters first
    summary.sort(key=lambda r: r["precision"])
    for r in summary:
        flag = ""
        if r["precision"] < 0.70 and r["evald"] >= 50:
            flag = "OVER-BLOCK?"
        elif r["precision"] >= 0.95 and r["evald"] >= 50:
            flag = "EXCELLENT"
        print(f"{r['filter'][:28]:28}{r['direction']:>7}{r['n']:>7}{r['evald']:>7}"
              f"{r['n_loss']:>10}{r['n_win']:>9}{r['precision']:>11.1%}{r['cost_ratio']:>12.3f}  {flag}")

    # Overall aggregate
    print()
    print("=== Aggregate per filter (both directions combined) ===")
    print(f"{'filter':28}{'evald':>8}{'loss_sav':>10}{'win_blk':>9}{'precision':>11}")
    agg = {}
    for r in summary:
        e = agg.setdefault(r["filter"], {"evald": 0, "n_win": 0, "n_loss": 0})
        e["evald"] += r["evald"]
        e["n_win"] += r["n_win"]
        e["n_loss"] += r["n_loss"]
    for filter_name in sorted(agg.keys(), key=lambda f: agg[f]["evald"], reverse=True):
        e = agg[filter_name]
        if e["evald"] == 0:
            continue
        p = e["n_loss"] / e["evald"]
        flag = ""
        if p < 0.70 and e["evald"] >= 100:
            flag = "OVER-BLOCK"
        elif p >= 0.95 and e["evald"] >= 100:
            flag = "EXCELLENT"
        print(f"{filter_name[:28]:28}{e['evald']:>8}{e['n_loss']:>10}{e['n_win']:>9}{p:>11.1%}  {flag}")

    # Persist
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    db_tag = "backtest" if "backtest" in str(db_path) else "live"
    path = report_dir / f"{today}_filter_precision_{db_tag}.md"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"# Filter precision report — {today}\n\n")
        f.write("Per-filter analysis using would_have_won labels from rejected_setups.\n\n")
        f.write("| filter | direction | n | evald | loss_saved | win_blocked | precision | flag |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---|\n")
        for r in summary:
            flag = "OVER-BLOCK?" if r["precision"] < 0.70 and r["evald"] >= 50 else ("EXCELLENT" if r["precision"] >= 0.95 and r["evald"] >= 50 else "")
            f.write(f"| {r['filter']} | {r['direction']} | {r['n']} | {r['evald']} | "
                    f"{r['n_loss']} | {r['n_win']} | {r['precision']:.1%} | {flag} |\n")
    print(f"\nReport: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
