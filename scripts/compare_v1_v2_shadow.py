#!/usr/bin/env python3
"""
compare_v1_v2_shadow.py — Compare v2 shadow predictions to v1 production decisions.

Reads data/shadow_predictions.jsonl (built by api/main.py _shadow_scanner)
and computes hypothetical PnL for v2 decisions vs actual v1 decisions over
the same time window.

Methodology:
  For each shadow record at time t with v2_signal != 'WAIT':
    1. Look up actual price at t (from record)
    2. Look up actual price at t + horizon (from data warehouse or current
       fetch)
    3. Compute realized R = (price_diff * sign(v2_signal)) / (sl_atr * atr)
    4. Compare to v1 decision at same t (if v1 was WAIT: v1 R = 0;
       if v1 acted: use v1 trade outcome from sentinel.db)
  Aggregate: Wilcoxon signed-rank test for statistical significance.

Usage:
    python scripts/compare_v1_v2_shadow.py
    python scripts/compare_v1_v2_shadow.py --horizon-bars 24 --tf 5min
    python scripts/compare_v1_v2_shadow.py --since 2026-04-25
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure repo root on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SHADOW_LOG = Path("data/shadow_predictions.jsonl")
WAREHOUSE = Path("data/historical")


def load_shadow(since: datetime | None = None) -> pd.DataFrame:
    """Load shadow predictions from JSONL."""
    if not SHADOW_LOG.exists():
        return pd.DataFrame()
    records = []
    with open(SHADOW_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if since:
        df = df[df["ts"] >= pd.Timestamp(since, tz="UTC")]
    return df.sort_values("ts").reset_index(drop=True)


def lookup_future_price(ts: pd.Timestamp, horizon_bars: int, tf: str = "5min") -> float | None:
    """Get close price at ts + horizon_bars from warehouse XAU 5min file."""
    p = WAREHOUSE / "XAU_USD" / f"{tf}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    # Find the bar at ts (closest after)
    after = df[df["datetime"] >= ts]
    if len(after) < horizon_bars + 1:
        return None
    return float(after["close"].iloc[horizon_bars])


def realised_r(entry_price: float, future_price: float, atr: float,
               direction: str, sl_atr: float = 1.0) -> float:
    """Compute realized R given entry, exit, ATR, direction."""
    if not atr or atr <= 0:
        return 0.0
    sign = 1 if direction == "LONG" else -1
    risk = sl_atr * atr
    return sign * (future_price - entry_price) / risk


def evaluate_shadow(
    horizon_bars: int = 24,
    tf: str = "5min",
    since: datetime | None = None,
) -> dict:
    """
    Evaluate hypothetical v2 PnL based on shadow log + future warehouse data.

    Returns dict with summary stats.
    """
    shadow = load_shadow(since=since)
    if shadow.empty:
        return {"error": "no shadow records"}

    # Filter to actionable v2 signals
    actionable = shadow[shadow["v2_signal"].isin(["LONG", "SHORT"])].copy()
    if actionable.empty:
        return {"error": "no actionable v2 signals", "total_shadow_records": len(shadow)}

    rs = []
    skipped = 0
    for _, row in actionable.iterrows():
        future_p = lookup_future_price(row["ts"], horizon_bars, tf)
        if future_p is None or row.get("price") is None or row.get("atr") is None:
            skipped += 1
            continue
        r = realised_r(
            float(row["price"]), future_p, float(row["atr"]),
            row["v2_signal"], sl_atr=1.0,
        )
        rs.append({
            "ts": row["ts"], "v2_signal": row["v2_signal"],
            "v2_long_r_pred": row.get("v2_long_r_pred"),
            "v2_short_r_pred": row.get("v2_short_r_pred"),
            "realised_r": r,
            "v1_signal": row.get("v1_signal"),
        })

    if not rs:
        return {
            "error": "no records with full horizon data",
            "total_actionable": len(actionable),
            "skipped": skipped,
        }

    rs_df = pd.DataFrame(rs)
    n = len(rs_df)
    wins = (rs_df["realised_r"] > 0).sum()
    losses = (rs_df["realised_r"] < 0).sum()
    avg_r = rs_df["realised_r"].mean()
    median_r = rs_df["realised_r"].median()
    sum_r = rs_df["realised_r"].sum()
    long_n = (rs_df["v2_signal"] == "LONG").sum()
    short_n = (rs_df["v2_signal"] == "SHORT").sum()
    long_avg = rs_df.loc[rs_df["v2_signal"] == "LONG", "realised_r"].mean() if long_n else 0
    short_avg = rs_df.loc[rs_df["v2_signal"] == "SHORT", "realised_r"].mean() if short_n else 0

    # Statistical: t-test of mean R against 0
    from scipy import stats as scistats
    t_stat, p_val = scistats.ttest_1samp(rs_df["realised_r"].dropna(), 0)

    return {
        "n_evaluated": int(n),
        "n_skipped": int(skipped),
        "horizon_bars": horizon_bars,
        "tf": tf,
        "wr_pct": float(wins / n * 100),
        "wins": int(wins),
        "losses": int(losses),
        "avg_realised_r": float(avg_r),
        "median_realised_r": float(median_r),
        "sum_realised_r": float(sum_r),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "long_avg_r": float(long_avg),
        "short_avg_r": float(short_avg),
        "t_stat_vs_zero": float(t_stat),
        "p_value": float(p_val),
        "statistically_significant": bool(p_val < 0.05),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-bars", type=int, default=24,
                    help="bars after entry to lookup price")
    ap.add_argument("--tf", default="5min")
    ap.add_argument("--since", default=None,
                    help="ISO datetime — only consider shadow records after this")
    args = ap.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    result = evaluate_shadow(
        horizon_bars=args.horizon_bars, tf=args.tf, since=since,
    )

    print("=" * 60)
    print("SHADOW v2 EVALUATION")
    print("=" * 60)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        for k, v in result.items():
            if k != "error":
                print(f"  {k}: {v}")
        return
    for k, v in result.items():
        if isinstance(v, float):
            print(f"  {k:30s}: {v:.4f}")
        else:
            print(f"  {k:30s}: {v}")
    print("=" * 60)


if __name__ == "__main__":
    main()
