"""
src/monitoring.py — Production Monitoring & Alerting Service

Periodic checks and Telegram alerts for:
  - Daily P&L summary (end of each trading day)
  - Circuit breaker triggers (immediate)
  - Model drift detection (daily)
  - System health (every 5 minutes)
  - Trade execution quality (per trade)

Designed to run as background task alongside the scanner.
"""

import datetime
import requests
from typing import Optional, Dict, List
from src.logger import logger
from src.config import TOKEN, CHAT_ID


# ═══════════════════════════════════════════════════════════════════════════
#  TELEGRAM ALERT (reusable, formatted)
# ═══════════════════════════════════════════════════════════════════════════

def _send_alert(text: str, silent: bool = False):
    """Send formatted alert to Telegram."""
    if not TOKEN or not CHAT_ID:
        logger.debug("[MONITOR] Telegram not configured — alert skipped")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown",
                  "disable_notification": silent},
            timeout=10,
        )
    except (requests.RequestException, Exception) as e:
        logger.debug(f"[MONITOR] Telegram send failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  DAILY P&L SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

def send_daily_summary():
    """
    Generate and send daily P&L summary to Telegram.
    Call at end of trading day (e.g., 22:00 CET Friday, or daily at 23:00).
    """
    try:
        from src.database import NewsDB
        db = NewsDB()

        today = datetime.date.today().isoformat()

        # Today's trades
        trades = db._query(
            "SELECT direction, status, profit, setup_grade FROM trades "
            "WHERE DATE(timestamp) = ? AND status IN ('WIN', 'LOSS')",
            (today,)
        )

        if not trades:
            _send_alert(f"*DAILY SUMMARY* ({today})\n\nNo trades today.", silent=True)
            return

        wins = sum(1 for t in trades if t[1] == 'WIN')
        losses = sum(1 for t in trades if t[1] == 'LOSS')
        total = wins + losses
        wr = wins / total * 100 if total > 0 else 0
        total_pnl = sum(float(t[2] or 0) for t in trades)
        avg_pnl = total_pnl / total if total > 0 else 0

        # Grade breakdown
        grades = {}
        for t in trades:
            g = t[3] or 'Unknown'
            if g not in grades:
                grades[g] = {'w': 0, 'l': 0}
            if t[1] == 'WIN':
                grades[g]['w'] += 1
            else:
                grades[g]['l'] += 1

        grade_str = ""
        for g, stats in sorted(grades.items()):
            grade_str += f"\n  {g}: {stats['w']}W/{stats['l']}L"

        # Portfolio balance
        try:
            bal = float(db.get_param("portfolio_balance", 0))
            bal_str = f"\nBalance: `${bal:,.2f}`"
        except (TypeError, ValueError):
            bal_str = ""

        # Risk manager status
        risk_str = ""
        try:
            from src.risk_manager import get_risk_manager
            rm = get_risk_manager()
            status = rm.get_status()
            if status.get('halted'):
                risk_str = f"\n*HALTED: {status.get('halt_reason', '?')}*"
            risk_str += f"\nKelly risk: {status.get('kelly_risk_pct', 0):.1f}%"
        except (ImportError, AttributeError):
            pass

        pnl_emoji = "+" if total_pnl >= 0 else ""
        wr_emoji = "🟢" if wr >= 50 else "🟡" if wr >= 35 else "🔴"

        msg = (
            f"*DAILY SUMMARY* ({today})\n"
            f"━━━━━━━━━━━━━━\n"
            f"{wr_emoji} Win rate: `{wr:.0f}%` ({wins}W/{losses}L)\n"
            f"P&L: `{pnl_emoji}{total_pnl:.2f}$` (avg {pnl_emoji}{avg_pnl:.2f}$)\n"
            f"Grades: {grade_str}\n"
            f"{bal_str}{risk_str}"
        )

        _send_alert(msg)
        logger.info(f"[MONITOR] Daily summary sent: {wins}W/{losses}L, PnL={total_pnl:+.2f}")

    except (ImportError, AttributeError, TypeError) as e:
        logger.warning(f"[MONITOR] Daily summary failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER ALERT
# ═══════════════════════════════════════════════════════════════════════════

def alert_circuit_breaker(reason: str):
    """Immediate alert when circuit breaker triggers."""
    msg = (
        f"*CIRCUIT BREAKER*\n"
        f"━━━━━━━━━━━━━━\n"
        f"{reason}\n"
        f"\nTrading halted. Resume via API or restart."
    )
    _send_alert(msg)
    logger.warning(f"[MONITOR] Circuit breaker alert: {reason}")


# ═══════════════════════════════════════════════════════════════════════════
#  MODEL DRIFT ALERT
# ═══════════════════════════════════════════════════════════════════════════

def check_and_alert_drift():
    """Run drift detection and alert if thresholds breached."""
    try:
        from src.model_monitor import run_drift_check
        alerts = run_drift_check()

        if alerts:
            msg = (
                f"*MODEL DRIFT DETECTED*\n"
                f"━━━━━━━━━━━━━━\n"
                + "\n".join(f"- {a}" for a in alerts)
                + "\n\nConsider retraining models."
            )
            _send_alert(msg)
            logger.warning(f"[MONITOR] Drift alerts: {len(alerts)}")
        else:
            logger.info("[MONITOR] Drift check: all models healthy")

    except (ImportError, AttributeError) as e:
        logger.debug(f"[MONITOR] Drift check skipped: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  TRADE EXECUTION ALERT
# ═══════════════════════════════════════════════════════════════════════════

def alert_trade_result(trade_id: int, direction: str, status: str,
                       entry: float, profit: float, grade: str = ""):
    """Alert on trade resolution (WIN/LOSS)."""
    emoji = "✅" if status == "WIN" else "❌"
    pnl_str = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"

    msg = (
        f"{emoji} *Trade #{trade_id} {status}*\n"
        f"{direction} | PnL: `{pnl_str}$`\n"
        f"Entry: `{entry:.2f}$` | Grade: {grade}"
    )
    _send_alert(msg, silent=(status == "WIN"))  # silent for wins, loud for losses


# ═══════════════════════════════════════════════════════════════════════════
#  SYSTEM HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════

def get_system_health() -> Dict:
    """
    Comprehensive system health check for /api/health/detailed endpoint.
    Returns status of all subsystems.
    """
    health = {
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "checks": {},
    }

    # Database
    try:
        from src.database import NewsDB
        db = NewsDB()
        row = db._query_one("SELECT COUNT(*) FROM trades")
        health["checks"]["database"] = {
            "status": "ok",
            "trades_count": row[0] if row else 0,
        }
    except Exception as e:
        health["checks"]["database"] = {"status": "error", "error": str(e)}
        health["status"] = "degraded"

    # Models
    try:
        import os
        models_ok = all(os.path.exists(f"models/{f}") for f in ["xgb.pkl", "lstm.keras"])
        health["checks"]["models"] = {
            "status": "ok" if models_ok else "missing",
            "xgb": os.path.exists("models/xgb.pkl"),
            "lstm": os.path.exists("models/lstm.keras"),
            "dqn": os.path.exists("models/rl_agent.keras"),
        }
    except Exception as e:
        health["checks"]["models"] = {"status": "error", "error": str(e)}

    # Risk manager
    try:
        from src.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm_status = rm.get_status()
        health["checks"]["risk_manager"] = {
            "status": "halted" if rm_status.get("halted") else "ok",
            "daily_loss_pct": rm_status.get("daily_loss_pct", 0),
            "consecutive_losses": rm_status.get("consecutive_losses", 0),
        }
        if rm_status.get("halted"):
            health["status"] = "degraded"
    except Exception as e:
        health["checks"]["risk_manager"] = {"status": "error", "error": str(e)}

    # Data provider
    try:
        from src.data_sources import get_provider
        provider = get_provider()
        price = provider.get_current_price("XAU/USD")
        health["checks"]["data_provider"] = {
            "status": "ok" if price else "unavailable",
            "gold_price": price.get("price") if price else None,
        }
    except Exception as e:
        health["checks"]["data_provider"] = {"status": "error", "error": str(e)}
        health["status"] = "degraded"

    # Metrics
    try:
        from src.metrics import get_all_metrics
        m = get_all_metrics()
        health["checks"]["metrics"] = {
            "status": "ok",
            "trades_today": m["trading"]["trades_opened"],
            "api_requests": m["api"]["requests_total"],
        }
    except Exception as e:
        health["checks"]["metrics"] = {"status": "error", "error": str(e)}

    return health


# ═══════════════════════════════════════════════════════════════════════════
#  WEEKLY PERFORMANCE REPORT
# ═══════════════════════════════════════════════════════════════════════════

def send_weekly_report():
    """Generate and send weekly performance summary to Telegram."""
    try:
        from src.database import NewsDB
        db = NewsDB()

        # Last 7 days
        week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

        trades = db._query(
            "SELECT direction, status, profit, session, setup_grade FROM trades "
            "WHERE DATE(timestamp) >= ? AND status IN ('WIN', 'LOSS')",
            (week_ago,)
        )

        if not trades:
            return

        wins = sum(1 for t in trades if t[1] == 'WIN')
        losses = sum(1 for t in trades if t[1] == 'LOSS')
        total = wins + losses
        wr = wins / total * 100 if total > 0 else 0
        total_pnl = sum(float(t[2] or 0) for t in trades)

        # Session breakdown
        sessions = {}
        for t in trades:
            s = t[3] or 'unknown'
            if s not in sessions:
                sessions[s] = {'w': 0, 'l': 0, 'pnl': 0}
            if t[1] == 'WIN':
                sessions[s]['w'] += 1
            else:
                sessions[s]['l'] += 1
            sessions[s]['pnl'] += float(t[2] or 0)

        session_str = ""
        for s, stats in sorted(sessions.items(), key=lambda x: -x[1]['pnl']):
            s_total = stats['w'] + stats['l']
            s_wr = stats['w'] / s_total * 100 if s_total > 0 else 0
            session_str += f"\n  {s}: {s_wr:.0f}% WR ({stats['w']}W/{stats['l']}L) PnL: {stats['pnl']:+.2f}$"

        pnl_emoji = "+" if total_pnl >= 0 else ""

        msg = (
            f"*WEEKLY REPORT* (last 7 days)\n"
            f"━━━━━━━━━━━━━━\n"
            f"Trades: {total} ({wins}W / {losses}L)\n"
            f"Win rate: `{wr:.0f}%`\n"
            f"P&L: `{pnl_emoji}{total_pnl:.2f}$`\n"
            f"\nBy session: {session_str}\n"
        )

        _send_alert(msg)
        logger.info(f"[MONITOR] Weekly report sent: {wins}W/{losses}L, PnL={total_pnl:+.2f}")

    except (ImportError, AttributeError, TypeError) as e:
        logger.warning(f"[MONITOR] Weekly report failed: {e}")
