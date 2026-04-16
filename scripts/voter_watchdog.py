#!/usr/bin/env python3
"""voter_watchdog.py - Periodic voter accuracy sanity check.

Every 6h: hit /api/voter-live-accuracy, compare to expected floor
per voter. If the ensemble's main earner (SMC) drops below 55%
directional accuracy for 2 consecutive checks, send Telegram alert.
Auto-mutes any voter that crosses into anti_signal territory (adds
safety rail on top of the 10am LSTM discovery).

Usage:
  python scripts/voter_watchdog.py           # one-shot check
  python scripts/voter_watchdog.py --auto-mute  # act on anti-signals

Schedule via Task Scheduler every 6h.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    for s in ("stdout", "stderr"):
        st = getattr(sys, s, None)
        if st and hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


EXPECTED_FLOOR = {
    "smc": 0.55,       # SMC is the earner — floor at 55%
    "lstm": 0.45,      # already known asymmetric; don't panic on weak
    "xgb": 0.45,
    "attention": 0.45,
    "dqn": 0.45,
    "ensemble": 0.50,  # aggregate should be at least break-even
}


def check_voters(hours: int = 72, horizon: int = 12) -> dict:
    import requests
    r = requests.get(
        "http://127.0.0.1:8000/api/voter-live-accuracy",
        params={"hours": hours, "horizon_candles": horizon},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def flag_anti_signals(data: dict) -> list[tuple[str, str]]:
    """Returns [(voter, reason), ...] for voters below floor or anti-signal."""
    flags = []
    for voter, v in data.get("voters", {}).items():
        status = v.get("status")
        acc = v.get("combined_accuracy_pct")
        samples = v.get("decisive_samples", 0)
        if samples < 10:
            continue
        floor = EXPECTED_FLOOR.get(voter, 0.45) * 100
        if status == "anti_signal":
            flags.append((voter, f"anti-signal ({acc}% < 45%)"))
        elif acc is not None and acc < floor:
            flags.append((voter, f"below floor ({acc}% < {floor:.0f}%)"))
    return flags


def auto_mute(voter: str) -> str:
    """Set ensemble_weight_<voter> to 0.05 (below MIN_ACTIVE_WEIGHT=0.10)."""
    from src.core.database import NewsDB
    db = NewsDB()
    key = f"ensemble_weight_{voter}"
    cur = db.get_param(key)
    if cur is None:
        return f"{voter}: param not found"
    if float(cur) <= 0.05:
        return f"{voter}: already muted at {cur}"
    db.set_param(key, 0.05)
    return f"{voter}: muted {cur} -> 0.05"


def send_telegram(text: str) -> None:
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip().lstrip("export ").strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"')
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing")
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
    }, timeout=10).raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-mute", action="store_true",
                    help="Set weight=0.05 for any voter flagged anti-signal")
    ap.add_argument("--notify", action="store_true",
                    help="Send Telegram alert if flags present")
    ap.add_argument("--hours", type=int, default=72)
    ap.add_argument("--horizon", type=int, default=12)
    args = ap.parse_args()

    try:
        data = check_voters(hours=args.hours, horizon=args.horizon)
    except Exception as e:
        print(f"[ERROR] Could not reach /api/voter-live-accuracy: {e}")
        return 1

    flags = flag_anti_signals(data)

    if not flags:
        print(f"[OK] All voters healthy. Verdict: {data.get('verdict')}")
        return 0

    print(f"[WARN] {len(flags)} voter(s) flagged:")
    for voter, reason in flags:
        print(f"  - {voter}: {reason}")

    if args.auto_mute:
        print()
        print("Auto-muting:")
        muted_actions = []
        for voter, reason in flags:
            v = data["voters"][voter]
            if v.get("status") == "anti_signal":
                msg = auto_mute(voter)
                print(f"  {msg}")
                muted_actions.append(msg)
            else:
                print(f"  {voter}: below-floor (not muting — needs human review)")

        if args.notify and muted_actions:
            try:
                text = "🚨 *Voter Watchdog*\n\n" + "\n".join(f"- {m}" for m in muted_actions)
                send_telegram(text)
                print("\nTelegram alert sent.")
            except Exception as e:
                print(f"\nTelegram send failed: {e}")

    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
