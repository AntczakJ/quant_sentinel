"""
scripts/ab_runner.py — automate A/B backtest comparison for a parameter change.

Wraps run_production_backtest.py to:
  1. Snapshot current `dynamic_params` value for the param to test.
  2. Run baseline (current value) backtest.
  3. Set the new value, run experiment backtest.
  4. Restore the original value.
  5. Print side-by-side comparison.

Usage:
    python scripts/ab_runner.py --param min_score \\
        --baseline 35 --experiment 50 \\
        --start 2025-10-01 --end 2026-04-26 --step-minutes 15

Or for env-flag toggles (no DB write):
    python scripts/ab_runner.py --env QUANT_REGIME_V2 \\
        --baseline 0 --experiment 1 \\
        --start 2025-10-01 --end 2026-04-26
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def snapshot_param(name: str) -> float | None:
    """Read current value of dynamic_params[name]. Returns None if absent."""
    import sqlite3
    conn = sqlite3.connect(ROOT / "data" / "sentinel.db")
    row = conn.execute(
        "SELECT param_value FROM dynamic_params WHERE param_name=?", (name,)
    ).fetchone()
    conn.close()
    return float(row[0]) if row else None


def set_param(name: str, value):
    """Write to BOTH sentinel.db AND backtest.db (backtest reads its own DB)."""
    import sqlite3
    for path in ("data/sentinel.db", "data/backtest.db"):
        conn = sqlite3.connect(ROOT / path)
        conn.execute(
            "INSERT OR REPLACE INTO dynamic_params (param_name, param_value) VALUES (?, ?)",
            (name, float(value)),
        )
        conn.commit()
        conn.close()


def restore_param(name: str, original: float | None):
    """Restore original DB state."""
    if original is None:
        # Delete the row we created (was absent originally)
        import sqlite3
        for path in ("data/sentinel.db", "data/backtest.db"):
            conn = sqlite3.connect(ROOT / path)
            conn.execute("DELETE FROM dynamic_params WHERE param_name=?", (name,))
            conn.commit()
            conn.close()
    else:
        set_param(name, original)


def run_backtest(args, output_path: str, env_overrides: dict | None = None) -> dict:
    """Run backtest with given args + optional env overrides. Returns stats dict."""
    cmd = [
        ".venv/Scripts/python.exe", "run_production_backtest.py",
        "--warehouse", "--reset",
        "--start", args.start, "--end", args.end,
        "--step-minutes", str(args.step_minutes),
        "--analytics", "--output", output_path,
    ]
    env = os.environ.copy()
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})
    print(f"\n[ab] Running: {' '.join(cmd)}", flush=True)
    if env_overrides:
        print(f"[ab] Env overrides: {env_overrides}", flush=True)
    result = subprocess.run(cmd, env=env, cwd=ROOT)
    if result.returncode != 0:
        print(f"[ab] Backtest exited {result.returncode}", flush=True)
    if Path(output_path).exists():
        return json.loads(Path(output_path).read_text())
    return {}


def compare_summary(a: dict, b: dict, label_a: str, label_b: str):
    """Print compact A vs B table. Same metrics as backtest --compare."""
    keys = [
        ("total_trades", "Trades"),
        ("win_rate_pct", "WR%"),
        ("profit_factor", "PF"),
        ("return_pct", "Return%"),
        ("max_drawdown_pct", "MaxDD%"),
        ("max_consec_losses", "MaxConsec"),
        ("alpha_vs_bh_pct", "Alpha%"),
        ("breakevens", "BE"),
    ]
    print("\n" + "=" * 70)
    print(f"{'Metric':<14} {label_a[:18]:>18} {label_b[:18]:>18} {'Δ':>10}")
    print("-" * 70)
    for k, label in keys:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = vb - va
            print(f"{label:<14} {va:>18.2f} {vb:>18.2f} {delta:>+10.2f}")
        else:
            print(f"{label:<14} {str(va):>18} {str(vb):>18} {'—':>10}")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--param", help="dynamic_params key to A/B")
    g.add_argument("--env", help="Env variable to A/B (set vs unset)")
    ap.add_argument("--baseline", required=True, help="Baseline value")
    ap.add_argument("--experiment", required=True, help="Experiment value")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--step-minutes", type=int, default=15)
    args = ap.parse_args()

    label_a = f"A: {args.param or args.env}={args.baseline}"
    label_b = f"B: {args.param or args.env}={args.experiment}"

    out_a = f"reports/ab_baseline_{args.param or args.env}.json"
    out_b = f"reports/ab_experiment_{args.param or args.env}.json"

    if args.param:
        # DB-backed param A/B
        original = snapshot_param(args.param)
        print(f"[ab] Original {args.param} = {original}")
        try:
            set_param(args.param, args.baseline)
            stats_a = run_backtest(args, out_a)
            set_param(args.param, args.experiment)
            stats_b = run_backtest(args, out_b)
        finally:
            restore_param(args.param, original)
            print(f"[ab] Restored {args.param} to {original}")
    else:
        # Env A/B (no DB mutation)
        baseline_env = {args.env: args.baseline} if args.baseline != "0" else {}
        experiment_env = {args.env: args.experiment}
        stats_a = run_backtest(args, out_a, baseline_env)
        stats_b = run_backtest(args, out_b, experiment_env)

    compare_summary(stats_a, stats_b, label_a, label_b)


if __name__ == "__main__":
    main()
