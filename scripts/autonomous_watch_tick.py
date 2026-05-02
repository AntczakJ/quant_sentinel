"""
Autonomous monitoring tick — single execution.

Run from /loop every ~30 min. Appends one block to
reports/2026-04-30_2day_watch.md and prints GREEN/YELLOW/RED to stdout.

Read-only. No DB writes, no API restarts, no param changes.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "2026-04-30_2day_watch.md"
PAUSE_FLAG = ROOT / "data" / "SCANNER_PAUSED"
API = "http://127.0.0.1:8000"

GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"


def fetch(path: str, timeout: float = 5.0):
    try:
        with urlopen(f"{API}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return {"_error": str(e)}


def get_streak() -> int:
    """Read consecutive LOSS streak from sentinel.db trades table.

    Read-only — uses the same DB the API uses. We never write.
    """
    import sqlite3

    db_path = ROOT / "data" / "sentinel.db"
    if not db_path.exists():
        return 0
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT status FROM trades "
            "WHERE status IN ('WIN','LOSS') "
            "ORDER BY id DESC LIMIT 20"
        )
        rows = [r[0] for r in cur.fetchall()]
        streak = 0
        for s in rows:
            if s == "LOSS":
                streak += 1
            else:
                break
        return streak
    finally:
        con.close()


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    health = fetch("/api/health")
    scanner = fetch("/api/health/scanner")
    trades_resp = fetch("/api/analysis/trades?limit=10")
    paused = PAUSE_FLAG.exists()

    if isinstance(trades_resp, dict) and isinstance(trades_resp.get("trades"), list):
        trades_list = trades_resp["trades"]
    elif isinstance(trades_resp, list):
        trades_list = trades_resp
    else:
        trades_list = []

    open_trades = [t for t in trades_list if isinstance(t, dict) and t.get("status") == "OPEN"]
    last_resolved = next(
        (t for t in trades_list if isinstance(t, dict) and t.get("status") in ("WIN", "LOSS")),
        None,
    )

    try:
        streak = get_streak()
    except Exception as e:
        streak = -1
        streak_err = str(e)
    else:
        streak_err = None

    verdict = GREEN
    flags = []
    if "_error" in health or health.get("status") != "healthy":
        verdict = RED
        flags.append(f"api unhealthy: {health.get('_error') or health.get('status')}")
    if "_error" in scanner or scanner.get("errors_total", 0) > 0:
        verdict = RED if verdict != RED else verdict
        flags.append(f"scanner errors: {scanner.get('errors_total')}")
    if paused:
        verdict = RED
        flags.append("SCANNER_PAUSED flag exists")
    if streak >= 8:
        verdict = RED
        flags.append(f"loss streak {streak} (>=auto-pause)")
    elif streak >= 5:
        verdict = YELLOW if verdict == GREEN else verdict
        flags.append(f"loss streak {streak} (warning)")
    if len(open_trades) > 5:
        verdict = YELLOW if verdict == GREEN else verdict
        flags.append(f"open trades {len(open_trades)}")
    if scanner.get("last_run_seconds_ago", 0) and scanner["last_run_seconds_ago"] > 600:
        verdict = YELLOW if verdict == GREEN else verdict
        flags.append(f"last scan {scanner['last_run_seconds_ago']}s ago")

    open_summary = ", ".join(
        f"#{t.get('id')} {t.get('direction')}@{t.get('entry')}" for t in open_trades
    ) or "(none)"
    last_summary = (
        f"#{last_resolved.get('id')} {last_resolved.get('status')} {last_resolved.get('profit')} ({last_resolved.get('timestamp')})"
        if last_resolved else "(none)"
    )

    block = [
        f"## {now}  — {verdict}",
        "",
        f"- API: {health.get('status', 'ERR')} (uptime {health.get('uptime', '?')})",
        f"- Scanner: {scanner.get('scans_total', '?')} cycles, errors={scanner.get('errors_total', '?')}, p95={scanner.get('p95_duration_ms', '?')}ms, last={scanner.get('last_run_seconds_ago', '?')}s ago",
        f"- Pause flag: {'YES' if paused else 'no'}",
        f"- Loss streak: {streak}" + (f" (err: {streak_err})" if streak_err else ""),
        f"- Open trades: {open_summary}",
        f"- Last resolved: {last_summary}",
    ]
    if flags:
        block.append(f"- **Flags**: {', '.join(flags)}")
    block.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    if not REPORT.exists():
        REPORT.write_text(
            "# Autonomous 2-day watch (2026-04-30 → 2026-05-02)\n\n"
            "Appended every monitoring tick. Read top-down for narrative,\n"
            "bottom for latest snapshot.\n\n",
            encoding="utf-8",
        )
    with REPORT.open("a", encoding="utf-8") as f:
        f.write("\n".join(block) + "\n")

    print(f"[{verdict}] {now}")
    if flags:
        print("  Flags: " + "; ".join(flags))
    print(f"  Open: {open_summary}")
    print(f"  Streak: {streak}")
    return 0 if verdict == GREEN else (1 if verdict == YELLOW else 2)


if __name__ == "__main__":
    sys.exit(main())
