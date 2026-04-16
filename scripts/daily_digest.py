#!/usr/bin/env python3
"""daily_digest.py - Morning summary via Telegram.

Runs once per day (typically at start of trading session). Sends a
compact digest of the previous 24h: PnL, trades closed, top voter,
any red-flag alerts (LSTM anti-signal, drift, ghost positions).

Usage:
  python scripts/daily_digest.py              # send to default chat
  python scripts/daily_digest.py --dry-run    # print to stdout only
  python scripts/daily_digest.py --hours 48   # window override

Schedule via Windows Task Scheduler or cron:
  daily @ 08:00 local → python scripts/daily_digest.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Windows console encoding: emoji in digest text breaks default cp1252 stdout.
if sys.platform == "win32":
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def build_digest(hours: int = 24) -> str:
    """Assemble the digest text. Returns multi-line markdown."""
    from src.core.database import NewsDB

    db = NewsDB()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    # --- PnL + trades ---
    pnl_row = db._query_one(
        "SELECT COALESCE(SUM(profit), 0), COUNT(*) FROM trades "
        "WHERE status IN ('WIN','LOSS','PROFIT') AND profit IS NOT NULL "
        "AND timestamp >= ?",
        (cutoff,),
    )
    pnl, n_closed = float(pnl_row[0] or 0), int(pnl_row[1] or 0)

    win_row = db._query_one(
        "SELECT COUNT(*) FROM trades WHERE status='WIN' AND timestamp >= ?",
        (cutoff,),
    )
    loss_row = db._query_one(
        "SELECT COUNT(*) FROM trades WHERE status='LOSS' AND timestamp >= ?",
        (cutoff,),
    )
    wins, losses = int(win_row[0] or 0), int(loss_row[0] or 0)
    win_rate = f"{wins / max(1, wins + losses) * 100:.0f}%" if (wins + losses) else "—"

    open_rows = db._query("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    n_open = int(open_rows[0][0] or 0) if open_rows else 0

    # --- Portfolio state ---
    balance = float(db.get_param("portfolio_balance") or 10000)

    # --- Scanner activity ---
    scan_row = db._query_one(
        "SELECT COUNT(*) FROM rejected_setups WHERE timestamp >= ?",
        (cutoff,),
    )
    n_rejected = int(scan_row[0] or 0) if scan_row else 0
    sig_row = db._query_one(
        "SELECT COUNT(*) FROM scanner_signals WHERE timestamp >= ?",
        (cutoff,),
    )
    n_signals = int(sig_row[0] or 0) if sig_row else 0

    # --- Drift alerts ---
    alert_row = db._query_one(
        "SELECT COUNT(*) FROM model_alerts WHERE resolved = 0"
    )
    n_alerts = int(alert_row[0] or 0) if alert_row else 0

    # --- Verdict ---
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    pnl_icon = "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")

    lines = [
        f"📊 *Quant Sentinel Digest — {hours}h*",
        "",
        f"{pnl_icon} *PnL*: {pnl_str} · {n_closed} closed · {wins}W / {losses}L · WR {win_rate}",
        f"📈 Balance: ${balance:,.0f} · {n_open} open",
        f"🔎 Scanner: {n_signals} signals · {n_rejected} rejections",
        f"⚠️ Unresolved alerts: {n_alerts}",
    ]

    # Red flags
    flags = []
    if pnl < -balance * 0.02:
        flags.append(f"PnL drawdown > 2% ({pnl_str})")
    if n_alerts > 20:
        flags.append(f"{n_alerts} drift alerts")
    if n_signals == 0 and n_rejected < 50:
        flags.append("scanner quiet")
    if n_open > 5:
        flags.append(f"{n_open} open positions (heat risk)")

    if flags:
        lines.append("")
        lines.append("🚩 *Flags:* " + "; ".join(flags))

    return "\n".join(lines)


def send_telegram(text: str) -> None:
    """Send via Telegram bot."""
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        # Try .env
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip().lstrip("export ").strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"')
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

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
    ap.add_argument("--dry-run", action="store_true", help="Print only, don't send")
    args = ap.parse_args()

    text = build_digest(hours=args.hours)
    print(text)

    if args.dry_run:
        print("\n[dry-run] Not sending.")
        return 0

    try:
        send_telegram(text)
        print("\n[OK] Sent to Telegram.")
    except Exception as e:
        print(f"\n[ERROR] Send failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
