"""
scripts/backfill_grades.py — retroactively populate setup_grade + setup_score
on existing trades that have factors but no grade (backtest.db pre-009446b).

Reads each NULL-grade trade, reconstructs minimal analysis dict from stored
columns, calls score_setup_quality, writes grade + score.

NOT exact (some analysis state isn't persisted) but accurate enough for
post-hoc analytics that group by grade.

Usage:
    python scripts/backfill_grades.py --db backtest [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def reconstruct_analysis(row: dict) -> dict:
    """Build a minimal analysis dict from stored trade columns + factors JSON."""
    factors_dict = {}
    try:
        if row.get("factors"):
            factors_dict = json.loads(row["factors"])
    except Exception:
        factors_dict = {}

    # Synthesize analysis dict — score_setup_quality reads many keys.
    # We cover what's most important; missing keys default to falsy.
    analysis = {
        "current_price": row.get("entry") or 0,
        "price": row.get("entry") or 0,
        "rsi": row.get("rsi") or 50,
        "atr": 5.0,  # not stored on trade row; use mid value
        "trend": row.get("trend") or "Bull",
        "structure": row.get("structure") or "Stable",
        "session": row.get("session") or "overlap",
        "macro_regime": "neutralny",  # not stored; would change penalty path
        "is_killzone": False,
        # Map factor_dict back to analysis flags
        "liquidity_grab": bool(factors_dict.get("grab_mss")),
        "mss": bool(factors_dict.get("grab_mss")),
        "liquidity_grab_dir": "bullish" if row.get("direction") == "LONG" else "bearish",
        "mss_direction": "bullish" if row.get("direction") == "LONG" else "bearish",
        "bos_bullish": bool(factors_dict.get("bos") and row.get("direction") == "LONG"),
        "bos_bearish": bool(factors_dict.get("bos") and row.get("direction") == "SHORT"),
        "choch_bullish": bool(factors_dict.get("choch") and row.get("direction") == "LONG"),
        "choch_bearish": bool(factors_dict.get("choch") and row.get("direction") == "SHORT"),
        "fvg_present": bool(factors_dict.get("fvg")),
        "fvg_dir": "bullish" if row.get("direction") == "LONG" else "bearish",
        "ob_count": int(factors_dict.get("ob_count", 0) or 0),
        "ob_price": row.get("entry") if factors_dict.get("ob_main") else None,
        "ichimoku_above_cloud": bool(factors_dict.get("ichimoku_bull")),
        "ichimoku_below_cloud": bool(factors_dict.get("ichimoku_bear")),
        "engulfing_score": 0.5 if factors_dict.get("engulfing") else 0,
        "pin_bar_score": 0.5 if factors_dict.get("pin_bar") else 0,
    }
    return analysis


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="backtest")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    paths = []
    if args.db in ("live", "both"):
        paths.append(("live", ROOT / "data" / "sentinel.db"))
    if args.db in ("backtest", "both"):
        paths.append(("backtest", ROOT / "data" / "backtest.db"))

    from src.trading.smc_engine import score_setup_quality

    total_updated = 0
    for label, p in paths:
        if not p.exists():
            print(f"[{label}] {p} missing")
            continue
        conn = sqlite3.connect(p)
        rows = conn.execute(
            """SELECT id, direction, entry, sl, tp, status, rsi, trend,
                      structure, factors, session
               FROM trades
               WHERE setup_grade IS NULL AND status IN ('WIN','LOSS','TIMEOUT','BREAKEVEN')
                 AND factors IS NOT NULL"""
        ).fetchall()
        cols = ["id", "direction", "entry", "sl", "tp", "status", "rsi",
                "trend", "structure", "factors", "session"]
        n_rows = len(rows)
        print(f"[{label}] {n_rows} trades to backfill")
        if not n_rows:
            conn.close()
            continue

        updates = []
        for r in rows:
            d = dict(zip(cols, r))
            analysis = reconstruct_analysis(d)
            try:
                result = score_setup_quality(analysis, d["direction"])
                grade = result["grade"]
                score = result["score"]
                updates.append((grade, score, d["id"]))
            except Exception as e:
                print(f"  [WARN] trade #{d['id']}: {e}")

        if args.dry_run:
            print(f"[{label}] DRY-RUN — would update {len(updates)} rows")
            for g, s, tid in updates[:5]:
                print(f"  #{tid} -> grade={g} score={s}")
            print(f"  ... and {max(0, len(updates)-5)} more")
        else:
            conn.executemany(
                "UPDATE trades SET setup_grade=?, setup_score=? WHERE id=?",
                updates
            )
            conn.commit()
            print(f"[{label}] Updated {len(updates)} rows")
            total_updated += len(updates)

        # Stats post-update
        rows = conn.execute(
            "SELECT setup_grade, COUNT(*) FROM trades "
            "WHERE status IN ('WIN','LOSS') GROUP BY setup_grade ORDER BY 2 DESC"
        ).fetchall()
        print(f"[{label}] Grade distribution after backfill:")
        for r in rows:
            print(f"  {r[0]!r:<10} {r[1]}")
        conn.close()

    print(f"\nTotal updated: {total_updated}")


if __name__ == "__main__":
    main()
