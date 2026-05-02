"""
backfill_short_shadow.py — historical retrospective: would SHORT XGB
have blocked the losing trades?

Loads each resolved trade, recomputes features at trade timestamp from
warehouse 5min XAU, runs SHORT XGB (models/short_2026-05-02/xgb.pkl),
and tabulates:

  - For LONG-LOSS trades: did SHORT model agree with the loss (predict
    SHORT-side)? If yes, wiring SHORT XGB as a LONG-veto would have
    saved that trade.
  - For LONG-WIN trades: did SHORT model also predict LONG? Or would
    it have falsely blocked the win?
  - For SHORT-WIN trades: did SHORT model predict SHORT? Confirms
    convergent good signals.

Key WR question answered: at threshold T, how many LONG losses would
SHORT model have blocked vs how many LONG wins would it have falsely
blocked?

USAGE
    .venv/Scripts/python.exe scripts/backfill_short_shadow.py
"""
from __future__ import annotations

import os
import pickle
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("LOGFIRE_IGNORE_NO_CONFIG", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

DB = REPO / "data" / "sentinel.db"
SHORT_XGB_PATH = REPO / "models" / "short_2026-05-02" / "xgb.pkl"
WAREHOUSE_5M = REPO / "data" / "historical" / "XAU_USD" / "5min.parquet"
WAREHOUSE_USDJPY = REPO / "data" / "historical" / "USD_JPY" / "5min.parquet"
COHORT_CUTOFF = "2026-04-06"


def main() -> int:
    if not SHORT_XGB_PATH.exists():
        print(f"ERR: SHORT XGB missing at {SHORT_XGB_PATH}")
        return 1
    if not WAREHOUSE_5M.exists():
        print(f"ERR: warehouse miss {WAREHOUSE_5M}")
        return 1

    # Load model
    print(f"Loading SHORT XGB from {SHORT_XGB_PATH}...")
    with open(SHORT_XGB_PATH, "rb") as f:
        model = pickle.load(f)

    # Load warehouse
    print(f"Loading warehouse 5min XAU...")
    df_xau = pd.read_parquet(WAREHOUSE_5M)
    df_xau["datetime"] = pd.to_datetime(df_xau["datetime"], utc=True)
    df_xau = df_xau.sort_values("datetime").reset_index(drop=True)

    df_usdjpy = None
    if WAREHOUSE_USDJPY.exists():
        df_usdjpy = pd.read_parquet(WAREHOUSE_USDJPY)
        df_usdjpy["datetime"] = pd.to_datetime(df_usdjpy["datetime"], utc=True)

    # Trades from DB
    print(f"Loading resolved trades since {COHORT_CUTOFF}...")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT id, timestamp, direction, status, profit, pattern
            FROM trades
            WHERE status IN ('WIN','LOSS') AND timestamp >= ?
            ORDER BY id
        """, (COHORT_CUTOFF,))
        trades = cur.fetchall()
    finally:
        con.close()

    print(f"Got {len(trades)} resolved trades.")

    from src.analysis.compute import compute_features, FEATURE_COLS

    results = []
    for trade_id, ts_str, direction, status, profit, pattern in trades:
        try:
            ts = pd.Timestamp(ts_str)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
        except Exception as e:
            print(f"#{trade_id}: bad timestamp {ts_str}: {e}")
            continue

        # Get last 200 bars at-or-before trade time
        mask = df_xau["datetime"] <= ts
        sub = df_xau[mask].tail(200)
        if len(sub) < 60:
            print(f"#{trade_id}: insufficient bars (n={len(sub)})")
            continue

        # USDJPY slice
        usdjpy_sub = None
        if df_usdjpy is not None:
            mask_jpy = df_usdjpy["datetime"] <= ts
            usdjpy_sub = df_usdjpy[mask_jpy].tail(200)

        try:
            feats = compute_features(sub.copy(), usdjpy_df=usdjpy_sub)
        except Exception as e:
            print(f"#{trade_id}: compute_features failed: {e}")
            continue

        if feats.empty:
            continue
        try:
            x = feats[FEATURE_COLS].iloc[[-1]].values
            proba = model.predict_proba(x)
            short_p = float(proba[0, 1]) if proba.ndim == 2 and proba.shape[1] >= 2 else float(proba[0])
        except Exception as e:
            print(f"#{trade_id}: predict failed: {e}")
            continue

        results.append({
            "id": trade_id, "ts": ts_str, "dir": direction,
            "status": status, "profit": profit or 0.0,
            "pattern": pattern, "short_p": short_p,
        })

    if not results:
        print("No predictions generated.")
        return 0

    # Tabulate
    print()
    print("=" * 90)
    print(f"{'id':>4}  {'ts':>20}  {'dir':>5}  {'status':>6}  {'profit':>8}  {'short_p':>8}  signal")
    print("-" * 90)
    for r in results:
        # Interpret short_p: high = SHORT model thinks SHORT wins
        sig = "SHORT" if r["short_p"] > 0.55 else ("LONG" if r["short_p"] < 0.45 else "NEUTRAL")
        # "Useful contrary": LONG-LOSS where short_p>0.5 = SHORT model would have warned
        useful = ""
        if r["dir"] == "LONG" and r["status"] == "LOSS" and r["short_p"] > 0.5:
            useful = " [USEFUL VETO]"
        elif r["dir"] == "LONG" and r["status"] == "WIN" and r["short_p"] > 0.5:
            useful = " [FALSE BLOCK]"
        elif r["dir"] == "SHORT" and r["status"] == "WIN" and r["short_p"] > 0.5:
            useful = " [convergent]"
        print(f"  {r['id']:>3}  {r['ts'][:19]:>20}  {r['dir']:>5}  {r['status']:>6}  "
              f"{r['profit']:>+8.2f}  {r['short_p']:>8.3f}  {sig:>7}{useful}")

    # Threshold sweep — would-be P&L impact of "block LONG when short_p > T"
    print()
    print("=" * 60)
    print("THRESHOLD SWEEP — block LONG when short_p > T")
    print("=" * 60)
    print(f"{'T':>6}  {'long_loss_blocked':>18}  {'long_win_blocked':>17}  {'pnl_saved':>11}")
    long_losses = [r for r in results if r["dir"] == "LONG" and r["status"] == "LOSS"]
    long_wins = [r for r in results if r["dir"] == "LONG" and r["status"] == "WIN"]
    avg_loss = sum(r["profit"] for r in long_losses) / len(long_losses) if long_losses else 0
    avg_win = sum(r["profit"] for r in long_wins) / len(long_wins) if long_wins else 0
    for T in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]:
        ll_b = sum(1 for r in long_losses if r["short_p"] > T)
        lw_b = sum(1 for r in long_wins if r["short_p"] > T)
        # P&L saved = -avg_loss * blocked_losses  - avg_win * blocked_wins
        pnl_saved = (-avg_loss) * ll_b - avg_win * lw_b
        print(f"  {T:>4.2f}  {ll_b:>18}  {lw_b:>17}  {pnl_saved:>+11.2f}")

    # Per-direction summary
    print("\n=== Per-direction summary ===")
    for dir_filter in ("LONG", "SHORT"):
        sub = [r for r in results if r["dir"] == dir_filter]
        if not sub:
            continue
        wins = [r for r in sub if r["status"] == "WIN"]
        losses = [r for r in sub if r["status"] == "LOSS"]
        avg_short_p_win = sum(r["short_p"] for r in wins) / len(wins) if wins else 0
        avg_short_p_loss = sum(r["short_p"] for r in losses) / len(losses) if losses else 0
        print(f"  {dir_filter}: n={len(sub)} (wins={len(wins)} losses={len(losses)})")
        print(f"    avg short_p on wins:   {avg_short_p_win:.3f}")
        print(f"    avg short_p on losses: {avg_short_p_loss:.3f}")
        # Ideal: WIN should have low short_p (SHORT disagrees with our profitable LONG-or-SHORT)
        # LOSS should have high short_p (SHORT agrees and would warn us)
        # Wait, this depends on direction of trade.

    # Persist report
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report = REPO / "reports" / f"{today}_short_shadow_backfill.md"
    report.parent.mkdir(exist_ok=True)
    with report.open("w", encoding="utf-8") as f:
        f.write(f"# SHORT XGB historical shadow — {today}\n\n")
        f.write(f"Cohort: {COHORT_CUTOFF} -> {today}, N={len(results)}\n\n")
        f.write("Threshold sweep — block LONG when short_p > T:\n\n")
        f.write("| T | long_losses_blocked | long_wins_blocked | pnl_saved |\n")
        f.write("|---|---:|---:|---:|\n")
        for T in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]:
            ll_b = sum(1 for r in long_losses if r["short_p"] > T)
            lw_b = sum(1 for r in long_wins if r["short_p"] > T)
            pnl_saved = (-avg_loss) * ll_b - avg_win * lw_b
            f.write(f"| {T:.2f} | {ll_b} | {lw_b} | {pnl_saved:+.2f} |\n")
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
