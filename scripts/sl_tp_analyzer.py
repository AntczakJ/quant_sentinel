"""
scripts/sl_tp_analyzer.py — analyze SL/TP placement vs trade outcomes.

For each closed trade, computes:
  - Actual SL distance in ATR multiples
  - Actual R:R achieved
  - "Maximum favorable excursion" (MFE) — how far did price go in our
    direction before reversing?
  - "Maximum adverse excursion" (MAE) — how far against?

Then aggregates:
  - Are losers hit by tiny adverse moves (SL too tight)?
  - Are winners losing TP-bound profit (TP too narrow)?
  - Distribution of MFE/MAE for WIN vs LOSS

Output: actionable verdicts on whether to widen SL or tighten TP.

Note: requires bar-level data. Uses ATR from trade row + entry/SL/TP.
Cannot compute MFE/MAE without OHLC time series (out of scope here);
proxy: actual_R = profit / risk_per_trade.

Usage:
    python scripts/sl_tp_analyzer.py [--db both] [--min-n 10]
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id, direction, status, entry, sl, tp, profit, lot,
                  filled_entry, filled_sl, filled_tp, slippage,
                  setup_grade, vol_regime, NULL as atr
           FROM trades
           WHERE status IN ('WIN','LOSS','TIMEOUT')"""
    ).fetchall()
    out = []
    cols = ["id", "direction", "status", "entry", "sl", "tp", "profit", "lot",
            "filled_entry", "filled_sl", "filled_tp", "slippage",
            "setup_grade", "vol_regime", "atr"]
    for r in rows:
        d = dict(zip(cols, r))
        out.append(d)
    conn.close()
    return out


def analyze_trade(t: dict) -> dict:
    """Compute placement diagnostics for one trade."""
    if not all(t.get(k) is not None for k in ("entry", "sl", "tp")):
        return {}
    entry = t["entry"]
    sl = t["sl"]
    tp = t["tp"]
    direction = t["direction"]

    sl_distance = abs(entry - sl)
    tp_distance = abs(tp - entry)
    rr_planned = tp_distance / max(0.01, sl_distance)

    atr = t.get("atr") or 0
    sl_in_atr = sl_distance / atr if atr else None
    tp_in_atr = tp_distance / atr if atr else None

    return {
        "id": t["id"],
        "status": t["status"],
        "direction": direction,
        "sl_distance": round(sl_distance, 2),
        "tp_distance": round(tp_distance, 2),
        "rr_planned": round(rr_planned, 2),
        "sl_in_atr": round(sl_in_atr, 2) if sl_in_atr else None,
        "tp_in_atr": round(tp_in_atr, 2) if tp_in_atr else None,
        "profit": t.get("profit") or 0,
        "lot": t.get("lot") or 0,
        "grade": t.get("setup_grade"),
    }


def aggregate(diags: list[dict]) -> dict:
    """Aggregate stats by outcome."""
    by_status = {"WIN": [], "LOSS": [], "TIMEOUT": []}
    for d in diags:
        if d.get("status") in by_status:
            by_status[d["status"]].append(d)

    out = {}
    for status, items in by_status.items():
        if not items:
            continue
        sl_atrs = [d["sl_in_atr"] for d in items if d.get("sl_in_atr") is not None]
        tp_atrs = [d["tp_in_atr"] for d in items if d.get("tp_in_atr") is not None]
        rrs = [d["rr_planned"] for d in items if d.get("rr_planned")]
        profits = [d["profit"] for d in items]
        out[status] = {
            "n": len(items),
            "sl_atr_mean": sum(sl_atrs) / len(sl_atrs) if sl_atrs else None,
            "sl_atr_median": sorted(sl_atrs)[len(sl_atrs)//2] if sl_atrs else None,
            "tp_atr_mean": sum(tp_atrs) / len(tp_atrs) if tp_atrs else None,
            "tp_atr_median": sorted(tp_atrs)[len(tp_atrs)//2] if tp_atrs else None,
            "rr_mean": sum(rrs) / len(rrs) if rrs else None,
            "profit_mean": sum(profits) / len(profits) if profits else None,
            "profit_total": sum(profits),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=10)
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db"))

    diags = [d for d in (analyze_trade(t) for t in trades) if d]
    n = len(diags)
    if not n:
        print("No trades.")
        return

    agg = aggregate(diags)
    print(f"COHORT: {n} trades\n")
    print(f"{'Status':<10} {'N':>4} {'SL ATR':>8} {'TP ATR':>8} {'R:R':>6} {'Profit':>10}")
    for status, s in agg.items():
        sl_a = f"{s['sl_atr_mean']:.2f}" if s.get('sl_atr_mean') else "-"
        tp_a = f"{s['tp_atr_mean']:.2f}" if s.get('tp_atr_mean') else "-"
        rr = f"{s['rr_mean']:.2f}" if s.get('rr_mean') else "-"
        print(f"{status:<10} {s['n']:>4} {sl_a:>8} {tp_a:>8} {rr:>6} ${s['profit_total']:>+9.2f}")

    # Per-grade breakdown
    print("\n=== By setup_grade ===")
    by_grade = {}
    for d in diags:
        g = d.get("grade") or "?"
        by_grade.setdefault(g, []).append(d)
    print(f"{'Grade':<6} {'N':>4} {'WR':>6} {'avg P/L':>10}")
    for g in sorted(by_grade.keys()):
        items = by_grade[g]
        n_g = len(items)
        wins = sum(1 for d in items if d["status"] == "WIN")
        avg_pl = sum(d["profit"] for d in items) / n_g
        print(f"{g:<6} {n_g:>4} {wins/n_g*100:>5.1f}% ${avg_pl:>+9.2f}")

    # Findings
    print("\n=== KEY FINDINGS ===")
    if "WIN" in agg and "LOSS" in agg:
        win_sl = agg["WIN"].get("sl_atr_mean")
        loss_sl = agg["LOSS"].get("sl_atr_mean")
        if win_sl and loss_sl:
            if loss_sl < win_sl - 0.3:
                print(f"  SL placement may be too tight on losers: "
                      f"LOSS SL={loss_sl:.2f}xATR vs WIN SL={win_sl:.2f}xATR")
            elif win_sl < loss_sl - 0.3:
                print(f"  WINs are placed with TIGHTER SL than LOSSES — odd: "
                      f"WIN={win_sl:.2f}xATR, LOSS={loss_sl:.2f}xATR")
            else:
                print(f"  SL distance similar across outcomes "
                      f"(WIN={win_sl:.2f}, LOSS={loss_sl:.2f}xATR)")
        win_rr = agg["WIN"].get("rr_mean")
        loss_rr = agg["LOSS"].get("rr_mean")
        if win_rr and loss_rr:
            if abs(win_rr - loss_rr) > 0.3:
                print(f"  R:R differs by outcome: WIN R:R={win_rr:.2f}, LOSS R:R={loss_rr:.2f}")
            else:
                print(f"  R:R consistent across outcomes (~{(win_rr + loss_rr)/2:.2f})")


if __name__ == "__main__":
    main()
