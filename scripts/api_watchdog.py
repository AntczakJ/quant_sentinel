#!/usr/bin/env python3
"""api_watchdog.py — External health watchdog for the quant_sentinel API.

Runs hourly via Task Scheduler. Unlike `src/ops/health_monitor.py` (which
runs INSIDE the API process), this runs outside — so if the API itself
dies, this still fires.

Checks:
  1. API reachable at /api/system-health
  2. Scanner fresh (last_rejection_age_sec < 900 == scanning every 5min)
  3. pnl_24h not deep red (abs < 3% of portfolio)
  4. No new ERROR/CRITICAL/Traceback in logs/api.log since last run
  5. Open trades not stuck (if any opened > 6h ago without close)

Sends Telegram alert only when an anomaly is detected. Tracks state in
data/api_watchdog_state.json to cooldown duplicate alerts (30 min) and
remember last log offset.

Usage:
  python scripts/api_watchdog.py           # dry-run, prints report
  python scripts/api_watchdog.py --notify  # send Telegram on anomaly
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if sys.platform == "win32":
    for s in ("stdout", "stderr"):
        st = getattr(sys, s, None)
        if st and hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


STATE_PATH = ROOT / "data" / "api_watchdog_state.json"
LOG_PATH = ROOT / "logs" / "api.log"
HEALTH_LOG = ROOT / "data" / "api_watchdog_log.jsonl"

API_BASE = "http://127.0.0.1:8000"
ALERT_COOLDOWN_SEC = 1800  # 30 min between same-key alerts

# Thresholds
SCANNER_STALE_SEC = 900       # 15 min (scan runs every 5 min)
PNL_24H_LOSS_PCT = 3.0         # alert if |loss| > 3% of balance
STUCK_TRADE_HOURS = 6
ERROR_PATTERN = re.compile(r"\b(CRITICAL|ERROR|Traceback)\b")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_alerts": {}, "log_offset": 0, "last_balance": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def should_alert(state: dict, key: str) -> bool:
    last = state["last_alerts"].get(key, 0)
    if time.time() - last >= ALERT_COOLDOWN_SEC:
        state["last_alerts"][key] = time.time()
        return True
    return False


def fetch_system_health() -> dict | None:
    import requests
    try:
        r = requests.get(f"{API_BASE}/api/system-health", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def scan_new_log_errors(state: dict) -> list[str]:
    """Return new ERROR/CRITICAL/Traceback lines since last scanned offset."""
    if not LOG_PATH.exists():
        return []
    try:
        size = LOG_PATH.stat().st_size
        offset = state.get("log_offset", 0)
        # Log rotated or truncated — reset
        if offset > size:
            offset = 0
        with LOG_PATH.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            errors = [ln.rstrip() for ln in f if ERROR_PATTERN.search(ln)]
            state["log_offset"] = f.tell()
        return errors[-20:]  # cap the sample
    except Exception as e:
        return [f"(watchdog log-scan failed: {e})"]


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
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    ).raise_for_status()


def append_snapshot(snapshot: dict) -> None:
    try:
        HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with HEALTH_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot) + "\n")
    except Exception:
        pass


def evaluate(health: dict | None, log_errors: list[str], state: dict) -> tuple[list[tuple[str, str]], dict]:
    """Return (alerts, snapshot). alerts is list of (key, message)."""
    alerts: list[tuple[str, str]] = []
    snap: dict = {"ts": datetime.now(timezone.utc).isoformat()}

    if health is None:
        alerts.append(("api_down", "🚨 *API unreachable* — `/api/system-health` failed"))
        snap["api_reachable"] = False
        return alerts, snap

    snap["api_reachable"] = True
    snap["overall"] = health.get("overall")
    snap["balance"] = health.get("portfolio_balance")
    snap["pnl_24h"] = (health.get("trades") or {}).get("pnl_24h")
    snap["trades_24h"] = (health.get("trades") or {}).get("trades_24h")
    snap["open_trades"] = (health.get("trades") or {}).get("open")
    snap["last_rejection_age"] = (health.get("scanner") or {}).get("last_rejection_age_sec")
    snap["drift_alerts"] = (health.get("drift_alerts") or {}).get("alert")
    snap["issues"] = health.get("issues", [])

    # 1. Scanner freshness
    age = snap["last_rejection_age"]
    if age is not None and age > SCANNER_STALE_SEC:
        alerts.append((
            "scanner_stale",
            f"⚠️ *Scanner stale* — no scan in {age/60:.0f} min (threshold {SCANNER_STALE_SEC/60:.0f})",
        ))

    # 2. Daily PnL drawdown
    pnl = snap["pnl_24h"]
    bal = snap["balance"]
    if pnl is not None and bal and bal > 0:
        loss_pct = (pnl / bal) * 100
        if loss_pct <= -PNL_24H_LOSS_PCT:
            alerts.append((
                "pnl_24h_loss",
                f"🚨 *24h loss {loss_pct:.1f}%* — PnL ${pnl:.2f} on balance ${bal:.0f}",
            ))

    # 3. Balance drop vs last check
    last_bal = state.get("last_balance")
    if last_bal and bal and bal > 0:
        drop_pct = ((bal - last_bal) / last_bal) * 100
        if drop_pct <= -2.0:  # 2% hourly drop
            alerts.append((
                "balance_drop",
                f"⚠️ *Balance drop {drop_pct:.1f}%* since last check — "
                f"${last_bal:.0f} → ${bal:.0f}",
            ))
    if bal:
        state["last_balance"] = bal

    # 4. Log errors since last run
    if log_errors:
        sample = "\n".join(f"`{ln[:120]}`" for ln in log_errors[:5])
        alerts.append((
            "log_errors",
            f"⚠️ *{len(log_errors)} new error line(s)* in api.log:\n{sample}",
        ))

    # 5. Stuck open trades
    open_detail = (health.get("trades") or {}).get("open_detail") or []
    stuck = []
    for t in open_detail:
        ts = t.get("timestamp")
        if not ts:
            continue
        try:
            opened = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
            if age_h > STUCK_TRADE_HOURS:
                stuck.append(f"#{t.get('id')} {t.get('direction')} age {age_h:.1f}h")
        except Exception:
            continue
    if stuck:
        alerts.append((
            "stuck_trade",
            f"⚠️ *Stuck open trade(s)*: {', '.join(stuck)} — max-hold is 4h",
        ))

    return alerts, snap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", action="store_true",
                    help="Send Telegram alert if any anomaly is detected")
    args = ap.parse_args()

    state = load_state()
    health = fetch_system_health()
    log_errors = scan_new_log_errors(state)
    alerts, snap = evaluate(health, log_errors, state)
    snap["n_alerts"] = len(alerts)
    append_snapshot(snap)

    if not alerts:
        print(f"[OK] {snap['ts']} — api={snap.get('api_reachable')} "
              f"bal=${snap.get('balance')} pnl24h=${snap.get('pnl_24h')} "
              f"open={snap.get('open_trades')} issues={len(snap.get('issues') or [])}")
        save_state(state)
        return 0

    # Alert section
    print(f"[ALERT] {len(alerts)} issue(s):")
    fire = []
    for key, msg in alerts:
        print(f"  - {key}: {msg.splitlines()[0]}")
        if should_alert(state, key):
            fire.append(msg)

    if args.notify and fire:
        header = f"🔔 *API Watchdog* ({snap['ts'][:16]}Z)\n\n"
        body = "\n\n".join(fire)
        footer = (f"\n\n_bal ${snap.get('balance')} · pnl24h ${snap.get('pnl_24h')} · "
                  f"open {snap.get('open_trades')}_")
        try:
            send_telegram(header + body + footer)
            print("[OK] Telegram alert sent")
        except Exception as e:
            print(f"[ERROR] Telegram failed: {e}")

    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
