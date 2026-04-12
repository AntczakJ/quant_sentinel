"""
src/ops/health_monitor.py — Periodic system health check with Telegram alerts.

Runs as a background task every 10 minutes. Detects:
  - Scanner stale (no run in > 15 min)
  - Scanner error rate > 10%
  - Data fetch failures spiking (>20/hour)
  - Model staleness (>14 days old)
  - Daily loss approaching hard limit (>3% warning, >5% = auto-halt already)

Sends ONE alert per issue with cooldown (won't spam every 10 min for same issue).
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Dict

from src.core.logger import logger


# Cooldown state — prevents alert spam
_last_alert: Dict[str, float] = {}
ALERT_COOLDOWN_SEC = 1800  # 30 min between same-type alerts


def _should_alert(key: str) -> bool:
    """True if >30 min since last alert of this type."""
    last = _last_alert.get(key, 0)
    if time.time() - last >= ALERT_COOLDOWN_SEC:
        _last_alert[key] = time.time()
        return True
    return False


def _send_alert(text: str) -> None:
    """Best-effort alert. Imports scanner's send_telegram_alert."""
    try:
        from src.trading.scanner import send_telegram_alert
        send_telegram_alert(text)
        logger.warning(f"[HEALTH ALERT] {text[:100]}")
    except Exception as e:
        logger.error(f"[HEALTH] Failed to send alert: {e}")


def check_once() -> Dict[str, str]:
    """Run all health checks once. Returns dict of {issue: severity}."""
    issues: Dict[str, str] = {}

    # 1. Scanner staleness
    try:
        from src.ops.metrics import scan_last_ts, scan_duration, scan_errors_total, data_fetch_failures
        now = time.time()
        last = scan_last_ts.value
        if last > 0:
            age_min = (now - last) / 60
            if age_min > 15:
                issues["scanner_stale"] = f"warning (last run {age_min:.0f}min ago)"
                if _should_alert("scanner_stale"):
                    _send_alert(
                        f"⚠️ *Scanner stale*\n"
                        f"No scan in {age_min:.0f} min (threshold: 15 min).\n"
                        f"Check API process + background tasks."
                    )

        # 2. Error rate
        if scan_duration.count > 20:
            err_rate = scan_errors_total.value / scan_duration.count
            if err_rate > 0.10:
                issues["scan_error_rate"] = f"warning ({err_rate:.0%} errors)"
                if _should_alert("scan_error_rate"):
                    _send_alert(
                        f"⚠️ *Scanner error rate high*\n"
                        f"{err_rate:.0%} of recent scans failed ({scan_errors_total.value}/{scan_duration.count}).\n"
                        f"Check logs for exceptions."
                    )

        # 3. Data fetch failures
        if data_fetch_failures.value > 20:
            issues["data_fetch_failures"] = f"warning ({data_fetch_failures.value} failures)"
            if _should_alert("data_fetch_failures"):
                _send_alert(
                    f"⚠️ *Data feed degraded*\n"
                    f"{data_fetch_failures.value} failed fetches (yfinance/twelve rate limits?).\n"
                    f"Using mock data — predictions unreliable."
                )
    except Exception as e:
        logger.debug(f"[HEALTH] metrics check failed: {e}")

    # 4. Model staleness
    try:
        for name in ("rl_agent", "lstm", "xgb", "attention"):
            path = f"models/{name}.keras" if name != "xgb" else "models/xgb.pkl"
            if not os.path.exists(path):
                continue
            age_days = (time.time() - os.path.getmtime(path)) / 86400
            if age_days > 14:
                key = f"model_stale_{name}"
                issues[key] = f"info ({age_days:.0f}d old)"
                if _should_alert(key):
                    _send_alert(
                        f"ℹ️ *Model stale: {name}*\n"
                        f"Last trained {age_days:.0f} days ago (threshold: 14d).\n"
                        f"Consider `python train_all.py` or `train_rl.py`."
                    )
    except Exception as e:
        logger.debug(f"[HEALTH] model check failed: {e}")

    # 5. Drawdown warning (soft — auto-halt at 5%)
    try:
        from src.trading.risk_manager import get_risk_manager
        from src.core.database import NewsDB
        rm = get_risk_manager()
        db = NewsDB()
        bal = float(db.get_param("portfolio_balance") or 10000)
        loss_pct = rm._get_daily_loss_pct(bal)
        if loss_pct >= 3.0:
            issues["drawdown_warning"] = f"warning (daily loss {loss_pct:.1f}%)"
            if _should_alert("drawdown_warning"):
                _send_alert(
                    f"⚠️ *Daily loss warning*\n"
                    f"Current daily loss: {loss_pct:.1f}%\n"
                    f"Auto-halt triggers at 5%. Review open positions."
                )
    except Exception as e:
        logger.debug(f"[HEALTH] drawdown check failed: {e}")

    return issues


async def health_monitor_task(context=None):
    """Run health checks every 10 minutes. Use as asyncio background task."""
    # Initial delay so metrics accumulate
    await asyncio.sleep(60)

    while True:
        try:
            issues = check_once()
            if issues:
                logger.info(f"[HEALTH] {len(issues)} issue(s): {list(issues.keys())}")
            else:
                logger.debug("[HEALTH] all checks passed")
        except asyncio.CancelledError:
            logger.info("[HEALTH] task cancelled")
            return
        except Exception as e:
            logger.error(f"[HEALTH] monitor failed: {e}")
        await asyncio.sleep(600)  # 10 min
