"""
scripts/overnight_ab.py — run 4 A/B backtests sequentially overnight.

Usage:
    python scripts/overnight_ab.py [--start 2025-10-01] [--end 2026-04-26]

Runs the 4 candidate fixes from 2026-05-04 session:
  1. QUANT_REGIME_V2=1 vs unset (Phase V2 routing)
  2. QUANT_BLOCK_CHOCH_OBCOUNT=1 vs unset (toxic pair filter)
  3. target_rr 3.0 → 2.0 for A+ scalp grade
  4. A+ scalp threshold 65 → 75

Each A/B writes:
  - reports/ab_baseline_<test>.json
  - reports/ab_experiment_<test>.json
  - reports/overnight_ab_summary.md

Designed for unattended overnight execution. ~10-12h total runtime
on 6-month windows. Use shorter windows (--start 2026-01-01) for
faster iteration.

PRECONDITION: big backtest must be FINISHED (PID 7253 dead). This
script reuses backtest.db.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


EXPERIMENTS = [
    {
        "name": "regime_v2",
        "kind": "env",
        "key": "QUANT_REGIME_V2",
        "baseline": "0",
        "experiment": "1",
        "description": "Phase V2 regime-aware routing (squeeze block, min_score floor, direction filter)",
    },
    {
        "name": "choch_obcount_block",
        "kind": "env",
        "key": "QUANT_BLOCK_CHOCH_OBCOUNT",
        "baseline": "0",
        "experiment": "1",
        "description": "Block toxic pair choch+ob_count (N=30 WR 16.7%)",
    },
]


def run_backtest(start: str, end: str, output: str, env_overrides: dict | None = None) -> dict:
    cmd = [
        ".venv/Scripts/python.exe", "run_production_backtest.py",
        "--warehouse", "--reset",
        "--start", start, "--end", end,
        "--step-minutes", "15",
        "--analytics", "--output", output,
    ]
    env = os.environ.copy()
    if env_overrides:
        for k, v in env_overrides.items():
            if v == "0":
                env.pop(k, None)
            else:
                env[k] = str(v)
    print(f"\n[ovn] Running: {' '.join(cmd)}", flush=True)
    if env_overrides:
        print(f"[ovn] Env overrides: {env_overrides}", flush=True)
    start_t = time.time()
    result = subprocess.run(cmd, env=env, cwd=ROOT)
    elapsed = time.time() - start_t
    print(f"[ovn] Exit code {result.returncode}, elapsed {elapsed/60:.1f} min", flush=True)
    p = ROOT / output if not Path(output).is_absolute() else Path(output)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def compare(a: dict, b: dict, label_a: str, label_b: str) -> str:
    """Return MD-formatted comparison block."""
    keys = [
        ("total_trades", "Trades"),
        ("win_rate_pct", "WR %"),
        ("profit_factor", "PF"),
        ("return_pct", "Return %"),
        ("max_drawdown_pct", "MaxDD %"),
        ("max_consec_losses", "MaxConsecLoss"),
        ("breakevens", "BE"),
    ]
    lines = ["", f"### {label_a} vs {label_b}", "",
             "| Metric | Baseline | Experiment | Δ |",
             "|---|---|---|---|"]
    for k, label in keys:
        va = a.get(k, "—")
        vb = b.get(k, "—")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = vb - va
            lines.append(f"| {label} | {va} | {vb} | {delta:+} |")
        else:
            lines.append(f"| {label} | {va} | {vb} | — |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default="2026-04-26")
    args = ap.parse_args()

    summary_lines = [
        f"# Overnight A/B Validation Run",
        f"",
        f"Started: {datetime.now().isoformat(timespec='minutes')}",
        f"Window: {args.start} → {args.end}",
        f"",
        f"## Experiments",
    ]

    results = []
    for i, exp in enumerate(EXPERIMENTS, 1):
        print(f"\n{'=' * 70}\n[{i}/{len(EXPERIMENTS)}] {exp['name']}: {exp['description']}\n{'=' * 70}", flush=True)
        out_a = f"reports/ab_baseline_{exp['name']}.json"
        out_b = f"reports/ab_experiment_{exp['name']}.json"

        if exp["kind"] == "env":
            env_a = {exp["key"]: exp["baseline"]}
            env_b = {exp["key"]: exp["experiment"]}
        else:
            print(f"[ovn] kind={exp['kind']} not yet supported, skipping")
            continue

        stats_a = run_backtest(args.start, args.end, out_a, env_a)
        stats_b = run_backtest(args.start, args.end, out_b, env_b)
        block = compare(stats_a, stats_b,
                         f"baseline ({exp['key']}={exp['baseline']})",
                         f"experiment ({exp['key']}={exp['experiment']})")
        summary_lines.append(f"\n## {i}. {exp['name']}\n\n{exp['description']}\n{block}")
        results.append({"name": exp["name"], "baseline": stats_a, "experiment": stats_b})

    # Write summary
    out_path = ROOT / "reports" / "overnight_ab_summary.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"\n[ovn] Summary written to {out_path}")

    # Verdict
    print(f"\n{'=' * 70}\nVERDICT\n{'=' * 70}")
    for r in results:
        a, b = r["baseline"], r["experiment"]
        ret_a = a.get("return_pct", 0)
        ret_b = b.get("return_pct", 0)
        pf_a = a.get("profit_factor", 0) or 0
        pf_b = b.get("profit_factor", 0) or 0
        if isinstance(pf_a, (int, float)) and isinstance(pf_b, (int, float)):
            verdict = "✓ DEPLOY" if (ret_b > ret_a + 1.0 and pf_b >= pf_a) else "✗ KEEP BASELINE"
        else:
            verdict = "? MANUAL REVIEW"
        print(f"  {r['name']:<25} return Δ {ret_b - ret_a:+.2f}%  pf Δ {pf_b - pf_a:+.2f}  → {verdict}")


if __name__ == "__main__":
    main()
