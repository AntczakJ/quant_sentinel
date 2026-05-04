"""
scripts/factor_pairs.py — analyze factor PAIRS for synergistic edge.

factor_predictive_power.py shows individual factor WR. This script
extends to pairs (and optionally triples) to find combinations that
together produce edge greater than the sum of parts.

Example: bos+choch alone might be weak, but bos+pin_bar might be strong.

Output: top 20 pairs by Δpp (delta vs cohort baseline) with N>=5.

Usage:
    python scripts/factor_pairs.py [--db both] [--min-n 5] [--triples]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, direction, status, profit, factors FROM trades "
        "WHERE status IN ('WIN','LOSS') AND factors IS NOT NULL"
    ).fetchall()
    out = []
    for r in rows:
        try:
            f = json.loads(r[4]) if r[4] else {}
        except Exception:
            f = {}
        # Only keep factors that are non-penalty (skip _penalty suffix)
        factors_set = {k for k, v in f.items() if v and not k.endswith("_penalty")}
        out.append({
            "id": r[0], "direction": r[1], "status": r[2],
            "profit": r[3] or 0, "factors": factors_set,
        })
    conn.close()
    return out


def compute_pair_edges(trades, min_n=5, baseline_wr=None):
    """For each pair of factors, compute WR when both present vs cohort baseline."""
    if baseline_wr is None:
        n_total = len(trades)
        wins_total = sum(1 for t in trades if t["status"] == "WIN")
        baseline_wr = wins_total / n_total * 100 if n_total else 0

    # Get all unique factors
    all_factors = set()
    for t in trades:
        all_factors.update(t["factors"])

    results = []
    for f1, f2 in combinations(sorted(all_factors), 2):
        with_pair = [t for t in trades if f1 in t["factors"] and f2 in t["factors"]]
        if len(with_pair) < min_n:
            continue
        n = len(with_pair)
        w = sum(1 for t in with_pair if t["status"] == "WIN")
        wr = w / n * 100
        delta = wr - baseline_wr
        avg_pl = sum(t["profit"] for t in with_pair) / n
        results.append({
            "pair": f"{f1} + {f2}",
            "n": n, "wins": w, "wr": wr,
            "delta_pp": delta,
            "avg_pl": avg_pl,
            "total_pl": avg_pl * n,
        })
    return sorted(results, key=lambda r: r["delta_pp"], reverse=True)


def compute_triple_edges(trades, min_n=5, baseline_wr=None, max_triples=10000):
    if baseline_wr is None:
        n_total = len(trades)
        baseline_wr = sum(1 for t in trades if t["status"] == "WIN") / n_total * 100

    all_factors = set()
    for t in trades:
        all_factors.update(t["factors"])

    # Limit combinatorial blow-up: only consider top 12 factors by frequency
    factor_counts = {}
    for t in trades:
        for f in t["factors"]:
            factor_counts[f] = factor_counts.get(f, 0) + 1
    top_factors = sorted(factor_counts, key=lambda f: -factor_counts[f])[:12]

    results = []
    n_combos = 0
    for f1, f2, f3 in combinations(sorted(top_factors), 3):
        if n_combos > max_triples:
            break
        n_combos += 1
        with_triple = [t for t in trades
                       if f1 in t["factors"] and f2 in t["factors"] and f3 in t["factors"]]
        if len(with_triple) < min_n:
            continue
        n = len(with_triple)
        w = sum(1 for t in with_triple if t["status"] == "WIN")
        wr = w / n * 100
        delta = wr - baseline_wr
        avg_pl = sum(t["profit"] for t in with_triple) / n
        results.append({
            "triple": f"{f1} + {f2} + {f3}",
            "n": n, "wins": w, "wr": wr,
            "delta_pp": delta,
            "avg_pl": avg_pl,
            "total_pl": avg_pl * n,
        })
    return sorted(results, key=lambda r: r["delta_pp"], reverse=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--triples", action="store_true")
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch_trades("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch_trades("data/backtest.db"))
    n = len(trades)
    if not n:
        print("No trades.")
        return

    wins = sum(1 for t in trades if t["status"] == "WIN")
    baseline = wins / n * 100
    print(f"COHORT: N={n}, baseline WR {baseline:.1f}%")
    print(f"All factor pairs with N>={args.min_n}:\n")

    pairs = compute_pair_edges(trades, min_n=args.min_n, baseline_wr=baseline)
    print(f"{'pair':<55} {'N':>4} {'WR':>6} {'delta':>6} {'P/L':>10}")
    for r in pairs[:25]:
        print(f"{r['pair']:<55} {r['n']:>4} {r['wr']:>5.1f}% {r['delta_pp']:>+5.1f}  ${r['total_pl']:>+8.2f}")

    if args.triples:
        print("\n" + "=" * 70)
        print(f"TRIPLES (top 15 by delta, min_n={args.min_n}):\n")
        triples = compute_triple_edges(trades, min_n=args.min_n, baseline_wr=baseline)
        print(f"{'triple':<60} {'N':>4} {'WR':>6} {'delta':>6}")
        for r in triples[:15]:
            print(f"{r['triple']:<60} {r['n']:>4} {r['wr']:>5.1f}% {r['delta_pp']:>+5.1f}")


if __name__ == "__main__":
    main()
