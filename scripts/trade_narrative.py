"""
scripts/trade_narrative.py — chronological equity narrative.

Reads all closed trades, builds equity curve over time, surfaces:
  - Major drawdowns and their causes (consecutive LOSS streaks)
  - Pivotal trades (largest wins/losses)
  - Streak breakdowns (max consec wins/losses)
  - Per-week summary table
  - Best/worst week

Differs from existing equity-curve PNG export — this is a PROSE narrative
suitable for a daily review or postmortem doc.

Usage:
    python scripts/trade_narrative.py [--db both] [--output reports/narrative.md]
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.split("+")[0].split(".")[0], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id, timestamp, direction, status, profit, pattern,
                  setup_grade, session
           FROM trades WHERE status IN ('WIN','LOSS','TIMEOUT','BREAKEVEN')
           ORDER BY timestamp"""
    ).fetchall()
    out = []
    for r in rows:
        ts = parse_ts(r[1])
        if not ts:
            continue
        out.append({
            "id": r[0], "ts": ts, "direction": r[2],
            "status": r[3], "profit": r[4] or 0,
            "pattern": r[5] or "?", "grade": r[6] or "?", "session": r[7] or "?",
        })
    conn.close()
    return sorted(out, key=lambda t: t["ts"])


def streaks(trades: list[dict]) -> dict:
    """Find longest WIN/LOSS streaks."""
    cur_kind = None
    cur_len = 0
    cur_start = None
    longest = {"WIN": (0, None, None), "LOSS": (0, None, None)}
    for t in trades:
        kind = t["status"] if t["status"] in ("WIN", "LOSS") else None
        if kind == cur_kind:
            cur_len += 1
        else:
            if cur_kind in ("WIN", "LOSS") and cur_len > longest[cur_kind][0]:
                longest[cur_kind] = (cur_len, cur_start, prev_t)
            cur_kind = kind
            cur_len = 1 if kind else 0
            cur_start = t["ts"] if kind else None
        prev_t = t["ts"]
    # Final streak
    if cur_kind in ("WIN", "LOSS") and cur_len > longest[cur_kind][0]:
        longest[cur_kind] = (cur_len, cur_start, prev_t)
    return longest


def equity_curve(trades: list[dict], starting=10000.0):
    equity = [starting]
    timestamps = [trades[0]["ts"]] if trades else []
    for t in trades:
        equity.append(equity[-1] + t["profit"])
        timestamps.append(t["ts"])
    return timestamps, equity


def max_drawdown(equity: list[float]):
    """Return (max_dd_pct, peak_idx, trough_idx)."""
    if not equity:
        return 0, 0, 0
    peak = equity[0]
    peak_idx = 0
    max_dd = 0
    max_dd_peak = 0
    max_dd_trough = 0
    for i, e in enumerate(equity):
        if e > peak:
            peak = e
            peak_idx = i
        dd = (e - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
            max_dd_peak = peak_idx
            max_dd_trough = i
    return max_dd, max_dd_peak, max_dd_trough


def per_week_summary(trades: list[dict]):
    """Group trades by ISO week."""
    by_week = {}
    for t in trades:
        wk = t["ts"].isocalendar()[:2]  # (year, week)
        by_week.setdefault(wk, []).append(t)
    out = []
    for wk in sorted(by_week.keys()):
        ts = by_week[wk]
        n = len(ts)
        wins = sum(1 for t in ts if t["status"] == "WIN")
        pl = sum(t["profit"] for t in ts)
        out.append({
            "week": f"{wk[0]}-W{wk[1]:02d}",
            "n": n, "wins": wins,
            "wr": wins / n * 100 if n else 0,
            "pl": pl,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db"))
    trades.sort(key=lambda t: t["ts"])

    n = len(trades)
    if not n:
        print("No trades.")
        return

    starting = 10000.0
    timestamps, equity = equity_curve(trades, starting=starting)
    final = equity[-1]
    total_pl = final - starting
    return_pct = (final / starting - 1) * 100
    dd_pct, dd_peak, dd_trough = max_drawdown(equity)

    wins = sum(1 for t in trades if t["status"] == "WIN")
    losses = sum(1 for t in trades if t["status"] == "LOSS")
    wr = wins / n * 100

    sk = streaks(trades)
    print(f"=== TRADE NARRATIVE — {trades[0]['ts'].date()} -> {trades[-1]['ts'].date()} ===\n")
    print(f"Trades: {n} (W={wins} L={losses})")
    print(f"WR: {wr:.1f}%")
    print(f"Equity: ${starting:.0f} -> ${final:.0f} ({return_pct:+.2f}%)")
    print(f"Max DD: {dd_pct:.2f}% (peak idx {dd_peak} -> trough idx {dd_trough})")
    print(f"Longest WIN streak: {sk['WIN'][0]} ({sk['WIN'][1]} -> {sk['WIN'][2]})")
    print(f"Longest LOSS streak: {sk['LOSS'][0]} ({sk['LOSS'][1]} -> {sk['LOSS'][2]})")

    # Pivotal trades
    sorted_by_pl = sorted(trades, key=lambda t: t["profit"])
    print("\n=== Top 5 LOSSES ===")
    for t in sorted_by_pl[:5]:
        print(f"  #{t['id']} {t['ts'].date()} {t['direction']} {t['grade']} ${t['profit']:+.2f} ({t['pattern'][:40]})")

    print("\n=== Top 5 WINS ===")
    for t in sorted_by_pl[-5:][::-1]:
        print(f"  #{t['id']} {t['ts'].date()} {t['direction']} {t['grade']} ${t['profit']:+.2f} ({t['pattern'][:40]})")

    # Weekly
    wk = per_week_summary(trades)
    print(f"\n=== Per-week summary ({len(wk)} weeks) ===")
    print(f"{'week':<10} {'N':>4} {'WR':>6} {'P/L':>10}")
    for r in wk:
        print(f"{r['week']:<10} {r['n']:>4} {r['wr']:>5.1f}% ${r['pl']:>+8.2f}")

    if wk:
        best_wk = max(wk, key=lambda r: r["pl"])
        worst_wk = min(wk, key=lambda r: r["pl"])
        print(f"\nBest week: {best_wk['week']} ({best_wk['n']} trades, WR {best_wk['wr']:.0f}%, +${best_wk['pl']:.2f})")
        print(f"Worst week: {worst_wk['week']} ({worst_wk['n']} trades, WR {worst_wk['wr']:.0f}%, -${abs(worst_wk['pl']):.2f})")

    if args.output:
        out = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
        out.parent.mkdir(exist_ok=True, parents=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# Trade Narrative — {trades[0]['ts'].date()} -> {trades[-1]['ts'].date()}\n\n")
            f.write(f"- Trades: {n} (W={wins} L={losses}), WR {wr:.1f}%\n")
            f.write(f"- Equity: ${starting:.0f} -> ${final:.0f} ({return_pct:+.2f}%)\n")
            f.write(f"- Max DD: {dd_pct:.2f}%\n")
            f.write(f"- Longest LOSS streak: {sk['LOSS'][0]}\n\n")
            f.write("## Per-week\n\n| Week | N | WR | P/L |\n|---|---|---|---|\n")
            for r in wk:
                f.write(f"| {r['week']} | {r['n']} | {r['wr']:.1f}% | ${r['pl']:+.2f} |\n")
        print(f"\nWritten -> {out}")


if __name__ == "__main__":
    main()
