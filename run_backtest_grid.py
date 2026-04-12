#!/usr/bin/env python3
"""run_backtest_grid.py - Two-stage walk-forward parameter grid search.

Sweeps production strategy parameters (min_confidence, sl_atr, target_rr,
partial_close, risk_percent) through a two-stage pipeline:

  Stage A (pre-filter): every cell on a single short window. Cheap.
  Stage B (deep eval):  top-N survivors from Stage A, each evaluated
                        with walk-forward across N windows, plus a
                        Monte Carlo bootstrap per cell for confidence
                        intervals on return and drawdown.

Every completed cell is written to `reports/wf_grid_<name>/cell_<hash>.json`
the moment it finishes, so an interrupted run resumes by skipping cells
already on disk.

Safety
------
Isolation enforced via src/backtest/isolation — writes go to
data/backtest.db, never to data/sentinel.db. Each cell resets the
backtest DB and applies its parameters to dynamic_params (where
finance.calculate_position reads them) before running.

Usage
-----
  # Smoke (3 cells, tiny; safe to run next to an active RL sweep):
  python run_backtest_grid.py --smoke

  # Default two-stage run (~4-6 h; wait for the RL sweep to finish):
  python run_backtest_grid.py --days 14 --windows 4 --mc 500

  # Stage A only (fast pre-filter):
  python run_backtest_grid.py --days 7 --stage a

  # Stage B only, picking the top-12 from a previous Stage A:
  python run_backtest_grid.py --stage b --top-n 12 \
      --stage-a-report reports/wf_grid_default/stage_a.json

  # Inspect an existing grid's leaderboard (no new runs):
  python run_backtest_grid.py --report --name default

Bug fix vs. the previous version
--------------------------------
The prior script iterated `sl_atr_mult` and `target_rr` but only
propagated `min_confidence` (via QUANT_BACKTEST_MIN_CONF). SL/RR were
silently ignored, so the whole grid effectively varied only one knob.
This version writes sl_atr_multiplier / tp_to_sl_ratio / risk_percent
into dynamic_params before each run so they actually take effect.
"""

from __future__ import annotations

# --- Isolation FIRST (before any src.* imports) --------------------------
from src.backtest.isolation import enforce_isolation
enforce_isolation("data/backtest.db")

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import statistics
import time
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


# -------------------------------------------------------------------------
# Grid spec
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class CellParams:
    min_confidence: float
    sl_atr_mult: float
    target_rr: float
    partial_close: bool
    risk_percent: float

    def cell_hash(self) -> str:
        raw = f"{self.min_confidence:.4f}|{self.sl_atr_mult:.3f}|{self.target_rr:.3f}|" \
              f"{int(self.partial_close)}|{self.risk_percent:.4f}"
        return hashlib.sha1(raw.encode()).hexdigest()[:10]

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["cell_hash"] = self.cell_hash()
        return d


def build_grid(smoke: bool = False) -> List[CellParams]:
    """Construct the parameter grid. Tune here to add / remove dimensions."""
    if smoke:
        # 3 cells, fast enough that it won't stress CPU much.
        return [
            CellParams(0.50, 1.5, 2.5, False, 1.0),
            CellParams(0.55, 2.0, 2.5, True, 1.0),
            CellParams(0.40, 1.5, 3.0, False, 2.0),
        ]
    mc_vals = (0.40, 0.50, 0.55, 0.60)
    sl_vals = (1.5, 2.0)
    rr_vals = (2.0, 2.5, 3.0)
    partial = (False, True)
    risk = (1.0, 2.0)
    return [
        CellParams(mc, sl, rr, pc, rp)
        for mc, sl, rr, pc, rp in itertools.product(
            mc_vals, sl_vals, rr_vals, partial, risk)
    ]


# -------------------------------------------------------------------------
# Cell execution — sets DB params then runs the existing backtest harness
# -------------------------------------------------------------------------

def _apply_params_to_db(params: CellParams) -> None:
    """Write params into data/backtest.db's dynamic_params so that
    finance.calculate_position reads them on the next run."""
    from src.core.database import NewsDB
    db = NewsDB()
    db.set_param("sl_atr_multiplier", params.sl_atr_mult)
    db.set_param("tp_to_sl_ratio", params.target_rr)
    db.set_param("risk_percent", params.risk_percent)


def _set_env_for_cell(params: CellParams) -> None:
    os.environ["QUANT_BACKTEST_MIN_CONF"] = f"{params.min_confidence:.4f}"
    if params.partial_close:
        os.environ["QUANT_BACKTEST_PARTIAL"] = "1"
    else:
        os.environ.pop("QUANT_BACKTEST_PARTIAL", None)


def _make_bt_args(days: int, step_minutes: int,
                  start: Optional[str] = None,
                  end: Optional[str] = None,
                  symbol: str = "XAU/USD",
                  yf: str = "GC=F") -> Any:
    """Build the args namespace consumed by run_production_backtest._run_backtest."""
    class _A:  # duck-typed argparse.Namespace
        pass
    a = _A()
    a.symbol = symbol
    a.yf = yf
    a.days = days
    a.start = start
    a.end = end
    a.step_minutes = step_minutes
    a.reset = True
    a.no_cache = False
    a.resume = False
    a.checkpoint_every = 100
    a.strict = False
    return a


async def _run_single_window(days: int, step_minutes: int,
                             start: Optional[str] = None,
                             end: Optional[str] = None) -> Dict[str, Any]:
    """One backtest pass over one window. Returns stats dict."""
    from run_production_backtest import _reset_backtest_db, _run_backtest
    _reset_backtest_db()
    return await _run_backtest(_make_bt_args(days, step_minutes, start, end))


def prefetch_shared_provider(symbol: str = "XAU/USD",
                             yf_symbol: str = "GC=F",
                             days: int = 60) -> None:
    """Fetch HistoricalProvider once so every cell in the sweep reuses the
    same in-memory DataFrames. Saves 96 cells x 4 TFs worth of parquet
    reads (~2-5 min on a full grid) and eliminates a class of bugs where
    a mid-grid cache TTL expiry would silently refresh only some cells."""
    from run_production_backtest import set_shared_provider
    from src.backtest.historical_provider import HistoricalProvider
    period_for_fetch = f"{max(days, 60)}d"
    provider = HistoricalProvider.from_yfinance(
        symbol=symbol, yf_symbol=yf_symbol, period=period_for_fetch,
        intervals=("5m", "15m", "1h", "4h"), use_cache=True,
    )
    set_shared_provider(provider, symbol=symbol, yf_symbol=yf_symbol)
    print(f"[grid] shared provider prefetched for {yf_symbol} ({period_for_fetch})")


def _collect_analytics() -> Dict[str, Any]:
    """Call into src/backtest/analytics + monte_carlo after a run."""
    out: Dict[str, Any] = {}
    try:
        from src.backtest.analytics import (
            compute_sharpe_sortino_calmar, compute_expectancy)
        sharpe = compute_sharpe_sortino_calmar() or {}
        exp = compute_expectancy() or {}
        out["sharpe"] = sharpe.get("sharpe")
        out["sortino"] = sharpe.get("sortino")
        out["calmar"] = sharpe.get("calmar")
        out["expectancy_usd"] = exp.get("expectancy_per_trade_usd")
    except Exception as e:
        out["analytics_error"] = str(e)[:120]
    return out


def _monte_carlo(n_sims: int) -> Dict[str, Any]:
    if n_sims <= 0:
        return {}
    try:
        from run_production_backtest import _monte_carlo_analysis
        return _monte_carlo_analysis(n_simulations=n_sims)
    except Exception as e:
        return {"mc_error": str(e)[:120]}


def _walk_forward_windows(total_days: int, n_windows: int) -> List[Tuple[str, str]]:
    """Return list of (start_iso, end_iso) non-overlapping windows.

    The newest window ends today; earlier windows step back by chunk days.
    """
    if n_windows <= 1:
        return [(None, None)]
    chunk = max(total_days // n_windows, 1)
    today = date.today()
    out: List[Tuple[str, str]] = []
    for w in range(n_windows):
        end = today - timedelta(days=w * chunk)
        start = end - timedelta(days=chunk)
        out.append((start.isoformat(), end.isoformat()))
    return out


def run_cell(params: CellParams,
             days: int,
             step_minutes: int,
             windows: int,
             mc_sims: int) -> Dict[str, Any]:
    """Run one grid cell end-to-end. Returns a fully-populated result dict."""
    _apply_params_to_db(params)
    _set_env_for_cell(params)
    t0 = time.time()

    wf_results: List[Dict[str, Any]] = []
    for (start, end) in _walk_forward_windows(days, windows):
        _apply_params_to_db(params)  # reset wipes DB, so re-apply every window
        try:
            stats = asyncio.run(_run_single_window(days // max(windows, 1),
                                                   step_minutes, start, end))
        except Exception as e:
            wf_results.append({"start": start, "end": end, "error": str(e)[:160]})
            continue
        stats = dict(stats)
        stats.update(_collect_analytics())
        stats["start"] = start
        stats["end"] = end
        wf_results.append(stats)

    # Aggregate across windows (mean + stdev of the core metrics).
    agg = _aggregate_windows(wf_results)

    # MC runs on the LAST window's trades only (backtest.db reflects it).
    # For a proper cross-window MC we would need to union trade tables — not
    # worth the complexity; last-window MC still answers "is this cell's edge
    # order-independent?" on the same data scale.
    mc = _monte_carlo(mc_sims) if mc_sims > 0 else {}

    return {
        "params": params.as_dict(),
        "windows": wf_results,
        "agg": agg,
        "mc": mc,
        "elapsed_sec": round(time.time() - t0, 1),
    }


def _aggregate_windows(windows: List[Dict[str, Any]]) -> Dict[str, Any]:
    def _collect(key):
        vs = [w.get(key) for w in windows
              if isinstance(w.get(key), (int, float))]
        return vs
    def _mean(vs):
        return round(statistics.mean(vs), 4) if vs else None
    def _stdev(vs):
        return round(statistics.stdev(vs), 4) if len(vs) > 1 else 0.0

    out: Dict[str, Any] = {"n_windows": len(windows),
                           "n_errors": sum(1 for w in windows if "error" in w)}
    for key in ("return_pct", "win_rate_pct", "max_drawdown_pct",
                "profit_factor", "sharpe", "sortino", "calmar",
                "expectancy_usd", "total_trades"):
        vs = _collect(key)
        out[f"{key}_mean"] = _mean(vs)
        out[f"{key}_stdev"] = _stdev(vs)
    return out


# -------------------------------------------------------------------------
# Resume-friendly persistence (per-cell JSON)
# -------------------------------------------------------------------------

def _grid_dir(name: str) -> Path:
    return Path("reports") / f"wf_grid_{name}"


def _cell_path(name: str, params: CellParams) -> Path:
    return _grid_dir(name) / f"cell_{params.cell_hash()}.json"


def save_cell(name: str, params: CellParams, result: Dict[str, Any]) -> None:
    path = _cell_path(name, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")


def load_completed(name: str) -> Dict[str, Dict[str, Any]]:
    """Return {cell_hash: result_dict} for every cell JSON already on disk."""
    out: Dict[str, Dict[str, Any]] = {}
    d = _grid_dir(name)
    if not d.exists():
        return out
    for p in d.glob("cell_*.json"):
        try:
            data = json.loads(p.read_text())
            h = data.get("params", {}).get("cell_hash")
            if h:
                out[h] = data
        except Exception:
            continue
    return out


# -------------------------------------------------------------------------
# Ranking: composite score + Pareto front
# -------------------------------------------------------------------------

def composite_score(agg: Dict[str, Any]) -> Optional[float]:
    """Single number summarizing a cell. Higher is better.

    0.4 * sharpe + 0.3 * calmar + 0.3 * PF — all read from *_mean.
    Cells with None / zero trades return None so they sort last.
    """
    sharpe = agg.get("sharpe_mean")
    calmar = agg.get("calmar_mean")
    pf = agg.get("profit_factor_mean")
    if sharpe is None or calmar is None or pf is None:
        return None
    return round(0.4 * float(sharpe) + 0.3 * float(calmar) + 0.3 * float(pf), 4)


def pareto_front(cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the subset of cells that are Pareto-optimal on
    (sharpe_mean, -|max_drawdown_pct_mean|). A cell is dominated iff
    another cell has strictly better sharpe AND strictly less DD."""
    def _point(c):
        a = c.get("agg", {})
        s = a.get("sharpe_mean")
        dd = a.get("max_drawdown_pct_mean")
        if s is None or dd is None:
            return None
        # DD is negative; we want less-negative = higher.
        return (float(s), float(dd))

    pts = [(c, _point(c)) for c in cells]
    pts = [(c, p) for c, p in pts if p is not None]
    front = []
    for c_i, p_i in pts:
        dominated = False
        for c_j, p_j in pts:
            if c_j is c_i:
                continue
            if p_j[0] >= p_i[0] and p_j[1] >= p_i[1] and \
               (p_j[0] > p_i[0] or p_j[1] > p_i[1]):
                dominated = True
                break
        if not dominated:
            front.append(c_i)
    return front


def sort_by_composite(cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keyed = [(composite_score(c.get("agg", {})) or -1e18, c) for c in cells]
    keyed.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in keyed]


# -------------------------------------------------------------------------
# Stage orchestration
# -------------------------------------------------------------------------

def run_stage(name: str, cells: List[CellParams], days: int,
              step_minutes: int, windows: int, mc_sims: int,
              resume: bool = True,
              progress: Optional[Callable[[int, int, CellParams, Dict], None]] = None
              ) -> List[Dict[str, Any]]:
    """Iterate a cell list, skipping any cell whose JSON is already on disk."""
    done = load_completed(name) if resume else {}
    results: List[Dict[str, Any]] = list(done.values())
    todo = [c for c in cells if c.cell_hash() not in done]
    print(f"[stage] {name}: {len(todo)} to run ({len(done)} cached), "
          f"{len(cells)} total")

    for i, params in enumerate(todo, start=1):
        print(f"\n=== cell {i}/{len(todo)}  {params.as_dict()} ===")
        try:
            result = run_cell(params, days=days, step_minutes=step_minutes,
                              windows=windows, mc_sims=mc_sims)
        except Exception as e:
            result = {"params": params.as_dict(), "fatal": str(e)[:200]}
        save_cell(name, params, result)
        results.append(result)
        if progress:
            progress(i, len(todo), params, result)
        _print_cell_summary(params, result)

    return results


def _print_cell_summary(params: CellParams, result: Dict[str, Any]) -> None:
    agg = result.get("agg", {})
    sharpe = agg.get("sharpe_mean")
    ret = agg.get("return_pct_mean")
    dd = agg.get("max_drawdown_pct_mean")
    trades = agg.get("total_trades_mean")
    if "fatal" in result:
        print(f"  FAILED: {result['fatal']}")
        return
    print(f"  -> sharpe={sharpe} return%={ret} dd%={dd} "
          f"trades={trades} composite={composite_score(agg)}")


# -------------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------------

def write_stage_report(name: str, stage: str,
                       results: List[Dict[str, Any]]) -> Path:
    path = _grid_dir(name) / f"stage_{stage}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    ranked = sort_by_composite(results)
    payload = {
        "name": name,
        "stage": stage,
        "n_cells": len(results),
        "top_by_composite": [r.get("params", {}).get("cell_hash")
                             for r in ranked[:10]],
        "pareto_front_hashes": [r.get("params", {}).get("cell_hash")
                                for r in pareto_front(results)],
        "cells": ranked,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"[report] stage '{stage}' -> {path}")
    return path


def print_leaderboard(results: List[Dict[str, Any]], top: int = 12) -> None:
    ranked = sort_by_composite(results)
    front_hashes = {r.get("params", {}).get("cell_hash")
                    for r in pareto_front(results)}

    header = (f"{'#':>3} {'hash':<10} {'mc':>5} {'sl':>5} {'rr':>5} "
              f"{'pc':>3} {'risk':>5} {'Sharpe':>7} {'Calmar':>7} "
              f"{'PF':>6} {'Ret%':>7} {'DD%':>7} {'Trd':>4} {'Comp':>6} {'P':>2}")
    print("\n" + header)
    print("-" * len(header))
    for i, c in enumerate(ranked[:top], start=1):
        p = c.get("params", {})
        a = c.get("agg", {})
        comp = composite_score(a)
        def f(v, n=2, w=7):
            return f"{v:>{w}.{n}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}"
        pareto = "*" if p.get("cell_hash") in front_hashes else ""
        print(f"{i:>3} {p.get('cell_hash','-'):<10} "
              f"{p.get('min_confidence'):>5.2f} "
              f"{p.get('sl_atr_mult'):>5.2f} "
              f"{p.get('target_rr'):>5.2f} "
              f"{'Y' if p.get('partial_close') else '-':>3} "
              f"{p.get('risk_percent'):>5.2f} "
              f"{f(a.get('sharpe_mean'))} "
              f"{f(a.get('calmar_mean'))} "
              f"{f(a.get('profit_factor_mean'), 2, 6)} "
              f"{f(a.get('return_pct_mean'))} "
              f"{f(a.get('max_drawdown_pct_mean'))} "
              f"{int(a['total_trades_mean']) if a.get('total_trades_mean') else '-':>4} "
              f"{f(comp, 2, 6)} {pareto:>2}")


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------

def _pick_top_n(stage_a_report: Path, n: int) -> List[CellParams]:
    data = json.loads(stage_a_report.read_text())
    top = data.get("cells", [])[:n]
    out: List[CellParams] = []
    for c in top:
        p = c.get("params", {})
        out.append(CellParams(
            min_confidence=float(p["min_confidence"]),
            sl_atr_mult=float(p["sl_atr_mult"]),
            target_rr=float(p["target_rr"]),
            partial_close=bool(p["partial_close"]),
            risk_percent=float(p["risk_percent"]),
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="default", help="grid run name (dir suffix)")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--step-minutes", type=int, default=15)
    ap.add_argument("--windows", type=int, default=4,
                    help="walk-forward windows per cell (Stage B)")
    ap.add_argument("--mc", type=int, default=500,
                    help="Monte Carlo simulations per cell (0=off)")
    ap.add_argument("--stage", choices=("a", "b", "both"), default="both")
    ap.add_argument("--top-n", type=int, default=12,
                    help="how many Stage A survivors feed Stage B")
    ap.add_argument("--stage-a-report", default=None,
                    help="explicit Stage A report path for --stage b")
    ap.add_argument("--smoke", action="store_true",
                    help="3-cell mini grid with no WF / no MC (~2-3 min)")
    ap.add_argument("--report", action="store_true",
                    help="print leaderboard for existing grid and exit")
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore cached cell JSONs and re-run everything")
    args = ap.parse_args()

    if args.report:
        results = list(load_completed(args.name).values())
        if not results:
            print(f"[report] no cells found under {_grid_dir(args.name)}")
            return 1
        print_leaderboard(results, top=20)
        return 0

    # ONE-TIME data fetch: every cell reuses this provider.
    prefetch_shared_provider(days=args.days if not args.smoke else 7)

    if args.smoke:
        name = args.name if args.name != "default" else "smoke"
        cells = build_grid(smoke=True)
        print(f"[grid] SMOKE: {len(cells)} cells, days={args.days}, no WF, no MC")
        results = run_stage(name, cells, days=max(args.days, 3),
                            step_minutes=args.step_minutes,
                            windows=1, mc_sims=0,
                            resume=not args.no_resume)
        write_stage_report(name, "smoke", results)
        print_leaderboard(results)
        return 0

    full_grid = build_grid(smoke=False)
    print(f"[grid] full grid: {len(full_grid)} cells")

    # ---- Stage A ---------------------------------------------------------
    if args.stage in ("a", "both"):
        print("\n[stage A] pre-filter pass (1 window, no MC)")
        stage_a = run_stage(f"{args.name}_A", full_grid,
                            days=max(args.days // 2, 7),
                            step_minutes=args.step_minutes,
                            windows=1, mc_sims=0,
                            resume=not args.no_resume)
        stage_a_report = write_stage_report(f"{args.name}_A", "a", stage_a)
        print_leaderboard(stage_a, top=args.top_n)
    else:
        stage_a_report = Path(args.stage_a_report) if args.stage_a_report else \
                         (_grid_dir(f"{args.name}_A") / "stage_a.json")
        if not stage_a_report.exists():
            print(f"[fatal] Stage A report not found: {stage_a_report}")
            return 2

    # ---- Stage B ---------------------------------------------------------
    if args.stage in ("b", "both"):
        survivors = _pick_top_n(stage_a_report, args.top_n)
        print(f"\n[stage B] deep eval on top {len(survivors)} survivors "
              f"(WF={args.windows}, MC={args.mc})")
        stage_b = run_stage(f"{args.name}_B", survivors,
                            days=args.days, step_minutes=args.step_minutes,
                            windows=args.windows, mc_sims=args.mc,
                            resume=not args.no_resume)
        write_stage_report(f"{args.name}_B", "b", stage_b)
        print_leaderboard(stage_b)

        front = pareto_front(stage_b)
        print(f"\n[pareto] {len(front)} Pareto-optimal configs on (Sharpe, -DD):")
        for c in front:
            p = c.get("params", {})
            a = c.get("agg", {})
            print(f"  {p.get('cell_hash')}  "
                  f"sharpe={a.get('sharpe_mean')}  dd%={a.get('max_drawdown_pct_mean')}  "
                  f"ret%={a.get('return_pct_mean')}  "
                  f"min_conf={p.get('min_confidence')} sl={p.get('sl_atr_mult')} "
                  f"rr={p.get('target_rr')} pc={p.get('partial_close')} "
                  f"risk={p.get('risk_percent')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
