#!/usr/bin/env python3
"""daily_dashboard_telegram.py — wraps operator_dashboard.py + sends digest to Telegram.

Builds the dashboard MD report, then sends a compact Telegram message
with key metrics + alert flags. Designed for Windows Task Scheduler:
  daily @ 07:00 local → python scripts/daily_dashboard_telegram.py

Telegram message limits to ~4000 chars. Full report goes to file;
Telegram gets headlines + auto-recommendations only.

USAGE
  python scripts/daily_dashboard_telegram.py              # send to Telegram
  python scripts/daily_dashboard_telegram.py --dry-run    # print only
  python scripts/daily_dashboard_telegram.py --hours 168  # weekly window
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    for stream_name in ("stdout", "stderr"):
        s = getattr(sys, stream_name, None)
        if s and hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def build_dashboard(hours: int, cutoff: str) -> str:
    """Run operator_dashboard.py as subprocess, capture markdown output."""
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.exists() else sys.executable
    script = ROOT / "scripts" / "operator_dashboard.py"
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    r = subprocess.run(
        [py, str(script), "--hours", str(hours), "--cutoff", cutoff],
        capture_output=True, text=True, env=env, timeout=120,
        encoding="utf-8", errors="replace",
    )
    return r.stdout or ""


def compact_telegram(full_md: str) -> str:
    """Trim to Telegram-friendly digest. Keep section headers + first 3 lines
    each, plus the auto-recommendations section in full."""
    lines = full_md.splitlines()
    out: list[str] = []
    in_recs = False
    section_lines = 0
    for ln in lines:
        if ln.startswith("## "):
            in_recs = "Auto-recommendations" in ln
            section_lines = 0
            out.append(ln)
            continue
        if in_recs:
            out.append(ln)
            continue
        if ln.startswith("# "):
            out.append(ln)
            continue
        section_lines += 1
        # Keep first 6 lines per section (header + few rows)
        if section_lines <= 6:
            out.append(ln)
    text = "\n".join(out)
    # Truncate to safe Telegram limit
    if len(text) > 3800:
        text = text[:3700] + "\n\n_[truncated, see full file]_"
    return text


def send_telegram(text: str) -> None:
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"')
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN/CHAT_ID not set")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }, timeout=10)
    r.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--cutoff", default="2026-01-01")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    full = build_dashboard(hours=args.hours, cutoff=args.cutoff)
    if not full:
        print("[ERROR] Dashboard build returned empty.")
        return 1

    compact = compact_telegram(full)
    print(compact)

    if args.dry_run:
        print("\n[dry-run] Not sending.")
        return 0

    try:
        send_telegram(compact)
        print("\n[OK] Sent to Telegram.")
    except Exception as e:
        print(f"\n[ERROR] Telegram send failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
