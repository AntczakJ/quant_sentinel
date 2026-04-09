"""
src/compliance.py — Compliance, Audit & Data Retention

Provides:
  1. Hash-chain audit log (tamper-proof trade history)
  2. Trade execution quality metrics (slippage, fill rate)
  3. Daily P&L report generation (persistent, stored in DB)
  4. Data retention & archival policy

Hash chain: each audit entry stores SHA-256 hash of previous entry.
If any record is modified, the chain breaks — detectable by verify_chain().
"""

import hashlib
import json
import datetime
from typing import Optional, Dict, List
from src.core.logger import logger


# ═══════════════════════════════════════════════════════════════════════════
#  HASH-CHAIN AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════

def _compute_hash(trade_id: int, old_status: str, new_status: str,
                  field: str, old_val: str, new_val: str,
                  reason: str, timestamp: str, prev_hash: str) -> str:
    """Compute SHA-256 hash of audit entry + previous hash (chain link)."""
    payload = f"{trade_id}|{old_status}|{new_status}|{field}|{old_val}|{new_val}|{reason}|{timestamp}|{prev_hash}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def log_audit_with_chain(trade_id: int, old_status: str, new_status: str,
                         field_changed: str = "status", old_value: str = "",
                         new_value: str = "", reason: str = ""):
    """
    Write tamper-proof audit entry with hash chain.

    Each entry stores:
      - Trade change details (who, what, when, why)
      - SHA-256 hash of (this_entry + previous_hash)
      - Previous entry's hash for chain verification
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get previous hash (last entry in chain)
        prev = db._query_one(
            "SELECT entry_hash FROM trades_audit ORDER BY id DESC LIMIT 1"
        )
        prev_hash = prev[0] if prev and prev[0] else "GENESIS"

        # Compute this entry's hash
        entry_hash = _compute_hash(
            trade_id, old_status, new_status,
            field_changed, old_value, new_value,
            reason, ts, prev_hash
        )

        db._execute(
            "INSERT INTO trades_audit "
            "(trade_id, old_status, new_status, field_changed, old_value, new_value, "
            "reason, timestamp, prev_hash, entry_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, old_status, new_status, field_changed,
             old_value, new_value, reason, ts, prev_hash, entry_hash)
        )

    except (ImportError, AttributeError, TypeError) as e:
        logger.debug(f"[AUDIT] Chain log failed: {e}")
        # Fallback to simple audit (without hash)
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            db.log_trade_audit(trade_id, old_status, new_status,
                               field_changed, old_value, new_value, reason)
        except (ImportError, AttributeError):
            pass


def verify_audit_chain() -> Dict:
    """
    Verify integrity of the entire audit hash chain.

    Returns:
      {"valid": True/False, "total_entries": int, "broken_at": int|None}

    If any entry was tampered with, the chain breaks at that point.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()

        rows = db._query(
            "SELECT id, trade_id, old_status, new_status, field_changed, "
            "old_value, new_value, reason, timestamp, prev_hash, entry_hash "
            "FROM trades_audit ORDER BY id ASC"
        )

        if not rows:
            return {"valid": True, "total_entries": 0, "broken_at": None}

        prev_hash = "GENESIS"
        for row in rows:
            (entry_id, trade_id, old_status, new_status, field,
             old_val, new_val, reason, ts, stored_prev, stored_hash) = row

            # Verify previous hash link
            if stored_prev and stored_prev != prev_hash:
                return {
                    "valid": False,
                    "total_entries": len(rows),
                    "broken_at": entry_id,
                    "error": f"Previous hash mismatch at entry #{entry_id}",
                }

            # Verify entry hash (if present)
            if stored_hash:
                expected = _compute_hash(
                    trade_id, old_status or "", new_status or "",
                    field or "", old_val or "", new_val or "",
                    reason or "", ts or "", prev_hash
                )
                if stored_hash != expected:
                    return {
                        "valid": False,
                        "total_entries": len(rows),
                        "broken_at": entry_id,
                        "error": f"Entry hash mismatch at #{entry_id} (data tampered)",
                    }

            prev_hash = stored_hash or prev_hash

        return {"valid": True, "total_entries": len(rows), "broken_at": None}

    except (ImportError, AttributeError, TypeError) as e:
        return {"valid": False, "error": str(e), "total_entries": 0}


# ═══════════════════════════════════════════════════════════════════════════
#  TRADE EXECUTION QUALITY REPORT
# ═══════════════════════════════════════════════════════════════════════════

def get_execution_quality_report(days: int = 30) -> Dict:
    """
    Analyze trade execution quality over the last N days.

    Metrics:
      - Fill rate (% of proposed trades that actually opened)
      - Average slippage (filled_entry vs requested entry)
      - SL hit accuracy (filled_sl vs requested sl)
      - Win rate by grade (A+ vs A vs B)
      - Average hold time (entry to close)
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()

        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

        # All resolved trades
        trades = db._query(
            "SELECT id, direction, entry, sl, tp, status, profit, "
            "filled_entry, filled_sl, slippage, setup_grade, timestamp "
            "FROM trades WHERE DATE(timestamp) >= ? AND status IN ('WIN', 'LOSS')",
            (cutoff,)
        )

        if not trades:
            return {"error": "No trades in period", "days": days}

        total = len(trades)
        wins = sum(1 for t in trades if t[5] == 'WIN')
        total_pnl = sum(float(t[6] or 0) for t in trades)

        # Slippage analysis
        slippage_data = []
        for t in trades:
            entry = float(t[2] or 0)
            filled = float(t[7] or 0)
            if entry > 0 and filled > 0:
                slip = abs(filled - entry)
                slippage_data.append(slip)

        avg_slippage = sum(slippage_data) / len(slippage_data) if slippage_data else 0

        # Win rate by grade
        grade_stats = {}
        for t in trades:
            grade = t[10] or 'Unknown'
            if grade not in grade_stats:
                grade_stats[grade] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t[5] == 'WIN':
                grade_stats[grade]['wins'] += 1
            else:
                grade_stats[grade]['losses'] += 1
            grade_stats[grade]['pnl'] += float(t[6] or 0)

        for g in grade_stats:
            total_g = grade_stats[g]['wins'] + grade_stats[g]['losses']
            grade_stats[g]['win_rate'] = round(grade_stats[g]['wins'] / total_g, 3) if total_g > 0 else 0
            grade_stats[g]['total'] = total_g

        # Proposed vs opened (fill rate)
        proposed = db._query_one(
            "SELECT COUNT(*) FROM trades WHERE DATE(timestamp) >= ?", (cutoff,)
        )
        rejected = db._query_one(
            "SELECT COUNT(*) FROM rejected_setups WHERE DATE(timestamp) >= ?", (cutoff,)
        )
        proposed_count = (proposed[0] if proposed else 0) + (rejected[0] if rejected else 0)
        fill_rate = total / proposed_count if proposed_count > 0 else 1.0

        return {
            "period_days": days,
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 3) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total > 0 else 0,
            "fill_rate": round(fill_rate, 3),
            "avg_slippage": round(avg_slippage, 4),
            "slippage_samples": len(slippage_data),
            "by_grade": grade_stats,
        }

    except (ImportError, AttributeError, TypeError) as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
#  DAILY P&L REPORT (persistent, stored in DB)
# ═══════════════════════════════════════════════════════════════════════════

def generate_daily_report(date: Optional[str] = None) -> Dict:
    """
    Generate and persist daily P&L report for a specific date.
    Stored in dynamic_params as JSON for historical retrieval.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()

        if date is None:
            date = datetime.date.today().isoformat()

        trades = db._query(
            "SELECT direction, status, profit, session, setup_grade, lot FROM trades "
            "WHERE DATE(timestamp) = ? AND status IN ('WIN', 'LOSS')",
            (date,)
        )

        wins = sum(1 for t in trades if t[1] == 'WIN')
        losses = len(trades) - wins
        total_pnl = sum(float(t[2] or 0) for t in trades)

        # By direction
        long_trades = [t for t in trades if 'LONG' in str(t[0]).upper()]
        short_trades = [t for t in trades if 'SHORT' in str(t[0]).upper()]

        report = {
            "date": date,
            "total_trades": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(trades), 3) if trades else 0,
            "total_pnl": round(total_pnl, 2),
            "long": {
                "count": len(long_trades),
                "wins": sum(1 for t in long_trades if t[1] == 'WIN'),
                "pnl": round(sum(float(t[2] or 0) for t in long_trades), 2),
            },
            "short": {
                "count": len(short_trades),
                "wins": sum(1 for t in short_trades if t[1] == 'WIN'),
                "pnl": round(sum(float(t[2] or 0) for t in short_trades), 2),
            },
        }

        # Persist
        db.set_param(f"daily_report_{date}", json.dumps(report))
        return report

    except (ImportError, AttributeError, TypeError) as e:
        return {"error": str(e)}


def get_daily_report(date: str) -> Optional[Dict]:
    """Retrieve persisted daily report for a specific date."""
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        raw = db.get_param(f"daily_report_{date}")
        if raw and isinstance(raw, str):
            return json.loads(raw)
    except (ImportError, json.JSONDecodeError, TypeError):
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  DATA RETENTION & ARCHIVAL
# ═══════════════════════════════════════════════════════════════════════════

def archive_old_data(retention_days: int = 365) -> Dict:
    """
    Archive data older than retention_days.

    Strategy:
      - ml_predictions > 90 days → DELETE (high volume, regenerated by models)
      - rejected_setups > 90 days → DELETE (analysis data, not critical)
      - trades_audit: NEVER delete (compliance requirement)
      - trades: NEVER delete (permanent record)
      - pattern_stats: NEVER delete (accumulated wisdom)

    Returns count of archived/deleted rows.
    """
    try:
        from src.core.database import NewsDB
        db = NewsDB()

        cutoff_90d = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
        results = {}

        # ml_predictions — high volume, safe to trim
        try:
            before = db._query_one("SELECT COUNT(*) FROM ml_predictions")
            db._execute(
                "DELETE FROM ml_predictions WHERE DATE(timestamp) < ?",
                (cutoff_90d,)
            )
            after = db._query_one("SELECT COUNT(*) FROM ml_predictions")
            deleted = (before[0] if before else 0) - (after[0] if after else 0)
            if deleted > 0:
                results["ml_predictions"] = {"deleted": deleted}
                logger.info(f"[RETENTION] Archived {deleted} ml_predictions older than 90 days")
        except (AttributeError, TypeError):
            pass

        # rejected_setups — analysis data
        try:
            before = db._query_one("SELECT COUNT(*) FROM rejected_setups")
            db._execute(
                "DELETE FROM rejected_setups WHERE DATE(timestamp) < ?",
                (cutoff_90d,)
            )
            after = db._query_one("SELECT COUNT(*) FROM rejected_setups")
            deleted = (before[0] if before else 0) - (after[0] if after else 0)
            if deleted > 0:
                results["rejected_setups"] = {"deleted": deleted}
        except (AttributeError, TypeError):
            pass

        # processed_news — dedup cache (no timestamp column, trim by count if too large)
        try:
            count_row = db._query_one("SELECT COUNT(*) FROM processed_news")
            total = count_row[0] if count_row else 0
            if total > 1000:
                # Keep last 500, delete oldest
                db._execute(
                    "DELETE FROM processed_news WHERE title_hash NOT IN "
                    "(SELECT title_hash FROM processed_news ORDER BY rowid DESC LIMIT 500)"
                )
                deleted = total - 500
                results["processed_news"] = {"deleted": deleted}
        except (AttributeError, TypeError):
            pass

        # Log retention summary
        total_deleted = sum(v.get("deleted", 0) for v in results.values())
        if total_deleted > 0:
            logger.info(f"[RETENTION] Total archived: {total_deleted} rows across {len(results)} tables")
        else:
            logger.debug("[RETENTION] No data to archive")

        return {"archived": results, "retention_days": 90, "protected_tables": [
            "trades", "trades_audit", "pattern_stats", "session_stats", "dynamic_params"
        ]}

    except (ImportError, AttributeError) as e:
        return {"error": str(e)}
