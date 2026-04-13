#!/usr/bin/env python3
"""tools/voter_forensics.py - Post-hoc per-voter calibration analysis.

Used after defusing a voter to determine empirically whether we should:
  (a) restore it as-is (if trades without it lose),
  (b) retrain it (if it's been structurally wrong over many trades), or
  (c) keep it disabled (if retrain doesn't help).

Outputs one row per closed trade since a given start date, showing what
each voter said and whether it agreed with the winning direction. Plus
a summary per voter: accuracy, false-bull rate, false-bear rate.

Usage
-----
  python tools/voter_forensics.py                     # since dpformer_defused_at
  python tools/voter_forensics.py --since 2026-04-13  # explicit date
  python tools/voter_forensics.py --voter dpformer    # focus one voter
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, Counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="ISO date; default: value of dpformer_defused_at param")
    ap.add_argument("--voter", default=None,
                    help="focus on one voter (else all)")
    args = ap.parse_args()

    from src.core.database import NewsDB
    db = NewsDB()

    since = args.since or db.get_param("dpformer_defused_at", None)
    if not since:
        print("[fatal] no --since and no dpformer_defused_at param", file=sys.stderr)
        return 2
    print(f"[forensics] analyzing trades since {since}")

    # Closed trades since date
    rows = db._query(
        "SELECT id, timestamp, direction, status FROM trades "
        "WHERE timestamp >= ? AND status IN ('WIN','PROFIT','LOSS','LOSE') "
        "ORDER BY timestamp ASC",
        (since,))
    if not rows:
        print("[forensics] no closed trades yet — come back later")
        return 0

    print(f"[forensics] {len(rows)} closed trades")
    print()

    voter_stats: dict[str, Counter] = defaultdict(Counter)
    details = []

    for trade_id, t_ts, t_dir, t_status in rows:
        is_win = t_status in ("WIN", "PROFIT")
        winning_dir = (t_dir if is_win
                       else ("SHORT" if t_dir == "LONG" else "LONG"))

        # Match ml_predictions within 60 min BEFORE this trade
        pred = db._query_one(
            "SELECT predictions_json FROM ml_predictions "
            "WHERE timestamp <= ? AND timestamp >= datetime(?, '-60 minutes') "
            "ORDER BY timestamp DESC LIMIT 1",
            (t_ts, t_ts))
        if not pred or not pred[0]:
            continue
        try:
            data = json.loads(pred[0])
            preds = data.get("predictions", data)
        except Exception:
            continue

        row_line = [f"{t_ts[:16]} trade#{trade_id} {t_dir:<5} {t_status:<4} winning={winning_dir}"]
        for voter, info in preds.items():
            if args.voter and voter != args.voter:
                continue
            status = info.get("status")
            val = info.get("value")
            if status == "unavailable" or val is None:
                voter_stats[voter]["abstain"] += 1
                row_line.append(f"{voter}=abstain")
                continue
            val = float(val)
            vote = "LONG" if val > 0.5 else "SHORT"
            correct = (vote == winning_dir)
            voter_stats[voter]["n_voted"] += 1
            voter_stats[voter][("correct" if correct else "wrong")] += 1
            # Direction of error
            if not correct:
                if winning_dir == "LONG" and vote == "SHORT":
                    voter_stats[voter]["missed_long"] += 1
                elif winning_dir == "SHORT" and vote == "LONG":
                    voter_stats[voter]["missed_short"] += 1
            row_line.append(f"{voter}={val:.2f}({'OK' if correct else 'WRONG'})")
        details.append(" | ".join(row_line))

    for line in details:
        print(line)

    print()
    print("=== per-voter summary ===")
    header = f"{'voter':<12} {'n':>4} {'acc':>6} {'wrong':>6} {'abstain':>8} {'missed_long':>12} {'missed_short':>13}"
    print(header)
    print("-" * len(header))
    for voter in sorted(voter_stats.keys()):
        s = voter_stats[voter]
        n = s["n_voted"]
        acc = s["correct"] / n if n > 0 else 0
        print(f"{voter:<12} {n:>4} {acc:>6.1%} {s['wrong']:>6} {s['abstain']:>8} "
              f"{s['missed_long']:>12} {s['missed_short']:>13}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
