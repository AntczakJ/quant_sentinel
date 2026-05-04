"""
scripts/factor_predictive_power.py — measure which scoring factors actually
predict WIN vs LOSS on closed trades.

Reads `trades.factors` (JSON) + `trades.status` from BOTH sentinel.db (live)
AND backtest.db (in-flight backtest), computes per-factor:
  - n_trades_with_factor
  - win_rate_with_factor (WR_w)
  - win_rate_without_factor (WR_wo)
  - delta_pp = WR_w - WR_wo
  - p-value (chi-square test for independence)

Output: ranked table + concrete recommendations for which factors to
weight up/down in `dynamic_params.weight_*`.

This complements the 5-agent audit by giving DATA-driven evidence vs
agent surface-pattern claims.
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from scipy.stats import chi2_contingency

ROOT = Path(__file__).resolve().parent.parent


def fetch_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, direction, status, profit, setup_grade, setup_score,
               factors, pattern, session, vol_regime, timestamp
        FROM trades
        WHERE status IN ('WIN', 'LOSS') AND factors IS NOT NULL
    """).fetchall()
    cols = ["id", "direction", "status", "profit", "setup_grade", "setup_score",
            "factors", "pattern", "session", "vol_regime", "timestamp"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["factors_dict"] = json.loads(d["factors"]) if d["factors"] else {}
        except Exception:
            d["factors_dict"] = {}
        out.append(d)
    conn.close()
    return out


def factor_table(trades: list[dict], min_n: int = 5) -> list[dict]:
    """For each factor key, compute WR-with vs WR-without + chi-square."""
    factor_set = set()
    for t in trades:
        factor_set.update(t["factors_dict"].keys())

    results = []
    for factor in factor_set:
        with_factor = [t for t in trades if t["factors_dict"].get(factor)]
        without_factor = [t for t in trades if not t["factors_dict"].get(factor)]
        if len(with_factor) < min_n:
            continue
        n_w = len(with_factor)
        n_wo = len(without_factor)
        wins_w = sum(1 for t in with_factor if t["status"] == "WIN")
        wins_wo = sum(1 for t in without_factor if t["status"] == "WIN")
        wr_w = wins_w / n_w * 100 if n_w else 0
        wr_wo = wins_wo / n_wo * 100 if n_wo else 0
        delta = wr_w - wr_wo

        # Chi-square test
        try:
            table = [[wins_w, n_w - wins_w], [wins_wo, n_wo - wins_wo]]
            chi2, p, _, _ = chi2_contingency(table)
        except Exception:
            chi2, p = 0, 1.0

        # Per-direction
        long_with = [t for t in with_factor if t["direction"] == "LONG"]
        short_with = [t for t in with_factor if t["direction"] == "SHORT"]
        long_wr = (sum(1 for t in long_with if t["status"] == "WIN") / len(long_with) * 100) if long_with else None
        short_wr = (sum(1 for t in short_with if t["status"] == "WIN") / len(short_with) * 100) if short_with else None

        # Avg P&L impact
        avg_profit_with = sum(t.get("profit") or 0 for t in with_factor) / max(n_w, 1)
        avg_profit_wo = sum(t.get("profit") or 0 for t in without_factor) / max(n_wo, 1)

        results.append({
            "factor": factor,
            "n_with": n_w,
            "n_without": n_wo,
            "wr_with": wr_w,
            "wr_without": wr_wo,
            "delta_pp": delta,
            "chi2": chi2,
            "p_value": p,
            "long_wr": long_wr,
            "long_n": len(long_with),
            "short_wr": short_wr,
            "short_n": len(short_with),
            "avg_profit_with": avg_profit_with,
            "avg_profit_without": avg_profit_wo,
        })
    return sorted(results, key=lambda x: x["delta_pp"], reverse=True)


def grade_table(trades: list[dict]) -> list[dict]:
    """WR per setup_grade — to validate grading is informative."""
    by_grade = defaultdict(list)
    for t in trades:
        by_grade[t.get("setup_grade") or "?"].append(t)
    out = []
    for g, ts in sorted(by_grade.items()):
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        out.append({
            "grade": g, "n": n, "wins": w,
            "wr": w / n * 100 if n else 0,
            "avg_profit": sum(t.get("profit") or 0 for t in ts) / max(n, 1),
        })
    return out


def session_table(trades: list[dict]) -> list[dict]:
    by_session = defaultdict(list)
    for t in trades:
        by_session[t.get("session") or "?"].append(t)
    out = []
    for s, ts in by_session.items():
        n = len(ts)
        w = sum(1 for t in ts if t["status"] == "WIN")
        out.append({
            "session": s, "n": n, "wins": w,
            "wr": w / n * 100 if n else 0,
            "avg_profit": sum(t.get("profit") or 0 for t in ts) / max(n, 1),
        })
    return sorted(out, key=lambda x: x["wr"], reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=5,
                    help="Minimum samples to include a factor (default 5)")
    ap.add_argument("--output", default=None, help="Write summary MD to path")
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        live = fetch_trades("data/sentinel.db")
        for t in live:
            t["source"] = "live"
        trades.extend(live)
        print(f"Live closed trades: {len(live)}")
    if args.db in ("backtest", "both"):
        bt = fetch_trades("data/backtest.db")
        for t in bt:
            t["source"] = "backtest"
        trades.extend(bt)
        print(f"Backtest closed trades: {len(bt)}")

    if not trades:
        print("No trades.")
        return

    n = len(trades)
    wins = sum(1 for t in trades if t["status"] == "WIN")
    print(f"\nTOTAL: {n} trades, WR={wins/n*100:.1f}%\n")

    # Direction split
    long_t = [t for t in trades if t["direction"] == "LONG"]
    short_t = [t for t in trades if t["direction"] == "SHORT"]
    print(f"LONG : N={len(long_t)} WR={sum(1 for t in long_t if t['status']=='WIN')/max(len(long_t),1)*100:.1f}%")
    print(f"SHORT: N={len(short_t)} WR={sum(1 for t in short_t if t['status']=='WIN')/max(len(short_t),1)*100:.1f}%\n")

    # Factor table
    print("=" * 100)
    print(f"{'factor':<30} {'N_w':>5} {'N_wo':>5} {'WR_w':>6} {'WR_wo':>7} {'delta':>7} {'p-val':>7} {'L_WR':>6} {'L_N':>4} {'S_WR':>6} {'S_N':>4}")
    print("=" * 100)
    table = factor_table(trades, min_n=args.min_n)
    for row in table:
        sig = "*" if row["p_value"] < 0.05 else " "
        l_wr = f"{row['long_wr']:.0f}%" if row['long_wr'] is not None else "  -"
        s_wr = f"{row['short_wr']:.0f}%" if row['short_wr'] is not None else "  -"
        print(f"{row['factor']:<30} {row['n_with']:>5} {row['n_without']:>5} "
              f"{row['wr_with']:>5.1f}% {row['wr_without']:>6.1f}% {row['delta_pp']:>+6.1f} "
              f"{row['p_value']:>6.3f}{sig} {l_wr:>6} {row['long_n']:>4} {s_wr:>6} {row['short_n']:>4}")

    print("\n" + "=" * 60)
    print("Setup grade WR")
    print("=" * 60)
    for row in grade_table(trades):
        print(f"  {row['grade']:<5} N={row['n']:>4} WR={row['wr']:>5.1f}%  avg_pl=${row['avg_profit']:+.2f}")

    print("\n" + "=" * 60)
    print("Session WR")
    print("=" * 60)
    for row in session_table(trades):
        print(f"  {row['session']:<10} N={row['n']:>4} WR={row['wr']:>5.1f}%  avg_pl=${row['avg_profit']:+.2f}")

    # Recommendations
    print("\n" + "=" * 60)
    print("RECOMMENDATIONS (factors with significant edge AND n_with >= 10)")
    print("=" * 60)
    candidates = [r for r in table
                  if r["p_value"] < 0.10 and r["n_with"] >= 10
                  and abs(r["delta_pp"]) >= 10]
    if not candidates:
        print("  None — sample too small or no significant edges yet.")
    else:
        for r in candidates:
            direction = "BOOST" if r["delta_pp"] > 0 else "PENALIZE"
            print(f"  {direction:<8} weight_{r['factor']:<25} "
                  f"(N={r['n_with']}, delta{r['delta_pp']:+.1f}pp, p={r['p_value']:.3f})")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                # Re-run to capture
                pass
            # Simpler: just dump summary
            f.write(f"# Factor Predictive Power — {n} trades, WR {wins/n*100:.1f}%\n\n")
            f.write("| Factor | N_with | WR_w | WR_wo | delta | p-val | L_WR (N) | S_WR (N) |\n")
            f.write("|---|---|---|---|---|---|---|---|\n")
            for row in table:
                l_wr = f"{row['long_wr']:.0f}%" if row['long_wr'] is not None else "-"
                s_wr = f"{row['short_wr']:.0f}%" if row['short_wr'] is not None else "-"
                sig = " *" if row["p_value"] < 0.05 else ""
                f.write(f"| {row['factor']} | {row['n_with']} | {row['wr_with']:.1f}% | "
                        f"{row['wr_without']:.1f}% | {row['delta_pp']:+.1f} | {row['p_value']:.3f}{sig} | "
                        f"{l_wr} ({row['long_n']}) | {s_wr} ({row['short_n']}) |\n")
        print(f"\nSummary written to {args.output}")


if __name__ == "__main__":
    main()
