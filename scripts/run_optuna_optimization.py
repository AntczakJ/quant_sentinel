#!/usr/bin/env python3
"""
scripts/run_optuna_optimization.py — Optuna replacement for grid backtest.

Why this exists
---------------
The grid backtest (memo `grid_backtest_verdict.md`) over-explored the
search space and produced a winner whose Sharpe stdev exceeded its mean
— overfit. Optuna with the TPE sampler + median pruner converges in
~5× fewer trials and keeps a study DB so partial runs resume cleanly.

This is OPT-IN — `run_production_backtest.py` is unchanged. Use it
alongside the grid for a while; when Optuna's winners hold up out of
sample, retire the grid path.

Usage
-----
  # 5 trials with mock evaluator — sanity-check the wiring:
  python scripts/run_optuna_optimization.py --n-trials 5 --mock

  # Real run, 30 trials, 30-day window per trial (~3 min each):
  python scripts/run_optuna_optimization.py --n-trials 30 --days 30

  # Resume an interrupted study:
  python scripts/run_optuna_optimization.py --resume --study-name xau_v1

Storage: SQLite at data/optuna_studies/<study_name>.db. Janek's existing
`optuna>=3.5.0` dep is sufficient (no extra packages needed).

Search space (matches DYNAMIC_PARAMS_WRITABLE in apply_grid_winner.py):
  - sl_atr_multiplier  ∈ [1.0, 4.0]
  - target_rr          ∈ [1.0, 4.0]   (mirrors to tp_to_sl_ratio via schema)
  - risk_percent       ∈ [0.25, 2.0]
  - min_tp_distance_mult ∈ [0.5, 2.5]

Composite score (objective, higher is better):
  0.5 * sharpe_mean
  + 0.3 * (profit_factor_mean - 1.0)
  + 0.2 * (return_pct_mean / max_drawdown_pct_mean_abs)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import optuna  # type: ignore


# ── Search space ──────────────────────────────────────────────────


def _suggest_params(trial: optuna.Trial) -> dict[str, float]:
    """Define the search space here. Keep aligned with DYNAMIC_PARAMS_WRITABLE."""
    return {
        "sl_atr_multiplier":   trial.suggest_float("sl_atr_multiplier", 1.0, 4.0, step=0.1),
        "target_rr":           trial.suggest_float("target_rr",         1.0, 4.0, step=0.1),
        "risk_percent":        trial.suggest_float("risk_percent",      0.25, 2.0, step=0.05),
        "min_tp_distance_mult":trial.suggest_float("min_tp_distance_mult", 0.5, 2.5, step=0.1),
    }


# ── Composite score ──────────────────────────────────────────────


def _composite(metrics: dict[str, float]) -> float:
    sharpe = float(metrics.get("sharpe_mean") or 0)
    pf     = float(metrics.get("profit_factor_mean") or 1.0)
    ret    = float(metrics.get("return_pct_mean") or 0)
    dd_abs = abs(float(metrics.get("max_drawdown_pct_mean") or -0.001) or 0.001)
    return 0.5 * sharpe + 0.3 * (pf - 1.0) + 0.2 * (ret / dd_abs)


# ── Evaluators ────────────────────────────────────────────────────


def _mock_eval(params: dict[str, float], rng: random.Random) -> dict[str, float]:
    """Synthetic metrics generator — used by `--mock` for wiring smoke tests.

    Pretends the optimum is around target_rr=2.5, sl_atr_mult=2.0,
    risk_percent=1.0. Shape ensures Optuna actually has a gradient to
    follow (verifying the search loop works) without spending real
    minutes on backtest runs.
    """
    target_d = abs(params["target_rr"] - 2.5)
    sl_d     = abs(params["sl_atr_multiplier"] - 2.0)
    risk_d   = abs(params["risk_percent"] - 1.0)
    base = 4.0 - 1.5 * target_d - 1.0 * sl_d - 0.7 * risk_d + rng.gauss(0, 0.1)
    return {
        "sharpe_mean": base,
        "profit_factor_mean": 1.0 + max(0, base / 4.0),
        "return_pct_mean": base * 1.5,
        "max_drawdown_pct_mean": -max(0.5, 4.0 - base),
        "total_trades_mean": 50 + rng.randint(-10, 10),
    }


def _real_eval(params: dict[str, float], days: int) -> dict[str, float]:
    """
    Subprocess run_production_backtest.py with a tiny report-only output.
    Parses the produced JSON (`--output trial.json`) for metrics.

    NOTE: the existing CLI does not expose a `--params-file` flag. This
    function writes the trial params into a temp dynamic_params snapshot
    via apply_grid_winner-style logic (only into backtest.db — the script
    enforces isolation at startup).
    """
    # Apply params into backtest.db's dynamic_params before invoking.
    # We use the schema-aware NewsDB so target_rr → tp_to_sl_ratio mirror
    # fires; tp_to_sl_ratio doesn't need an explicit assignment.
    os.environ["DATABASE_URL"] = "data/backtest.db"
    from src.core.database import NewsDB
    db = NewsDB()
    for k, v in params.items():
        db.set_param(k, float(v))

    out_path = ROOT / "data" / "optuna_studies" / "_trial.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, str(ROOT / "run_production_backtest.py"),
        "--days", str(days),
        "--warehouse",          # use local parquets — no API credit cost
        "--reset",              # clean slate per trial
        "--seed", "42",         # determinism
        "--output", str(out_path),
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))

    if not out_path.exists():
        raise RuntimeError(f"Trial JSON {out_path} not produced")
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    # run_production_backtest.py reports under different keys depending
    # on whether walk-forward / Monte Carlo were run. Prefer the
    # aggregated keys; fall back to direct.
    summary = raw.get("aggregated") or raw.get("summary") or raw
    return {
        "sharpe_mean": float(summary.get("sharpe", summary.get("sharpe_mean", 0))),
        "profit_factor_mean": float(summary.get("profit_factor", summary.get("profit_factor_mean", 1.0))),
        "return_pct_mean": float(summary.get("return_pct", summary.get("return_pct_mean", 0))),
        "max_drawdown_pct_mean": float(summary.get("max_drawdown_pct", summary.get("max_drawdown_pct_mean", -0.5))),
        "total_trades_mean": float(summary.get("total_trades", summary.get("total_trades_mean", 0))),
    }


# ── Optuna driver ─────────────────────────────────────────────────


def _make_objective(use_mock: bool, days: int):
    rng = random.Random(0)

    def objective(trial: optuna.Trial) -> float:
        params = _suggest_params(trial)
        if use_mock:
            metrics = _mock_eval(params, rng)
        else:
            metrics = _real_eval(params, days)
        # Stash full metrics on the trial for later inspection
        for k, v in metrics.items():
            trial.set_user_attr(k, v)
        return _composite(metrics)

    return objective


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--study-name", default="xau_optuna_v1")
    ap.add_argument("--n-trials", type=int, default=5)
    ap.add_argument("--days", type=int, default=30, help="window per real trial")
    ap.add_argument("--mock", action="store_true",
                    help="use synthetic evaluator — sanity-check wiring without running backtests")
    ap.add_argument("--resume", action="store_true", help="reuse the existing study DB")
    args = ap.parse_args()

    storage_dir = ROOT / "data" / "optuna_studies"
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_url = f"sqlite:///{(storage_dir / args.study_name).as_posix()}.db"

    if args.resume:
        study = optuna.load_study(study_name=args.study_name, storage=storage_url)
        print(f"[optuna] resumed study {args.study_name}: {len(study.trials)} trials so far")
    else:
        study = optuna.create_study(
            study_name=args.study_name,
            storage=storage_url,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42, n_startup_trials=8),
            pruner=optuna.pruners.MedianPruner(n_startup_trials=10, n_warmup_steps=5),
            load_if_exists=True,
        )
        print(f"[optuna] created study {args.study_name} at {storage_url}")

    objective = _make_objective(use_mock=args.mock, days=args.days)
    t0 = time.perf_counter()
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)
    elapsed = time.perf_counter() - t0

    print()
    print(f"[optuna] done — {len(study.trials)} total trials, {elapsed:.1f}s elapsed")
    print(f"[optuna] best composite: {study.best_value:.4f}")
    print(f"[optuna] best params:")
    for k, v in study.best_params.items():
        print(f"    {k}: {v}")
    print(f"[optuna] best metrics (user_attrs):")
    for k, v in study.best_trial.user_attrs.items():
        print(f"    {k}: {v}")
    print()
    print("Inspect interactively:")
    print(f"    optuna-dashboard {storage_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
