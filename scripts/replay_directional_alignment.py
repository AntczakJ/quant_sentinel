"""replay_directional_alignment.py — counterfactual replay for rejected setups.

Implements the spec at `docs/SHADOW_LOG_DIRECTIONAL_ALIGNMENT.md`. For
every row in `rejected_setups` with `would_have_won IS NULL`:

  1. Reconstruct counterfactual SL/TP from rejection-time price + ATR
     using snapshot params (`sl_atr_multiplier`, `sl_min_distance`,
     `target_rr`, plus a 4.0 floor for scalp TFs).
  2. Walk forward bar-by-bar in the local 5-min parquet warehouse,
     check whether SL or TP was hit first within the hold cap.
  3. Update `would_have_won` per row (1=TP, 0=SL, 2=time-exit win,
     3=time-exit loss).
  4. Aggregate per filter / TF / direction / week.

Deliberately reads the LOCAL warehouse — not TwelveData. Reasons:
  - 9k+ rejections × TwelveData would burn ~3 h of credit budget at
    55 / min cap. Warehouse is on disk, no API hits, runs in minutes.
  - Warehouse parquet was sourced from TwelveData spot, so the price
    series matches what the live scanner sees (no GC=F divergence).

Usage:
    python scripts/replay_directional_alignment.py
    python scripts/replay_directional_alignment.py --filter directional_alignment
    python scripts/replay_directional_alignment.py --since 2026-04-20 --tf 1h 4h
    python scripts/replay_directional_alignment.py --no-write   # dry-run, just print

Output:
    Console: aggregate WR / expectancy / per-bucket breakdowns.
    DB: writes back `would_have_won` on each replayed row (unless --no-write).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "sentinel.db"
WAREHOUSE_5M = REPO / "data" / "historical" / "XAU_USD" / "5min.parquet"

# Spec defaults — snapshot from 2026-04-20 baseline. Self-learning has
# probably mutated these in `dynamic_params` since, but we use the
# snapshot to keep the historical replay deterministic. Caller can
# override via CLI flags if a different param epoch is being studied.
DEFAULT_SL_ATR_MULT = 2.063
DEFAULT_SL_MIN_DIST = 6.587
DEFAULT_TARGET_RR = 1.963
SCALP_TFS = {"5m", "15m", "30m"}
SCALP_SL_FLOOR = 4.0  # `sl_floor` from finance.py:163

# Hold cap = 4h for both 1h and 4h setups (scalp time-exit, per spec).
# Stored in 5m bars: 4h × 12 bars/h = 48 bars max.
HOLD_CAP_BARS_BY_TF = {
    "5m": 48,    # 4h
    "15m": 48,   # 4h
    "30m": 48,   # 4h
    "1h": 48,    # 4h
    "4h": 48,    # 4h
}


@dataclass
class ReplayParams:
    sl_atr_mult: float = DEFAULT_SL_ATR_MULT
    sl_min_dist: float = DEFAULT_SL_MIN_DIST
    target_rr: float = DEFAULT_TARGET_RR


@dataclass
class ReplayOutcome:
    rejection_id: int
    timestamp: str
    timeframe: str
    direction: str
    entry: float
    sl: float
    tp: float
    sl_distance: float
    tp_distance: float
    # 1=TP win, 0=SL loss, 2=time-exit profit, 3=time-exit loss, None=skipped
    would_have_won: Optional[int] = None
    exit_reason: str = ""    # 'sl' | 'tp' | 'time_win' | 'time_loss' | 'skipped'
    bars_held: int = 0
    pnl_per_unit: float = 0.0   # exit_price - entry (LONG) / entry - exit_price (SHORT)
    skip_reason: str = ""


def load_warehouse(path: Path = WAREHOUSE_5M) -> pd.DataFrame:
    """Load 5m parquet, ensure datetime-indexed UTC, sorted ascending."""
    if not path.exists():
        raise FileNotFoundError(f"warehouse missing: {path}")
    df = pd.read_parquet(path)
    if "datetime" not in df.columns:
        raise ValueError("expected 'datetime' column in 5min.parquet")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df.set_index("datetime")
    return df


def fetch_rejections(
    conn: sqlite3.Connection,
    filter_name: Optional[str] = None,
    timeframes: Optional[list[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    only_unresolved: bool = True,
    limit: Optional[int] = None,
) -> list[tuple]:
    """Pull rejection rows ready for replay. Skips rows missing atr / price."""
    sql = ["""
        SELECT id, timestamp, timeframe, direction, price, atr, confluence_count, filter_name
        FROM rejected_setups
        WHERE atr IS NOT NULL AND atr > 0
          AND price IS NOT NULL AND price > 0
          AND direction IN ('LONG','SHORT')
    """]
    args: list = []
    if filter_name:
        sql.append("AND filter_name = ?")
        args.append(filter_name)
    if timeframes:
        placeholders = ",".join(["?"] * len(timeframes))
        sql.append(f"AND timeframe IN ({placeholders})")
        args.extend(timeframes)
    if since:
        sql.append("AND timestamp >= ?")
        args.append(since)
    if until:
        sql.append("AND timestamp <= ?")
        args.append(until)
    if only_unresolved:
        sql.append("AND would_have_won IS NULL")
    sql.append("ORDER BY timestamp ASC")
    if limit:
        sql.append(f"LIMIT {int(limit)}")
    return conn.execute(" ".join(sql), args).fetchall()


def compute_levels(direction: str, price: float, atr: float, tf: str,
                   p: ReplayParams) -> tuple[float, float, float, float]:
    """Return (sl, tp, sl_distance, tp_distance) per spec."""
    sl_distance = max(atr * p.sl_atr_mult, p.sl_min_dist)
    if tf in SCALP_TFS:
        sl_distance = max(sl_distance, SCALP_SL_FLOOR)
    tp_distance = sl_distance * p.target_rr
    if direction == "LONG":
        return price - sl_distance, price + tp_distance, sl_distance, tp_distance
    return price + sl_distance, price - tp_distance, sl_distance, tp_distance


def replay_one(
    rejection_id: int, timestamp: str, timeframe: str, direction: str,
    price: float, atr: float, filter_name: str,
    warehouse: pd.DataFrame, p: ReplayParams,
) -> ReplayOutcome:
    """Walk forward bar-by-bar, return outcome."""
    sl, tp, sl_dist, tp_dist = compute_levels(direction, price, atr, timeframe, p)
    out = ReplayOutcome(
        rejection_id=rejection_id, timestamp=timestamp, timeframe=timeframe,
        direction=direction, entry=price, sl=sl, tp=tp,
        sl_distance=sl_dist, tp_distance=tp_dist,
    )

    try:
        ts = pd.Timestamp(timestamp, tz="UTC")
    except (ValueError, TypeError):
        out.skip_reason = "bad timestamp"
        out.exit_reason = "skipped"
        return out

    # Find next bar at or after rejection timestamp. Use searchsorted
    # on the index since it's sorted ascending.
    try:
        start_idx = warehouse.index.searchsorted(ts, side="left")
    except Exception:
        out.skip_reason = "warehouse search failed"
        out.exit_reason = "skipped"
        return out

    if start_idx >= len(warehouse):
        out.skip_reason = "after warehouse end"
        out.exit_reason = "skipped"
        return out

    hold_cap = HOLD_CAP_BARS_BY_TF.get(timeframe, 48)
    forward = warehouse.iloc[start_idx:start_idx + hold_cap]
    if len(forward) == 0:
        out.skip_reason = "no forward bars"
        out.exit_reason = "skipped"
        return out

    # Walk bar-by-bar. If both SL and TP triggered in same bar, assume SL
    # first (pessimistic — matches spec).
    for i, (idx_ts, bar) in enumerate(forward.iterrows()):
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        if direction == "LONG":
            sl_hit = bar_low <= sl
            tp_hit = bar_high >= tp
        else:  # SHORT
            sl_hit = bar_high >= sl
            tp_hit = bar_low <= tp

        if sl_hit and tp_hit:
            # pessimistic — SL first
            out.would_have_won = 0
            out.exit_reason = "sl"
            out.bars_held = i + 1
            out.pnl_per_unit = -sl_dist if direction == "LONG" else -sl_dist
            return out
        if sl_hit:
            out.would_have_won = 0
            out.exit_reason = "sl"
            out.bars_held = i + 1
            out.pnl_per_unit = -sl_dist
            return out
        if tp_hit:
            out.would_have_won = 1
            out.exit_reason = "tp"
            out.bars_held = i + 1
            out.pnl_per_unit = tp_dist
            return out

    # Time exit — close at last bar's close, compare to entry
    last_close = float(forward.iloc[-1]["close"])
    if direction == "LONG":
        pnl = last_close - price
    else:
        pnl = price - last_close
    out.bars_held = len(forward)
    out.pnl_per_unit = pnl
    if pnl > 0:
        out.would_have_won = 2
        out.exit_reason = "time_win"
    else:
        out.would_have_won = 3
        out.exit_reason = "time_loss"
    return out


def aggregate(outcomes: list[ReplayOutcome]) -> dict:
    """Per-bucket WR + expectancy summaries.

    **Two parallel WR metrics** because they answer different questions:
      - **WR_strict**: TP-hits / (TP-hits + SL-hits) — only counts setups
        that actually resolved at a level. Ignores time-exits. The bar
        a real trade has to clear (cover spread + slippage to bank R).
      - **WR_loose**: any-positive / total — counts time-exits with PnL>0
        as wins. Easy to confuse "barely positive close" with edge.
        Useful for completeness but misleading as headline.

    **Expectancy in R** uses actual `pnl_per_unit / sl_distance` per row
    so time-exits contribute their fractional R, not a full +R_target
    or -1R as the original spec read suggested. Real-world equivalent:
    closing at exit with whatever the price delta was.
    """
    resolved = [o for o in outcomes if o.would_have_won is not None]
    if not resolved:
        return {"n_resolved": 0, "n_skipped": len(outcomes)}

    n = len(resolved)
    tp_hits = sum(1 for o in resolved if o.would_have_won == 1)
    sl_hits = sum(1 for o in resolved if o.would_have_won == 0)
    time_wins = sum(1 for o in resolved if o.would_have_won == 2)
    time_losses = sum(1 for o in resolved if o.would_have_won == 3)
    n_resolved_at_level = tp_hits + sl_hits

    wr_strict = tp_hits / n_resolved_at_level if n_resolved_at_level else 0.0
    wr_loose = (tp_hits + time_wins) / n if n else 0.0
    avg_R_target = sum(o.tp_distance / o.sl_distance for o in resolved) / n

    # True expectancy: per-row R = pnl_per_unit / sl_distance.
    # SL-hit rows have pnl = -sl_distance, so R = -1.
    # TP-hit rows have pnl = tp_distance, so R = target_rr (~1.96).
    # Time-exit rows have pnl = whatever, R = small fraction.
    rs: list[float] = []
    for o in resolved:
        if o.sl_distance and o.sl_distance > 0:
            rs.append(o.pnl_per_unit / o.sl_distance)
    expectancy_R = sum(rs) / len(rs) if rs else 0.0
    # Tail risk
    rs_sorted = sorted(rs)
    p10 = rs_sorted[max(0, int(len(rs_sorted) * 0.10) - 1)] if rs_sorted else 0.0

    by_tf: dict[str, dict] = defaultdict(lambda: {"n": 0, "tp": 0, "sl": 0, "time_win": 0, "time_loss": 0, "exp_R_sum": 0.0})
    by_dir: dict[str, dict] = defaultdict(lambda: {"n": 0, "tp": 0, "sl": 0, "exp_R_sum": 0.0})
    by_week: dict[str, dict] = defaultdict(lambda: {"n": 0, "tp": 0, "sl": 0, "exp_R_sum": 0.0})

    for o in resolved:
        r = (o.pnl_per_unit / o.sl_distance) if o.sl_distance else 0.0
        tf_d = by_tf[o.timeframe]
        tf_d["n"] += 1
        tf_d["exp_R_sum"] += r
        if o.would_have_won == 1: tf_d["tp"] += 1
        elif o.would_have_won == 0: tf_d["sl"] += 1
        elif o.would_have_won == 2: tf_d["time_win"] += 1
        elif o.would_have_won == 3: tf_d["time_loss"] += 1

        d_d = by_dir[o.direction]
        d_d["n"] += 1
        d_d["exp_R_sum"] += r
        if o.would_have_won == 1: d_d["tp"] += 1
        elif o.would_have_won == 0: d_d["sl"] += 1

        try:
            week = pd.Timestamp(o.timestamp).strftime("%G-W%V")
        except Exception:
            week = "unknown"
        w_d = by_week[week]
        w_d["n"] += 1
        w_d["exp_R_sum"] += r
        if o.would_have_won == 1: w_d["tp"] += 1
        elif o.would_have_won == 0: w_d["sl"] += 1

    return {
        "n_resolved": n,
        "n_skipped": len(outcomes) - n,
        "tp_hits": tp_hits, "sl_hits": sl_hits,
        "time_wins": time_wins, "time_losses": time_losses,
        "n_resolved_at_level": n_resolved_at_level,
        "win_rate_strict": wr_strict,
        "win_rate_loose": wr_loose,
        "avg_R_target": avg_R_target,
        "expectancy_R": expectancy_R,
        "p10_R": p10,
        "by_tf": dict(by_tf),
        "by_direction": dict(by_dir),
        "by_week": dict(by_week),
    }


def write_back(conn: sqlite3.Connection, outcomes: list[ReplayOutcome]) -> int:
    """Bulk update `would_have_won`. Returns rows updated."""
    rows_to_update = [(o.would_have_won, o.rejection_id) for o in outcomes
                      if o.would_have_won is not None]
    if not rows_to_update:
        return 0
    conn.executemany(
        "UPDATE rejected_setups SET would_have_won = ? WHERE id = ?",
        rows_to_update,
    )
    conn.commit()
    return len(rows_to_update)


def print_aggregate(agg: dict) -> None:
    print("=" * 78)
    print("REPLAY AGGREGATE")
    print("=" * 78)
    print(f"Resolved: {agg['n_resolved']}  |  Skipped: {agg['n_skipped']}")
    if agg.get("n_resolved", 0) == 0:
        return

    n_lvl = agg["n_resolved_at_level"]
    print(f"\nResolved at level (TP or SL): {n_lvl}/{agg['n_resolved']}  "
          f"({100*n_lvl/agg['n_resolved']:.1f}%)")
    print(f"  TP hits: {agg['tp_hits']}   SL hits: {agg['sl_hits']}")
    print(f"  Time-exit: wins {agg['time_wins']}, losses {agg['time_losses']}")
    print()
    print(f"WR_strict (TP / TP+SL):    {agg['win_rate_strict']*100:>5.1f}%   "
          f"← real edge — covers spread/slippage")
    print(f"WR_loose  (any positive):  {agg['win_rate_loose']*100:>5.1f}%   "
          f"← lenient — counts +0.01 closes")
    print(f"Avg target R:              {agg['avg_R_target']:>5.2f}")
    print(f"Expectancy (per-row R):    {agg['expectancy_R']:+.3f} R")
    print(f"P10 R (left tail):         {agg['p10_R']:+.3f} R")
    print()
    print("Per timeframe (TP / SL / time-win / time-loss / expectancy R):")
    for tf, d in sorted(agg["by_tf"].items()):
        exp_r = d["exp_R_sum"] / d["n"] if d["n"] else 0
        # WR_strict per TF
        n_lvl_tf = d["tp"] + d["sl"]
        wr_strict = d["tp"] / n_lvl_tf if n_lvl_tf else 0
        print(f"  {tf:>4s}: n={d['n']:>5d}  TP={d['tp']:>4d}  SL={d['sl']:>4d}  "
              f"tw={d['time_win']:>3d}  tl={d['time_loss']:>3d}  "
              f"WR_strict={wr_strict*100:>5.1f}%  E={exp_r:+.3f}R")
    print()
    print("Per direction:")
    for d_name, d in sorted(agg["by_direction"].items()):
        n_lvl_d = d["tp"] + d["sl"]
        wr_strict = d["tp"] / n_lvl_d if n_lvl_d else 0
        exp_r = d["exp_R_sum"] / d["n"] if d["n"] else 0
        print(f"  {d_name:>5s}: n={d['n']:>5d}  TP={d['tp']:>4d}  SL={d['sl']:>4d}  "
              f"WR_strict={wr_strict*100:>5.1f}%  E={exp_r:+.3f}R")
    print()
    print("Per week (top 8 by sample):")
    sorted_weeks = sorted(agg["by_week"].items(), key=lambda kv: -kv[1]["n"])[:8]
    for week, d in sorted_weeks:
        exp_r = d["exp_R_sum"] / d["n"] if d["n"] else 0
        n_lvl_w = d["tp"] + d["sl"]
        wr_strict = d["tp"] / n_lvl_w if n_lvl_w else 0
        print(f"  {week}: n={d['n']:>4d}  TP={d['tp']:>3d}  SL={d['sl']:>3d}  "
              f"WR_strict={wr_strict*100:>5.1f}%  E={exp_r:+.3f}R")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--filter", default=None,
                    help="Filter by filter_name (e.g. 'directional_alignment'). "
                         "Default: all unresolved.")
    ap.add_argument("--tf", nargs="+", default=None,
                    help="Restrict to timeframes (e.g. --tf 1h 4h)")
    ap.add_argument("--since", default=None,
                    help="Only rows with timestamp >= this (YYYY-MM-DD)")
    ap.add_argument("--until", default=None,
                    help="Only rows with timestamp <= this (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap rows processed (smoke test)")
    ap.add_argument("--no-write", action="store_true",
                    help="Don't UPDATE the DB — print only")
    ap.add_argument("--include-resolved", action="store_true",
                    help="Re-replay rows that already have would_have_won")
    ap.add_argument("--sl-atr-mult", type=float, default=DEFAULT_SL_ATR_MULT)
    ap.add_argument("--sl-min-dist", type=float, default=DEFAULT_SL_MIN_DIST)
    ap.add_argument("--target-rr", type=float, default=DEFAULT_TARGET_RR)
    args = ap.parse_args()

    p = ReplayParams(
        sl_atr_mult=args.sl_atr_mult,
        sl_min_dist=args.sl_min_dist,
        target_rr=args.target_rr,
    )

    print(f"[replay] DB: {DB}")
    print(f"[replay] params: sl_atr_mult={p.sl_atr_mult}  "
          f"sl_min_dist={p.sl_min_dist}  target_rr={p.target_rr}")

    print(f"[replay] loading warehouse: {WAREHOUSE_5M}", flush=True)
    t0 = time.time()
    warehouse = load_warehouse(WAREHOUSE_5M)
    print(f"[replay] warehouse loaded: {len(warehouse):,} bars  "
          f"({warehouse.index[0]} → {warehouse.index[-1]})  "
          f"in {time.time()-t0:.1f}s")

    conn = sqlite3.connect(DB)
    rejections = fetch_rejections(
        conn,
        filter_name=args.filter,
        timeframes=args.tf,
        since=args.since,
        until=args.until,
        only_unresolved=not args.include_resolved,
        limit=args.limit,
    )
    print(f"[replay] eligible rejections: {len(rejections):,}", flush=True)
    if not rejections:
        print("[replay] nothing to replay")
        return 0

    outcomes: list[ReplayOutcome] = []
    t0 = time.time()
    skip_counter: Counter = Counter()
    for i, (rid, ts, tf, dir_, price, atr, confl, filt) in enumerate(rejections):
        try:
            outcome = replay_one(
                rid, ts, tf, dir_, float(price), float(atr), filt,
                warehouse, p,
            )
            outcomes.append(outcome)
            if outcome.skip_reason:
                skip_counter[outcome.skip_reason] += 1
        except Exception as e:
            skip_counter[f"exception: {type(e).__name__}"] += 1
        # Progress every 1000
        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed else 0
            eta = (len(rejections) - (i + 1)) / rate if rate else 0
            print(f"[replay] {i+1}/{len(rejections)}  ({rate:.0f}/s, ETA {eta:.0f}s)",
                  flush=True)
    print(f"[replay] processed {len(outcomes):,} in {time.time()-t0:.1f}s")
    if skip_counter:
        print(f"[replay] skip reasons: {dict(skip_counter)}")

    agg = aggregate(outcomes)
    print_aggregate(agg)

    if not args.no_write:
        n_updated = write_back(conn, outcomes)
        print(f"[replay] DB updated: {n_updated:,} rows")
    else:
        print("[replay] --no-write: DB not modified")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
