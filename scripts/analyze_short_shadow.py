"""
analyze_short_shadow.py — Compare SHORT XGB shadow predictions vs outcomes.

For every resolved trade with a `predictions_json.shadow_short_xgb` key,
correlate the shadow prediction (P(SHORT TP hit)) with the actual outcome.
Outputs a summary that answers:

  1. Did shadow_short signal SHORT (>0.5) when trade was LONG-loss?
     → SHORT model would have correctly suggested opposite direction.

  2. Did shadow_short signal LONG (<0.5) when trade was LONG-win?
     → SHORT model correctly stayed out / disagreed; LONG win meant it
       was wrong about SHORT but right about no-short-entry.

  3. Aggregate hit rate for "shadow_short>0.5 implies the LONG trade
     would lose" — proxy for whether wiring SHORT model would help.

USAGE
    .venv/Scripts/python.exe scripts/analyze_short_shadow.py

Read-only against data/sentinel.db. Requires at least 5 resolved trades
with shadow data (so run AFTER ~24-48h of live cycles post-restart).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "sentinel.db"


def main() -> int:
    if not DB.exists():
        print(f"ERR: DB miss {DB}")
        return 1
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        # Join resolved trades with their newest ml_predictions row
        cur.execute("""
            SELECT t.id, t.direction, t.status, t.profit, t.timestamp,
                   p.predictions_json
            FROM trades t
            LEFT JOIN ml_predictions p ON p.trade_id = t.id
            WHERE t.status IN ('WIN', 'LOSS')
            ORDER BY t.id DESC
            LIMIT 200
        """)
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        print("No resolved trades to analyze.")
        return 0

    parsed = []
    for trade_id, direction, status, profit, ts, pred_json in rows:
        if not pred_json:
            continue
        try:
            d = json.loads(pred_json)
        except Exception:
            continue
        shadow = d.get("shadow_short_xgb")
        if shadow is None:
            continue
        parsed.append({
            "id": trade_id, "direction": direction, "status": status,
            "profit": profit or 0.0, "ts": ts, "shadow_short": float(shadow),
        })

    print("=" * 70)
    print(f"SHORT XGB shadow analysis — {len(parsed)} trades with shadow data")
    print("=" * 70)
    if not parsed:
        print("(No shadow_short_xgb data yet — need post-restart trades)")
        return 0
    if len(parsed) < 5:
        print(f"⚠️  N<5; results not meaningful. Run again after more trades.")

    # Bucket: actual outcome × shadow direction
    buckets = {("LONG", "WIN"): [], ("LONG", "LOSS"): [],
               ("SHORT", "WIN"): [], ("SHORT", "LOSS"): []}
    for p in parsed:
        key = (p["direction"], p["status"])
        if key in buckets:
            buckets[key].append(p["shadow_short"])

    print(f"\n{'Live Trade':18}{'N':>5}{'shadow_short avg':>22}{'shadow agrees':>16}")
    print(f"{'-'*18}{'-'*5}{'-'*22}{'-'*16}")
    rows_out = [
        ("LONG WIN",  buckets[("LONG", "WIN")],  "<0.5"),  # short model says no-short = correct
        ("LONG LOSS", buckets[("LONG", "LOSS")], ">0.5"),  # short model says short = useful contrary
        ("SHORT WIN", buckets[("SHORT", "WIN")], ">0.5"),  # short model agrees with winning short
        ("SHORT LOSS",buckets[("SHORT", "LOSS")],"<0.5"),  # short model says no-short = useful
    ]
    for label, vals, agree_rule in rows_out:
        if not vals:
            print(f"{label:18}{0:>5}{'(no data)':>22}{'':>16}")
            continue
        avg = sum(vals) / len(vals)
        # "agrees" = shadow follows agree_rule
        if agree_rule == ">0.5":
            agree_n = sum(1 for v in vals if v > 0.5)
        else:
            agree_n = sum(1 for v in vals if v < 0.5)
        agree_pct = (agree_n / len(vals)) * 100
        print(f"{label:18}{len(vals):>5}{avg:>22.3f}{f'{agree_n}/{len(vals)} {agree_pct:.0f}%':>16}")

    # Headline: would wiring SHORT signal as a veto have helped?
    long_loss = buckets[("LONG", "LOSS")]
    long_win = buckets[("LONG", "WIN")]
    if long_loss and long_win:
        # Threshold sweep
        print("\n  THRESHOLD SWEEP — block LONG when shadow_short > T:")
        print(f"  {'T':>6}  {'losses_blocked':>15}  {'wins_blocked':>13}  {'P&L impact':>12}")
        for T in [0.40, 0.45, 0.50, 0.55, 0.60]:
            losses_blocked = sum(1 for v in long_loss if v > T)
            wins_blocked = sum(1 for v in long_win if v > T)
            # P&L: avg_loss * losses_blocked - avg_win * wins_blocked
            avg_loss = (sum(p["profit"] for p in parsed if p["direction"] == "LONG" and p["status"] == "LOSS") / max(len(long_loss), 1))
            avg_win = (sum(p["profit"] for p in parsed if p["direction"] == "LONG" and p["status"] == "WIN") / max(len(long_win), 1))
            pnl_saved = -avg_loss * losses_blocked - avg_win * wins_blocked
            print(f"  {T:>6.2f}  {losses_blocked:>15}  {wins_blocked:>13}  {pnl_saved:>+12.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
