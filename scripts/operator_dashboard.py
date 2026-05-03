"""
operator_dashboard.py — single-command operator overview.

Runs all key analytics in sequence and produces ONE consolidated MD file
+ console summary. Designed for Janek's morning review.

Sections:
  1. API + scanner health snapshot
  2. Trade activity last 24h / 7d
  3. Per-pattern WR (live + backtest combined cohort)
  4. Factor edge (combined)
  5. Filter precision (top over-blockers)
  6. SHORT-XGB veto effectiveness (if data)
  7. Recommended actions (auto-derived)

USAGE
    .venv/Scripts/python.exe scripts/operator_dashboard.py
    .venv/Scripts/python.exe scripts/operator_dashboard.py --hours 168  # weekly
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[1]
SENTINEL_DB = REPO / "data" / "sentinel.db"
BACKTEST_DB = REPO / "data" / "backtest.db"
API_BASE = "http://127.0.0.1:8000"


def fetch_api(path: str, timeout: float = 5.0) -> dict | None:
    try:
        with urlopen(f"{API_BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def section_health(out) -> None:
    out.append("## 1. API + scanner health\n")
    h = fetch_api("/api/health")
    sh = fetch_api("/api/health/scanner")
    if not h:
        out.append("- ⚠️  API NOT REACHABLE\n")
        return
    out.append(f"- Status: {h.get('status')}\n")
    out.append(f"- Uptime: {h.get('uptime')}\n")
    out.append(f"- Models loaded: {h.get('models_loaded')}\n")
    if sh:
        out.append(f"- Scanner cycles: {sh.get('scans_total')}, errors: {sh.get('errors_total')}\n")
        out.append(f"- p95 cycle: {sh.get('p95_duration_ms', 0):.0f}ms\n")
    out.append("\n")


def section_trades(out, hours: int) -> None:
    out.append(f"## 2. Trade activity (last {hours}h)\n")
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute(
        "SELECT direction, status, profit FROM trades "
        "WHERE status IN ('WIN','LOSS') AND timestamp >= ?",
        (cutoff,)
    )
    rows = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    open_n = cur.fetchone()[0]
    con.close()
    if not rows:
        out.append(f"- No resolved trades in {hours}h.\n")
        out.append(f"- Open: {open_n}\n\n")
        return
    wins = sum(1 for r in rows if r[1] == "WIN")
    losses = sum(1 for r in rows if r[1] == "LOSS")
    pnl = sum(float(r[2] or 0) for r in rows)
    long_n = sum(1 for r in rows if r[0] == "LONG")
    short_n = sum(1 for r in rows if r[0] == "SHORT")
    wr = wins / (wins + losses) if (wins + losses) else 0
    out.append(f"- N: {len(rows)} ({long_n}L / {short_n}S)\n")
    out.append(f"- Wins: {wins} | Losses: {losses} | WR: {wr:.1%}\n")
    out.append(f"- PnL: ${pnl:+.2f}\n")
    out.append(f"- Open: {open_n}\n\n")


def section_combined_pattern_wr(out, cutoff: str) -> None:
    out.append("## 3. Pattern × Direction (combined live + backtest)\n")
    if not BACKTEST_DB.exists():
        # Live only
        con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
        con.execute(f"ATTACH DATABASE 'file:{BACKTEST_DB}?mode=ro' AS bt KEY ''")
    cur = con.cursor()
    if BACKTEST_DB.exists():
        cur.execute("""
            WITH all_t AS (
                SELECT pattern, direction, status FROM main.trades
                WHERE status IN ('WIN','LOSS') AND timestamp >= ?
                UNION ALL
                SELECT pattern, direction, status FROM bt.trades
                WHERE status IN ('WIN','LOSS') AND timestamp >= ?
            )
            SELECT pattern, direction,
                   COUNT(*) AS n,
                   SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) AS wins
            FROM all_t
            GROUP BY pattern, direction
            HAVING n >= 3
            ORDER BY n DESC
        """, (cutoff, cutoff))
    else:
        cur.execute("""
            SELECT pattern, direction,
                   COUNT(*) AS n,
                   SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) AS wins
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
            GROUP BY pattern, direction
            HAVING n >= 3
            ORDER BY n DESC
        """, (cutoff,))
    rows = cur.fetchall()
    con.close()
    if not rows:
        out.append("- No data.\n\n")
        return
    out.append("| pattern | dir | n | wins | WR |\n")
    out.append("|---|---|---:|---:|---:|\n")
    for pat, dr, n, wins in rows:
        wr = wins / n if n else 0
        flag = " 🚨" if wr < 0.20 and n >= 10 else (" ✅" if wr >= 0.40 and n >= 5 else "")
        out.append(f"| {pat} | {dr} | {n} | {wins} | {wr:.1%}{flag} |\n")
    out.append("\n")


def section_filter_precision(out) -> None:
    out.append("## 4. Top filter over-blockers (sentinel.db)\n")
    con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("""
        SELECT filter_name,
               SUM(CASE WHEN would_have_won IN (1,2) THEN 1 ELSE 0 END) AS wins_blocked,
               SUM(CASE WHEN would_have_won IN (0,3) THEN 1 ELSE 0 END) AS losses_saved
        FROM rejected_setups
        WHERE would_have_won IS NOT NULL
        GROUP BY filter_name
        HAVING wins_blocked + losses_saved >= 50
        ORDER BY wins_blocked DESC
    """)
    rows = cur.fetchall()
    con.close()
    out.append("| filter | wins_blocked | losses_saved | precision |\n")
    out.append("|---|---:|---:|---:|\n")
    for fn, wb, ls in rows[:10]:
        evald = wb + ls
        prec = ls / evald if evald else 0
        flag = " ⚠️" if prec < 0.65 and wb > 50 else ""
        out.append(f"| {fn} | {wb} | {ls} | {prec:.1%}{flag} |\n")
    out.append("\n")


def section_short_shadow(out, hours: int) -> None:
    out.append(f"## 5. SHORT-XGB shadow (post-restart, last {hours}h)\n")
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("""
        SELECT predictions_json FROM ml_predictions
        WHERE timestamp >= ? AND predictions_json IS NOT NULL
    """, (cutoff,))
    rows = cur.fetchall()
    con.close()
    if not rows:
        out.append(f"- No predictions data in {hours}h.\n\n")
        return
    short_ps = []
    for (raw,) in rows:
        try:
            d = json.loads(raw)
            sp = d.get("shadow_short_xgb")
            if sp is not None:
                short_ps.append(float(sp))
        except Exception:
            pass
    if not short_ps:
        out.append(f"- No shadow_short_xgb in {hours}h predictions.\n\n")
        return
    above_T = sum(1 for p in short_ps if p > 0.55)
    out.append(f"- Predictions persisted: {len(short_ps)}\n")
    out.append(f"- Mean short_p: {sum(short_ps)/len(short_ps):.3f}\n")
    out.append(f"- Above veto T=0.55: {above_T} ({above_T/len(short_ps)*100:.0f}%)\n\n")


def section_recommendations(out, cutoff: str) -> None:
    out.append("## 6. Auto-recommendations\n")
    recs = []
    # Check for patterns near toxic threshold
    con = sqlite3.connect(f"file:{SENTINEL_DB}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT pattern, count, wins FROM pattern_stats WHERE count >= 15 AND count < 25")
    for pat, cnt, wins in cur.fetchall():
        wr = wins / cnt
        if wr < 0.30:
            recs.append(f"⚠️  Pattern `{pat}` n={cnt} WR={wr:.0%} approaching toxic block")
    # Streak check
    cur.execute(
        "SELECT status FROM trades WHERE status IN ('WIN','LOSS') ORDER BY id DESC LIMIT 8"
    )
    statuses = [r[0] for r in cur.fetchall()]
    streak = 0
    for s in statuses:
        if s == "LOSS":
            streak += 1
        else:
            break
    if streak >= 4:
        recs.append(f"⚠️  Loss streak {streak} (auto-pause at 8)")
    con.close()
    if not recs:
        recs.append("✅ No urgent action items detected")
    for r in recs:
        out.append(f"- {r}\n")
    out.append("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--cutoff", default="2026-03-01")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out: list[str] = [f"# Operator Dashboard — {today}\n\n"]
    section_health(out)
    section_trades(out, args.hours)
    section_combined_pattern_wr(out, args.cutoff)
    section_filter_precision(out)
    section_short_shadow(out, args.hours)
    section_recommendations(out, args.cutoff)

    text = "".join(out)
    print(text)

    # Persist
    today_path = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_dir = REPO / "reports"
    report_dir.mkdir(exist_ok=True)
    path = report_dir / f"{today_path}_operator_dashboard.md"
    path.write_text(text, encoding="utf-8")
    print(f"\n[Report written: {path}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
