#!/usr/bin/env python3
"""replay_analyzer.py - Offline "what-if" analyzer for scanner decisions.

For each rejected_setups entry in the last N hours, shows:
 - Which filter blocked it
 - What the rejection reason was
 - What the outcome WOULD have been if we'd taken the trade
   (using yfinance forward prices at the timestamp)

Lets you calibrate thresholds without waiting for live data.
Answers: "if we relaxed confluence threshold, would we have made money?"

Usage:
  python scripts/replay_analyzer.py                    # last 24h summary
  python scripts/replay_analyzer.py --hours 72         # 3-day window
  python scripts/replay_analyzer.py --filter setup_quality  # only one filter
  python scripts/replay_analyzer.py --tf 5m            # only one TF

Example output:
  Rejected (last 24h): 560 setups across 4 TFs
  Top filter: setup_quality (235, 42%)
    -> if we'd taken them at entry+0.1% TP, 2h horizon:
       64% winrate, expectancy +$2.3/trade
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
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


def fetch_candles():
    """Prefer live provider (scanner's actual source), fall back to yf."""
    try:
        from src.data.data_sources import get_provider
        df = get_provider().get_candles("XAU/USD", "5m", 2016)
        if df is not None and not df.empty:
            import pandas as pd
            if "timestamp" in df.columns:
                df = df.set_index("timestamp")
            df.index = pd.to_datetime(df.index)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.columns = [str(c).lower() for c in df.columns]
            return df
    except Exception as e:
        print(f"[warn] live provider failed: {e}")
    # Fallback
    import yfinance as yf
    df = yf.download("GC=F", interval="5m", period="7d",
                     progress=False, auto_adjust=False)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                  for c in df.columns]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--filter", default=None,
                    help="Only analyze rejections from this filter_name")
    ap.add_argument("--tf", default=None,
                    help="Only analyze rejections for this timeframe")
    ap.add_argument("--horizon-bars", type=int, default=24,
                    help="Forward bars to evaluate (24 × 5m = 2h)")
    ap.add_argument("--target-pct", type=float, default=0.1,
                    help="Target profit % for 'win' classification")
    args = ap.parse_args()

    from src.core.database import NewsDB
    db = NewsDB()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()

    where = ["timestamp >= ?"]
    params = [cutoff]
    if args.filter:
        where.append("filter_name = ?")
        params.append(args.filter)
    if args.tf:
        where.append("timeframe = ?")
        params.append(args.tf)
    sql = f"""SELECT id, timestamp, timeframe, direction, price, rejection_reason, filter_name
    FROM rejected_setups WHERE {' AND '.join(where)} ORDER BY timestamp"""
    rows = db._query(sql, tuple(params))

    if not rows:
        print(f"No rejected setups in last {args.hours}h with given filters.")
        return 0

    print(f"Found {len(rows)} rejected setups. Loading forward prices...")
    df = fetch_candles()

    import pandas as pd
    by_filter: dict = defaultdict(lambda: Counter())
    by_filter_reason: dict = defaultdict(lambda: Counter())
    outcomes: dict = defaultdict(lambda: {"win": 0, "loss": 0, "flat": 0, "n": 0,
                                           "total_pnl_pct": 0.0})

    for row in rows:
        _id, ts_str, tf, direction, price, reason, fname = row
        by_filter[fname]["total"] += 1
        by_filter_reason[fname][reason] += 1

        if not price or not direction:
            continue
        ts = pd.Timestamp(ts_str)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        mask = df.index >= ts
        if not mask.any():
            continue
        idx_from = df.index[mask][0]
        future = df.index[df.index > idx_from][: args.horizon_bars]
        if len(future) < args.horizon_bars:
            continue
        try:
            entry = float(price)
            high = float(df.loc[future, "high"].max())
            low = float(df.loc[future, "low"].min())
        except Exception:
            continue

        if direction == "LONG":
            max_gain = (high - entry) / entry * 100
            max_loss = (low - entry) / entry * 100
        else:  # SHORT
            max_gain = (entry - low) / entry * 100
            max_loss = (entry - high) / entry * 100

        key = fname
        outcomes[key]["n"] += 1
        if max_gain >= args.target_pct:
            outcomes[key]["win"] += 1
            outcomes[key]["total_pnl_pct"] += args.target_pct
        elif max_loss <= -args.target_pct:
            outcomes[key]["loss"] += 1
            outcomes[key]["total_pnl_pct"] -= args.target_pct
        else:
            outcomes[key]["flat"] += 1

    # Report
    print()
    print(f"=== Rejected setups last {args.hours}h by filter ===")
    total = sum(c["total"] for c in by_filter.values())
    for fname, ct in sorted(by_filter.items(), key=lambda x: -x[1]["total"]):
        n = ct["total"]
        pct = n / total * 100 if total else 0
        out = outcomes.get(fname, {"n": 0})
        n_outcome = out["n"]
        if n_outcome > 0:
            wr = out["win"] / n_outcome * 100
            expectancy = out["total_pnl_pct"] / n_outcome
            verdict = ("SHOULD ACCEPT" if wr > 55 and expectancy > 0
                       else "BORDERLINE" if wr > 45
                       else "CORRECT REJECT")
            print(f"  [{verdict:16s}] {fname:20s} {n:4d} ({pct:5.1f}%) | "
                  f"hypothetical WR: {wr:.0f}%, expectancy: {expectancy:+.3f}%")
        else:
            print(f"  [no-data]         {fname:20s} {n:4d} ({pct:5.1f}%) | insufficient forward data")

    # Most common reasons
    print()
    print("=== Top rejection reasons ===")
    for fname, reasons in by_filter.items():
        if reasons["total"] > 10:
            top = by_filter_reason[fname].most_common(3)
            print(f"  {fname}:")
            for reason, n in top:
                print(f"    {n:4d}  {reason[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
