"""
scripts/master_dashboard.py — single-command "what's the system doing" report.

Aggregates output from all 2026-05-04 analyzers:
  - learning_health_check (Bayesian state sanity)
  - why_no_trade (last N hours)
  - factor_predictive_power (live + backtest cohort)
  - wr_cube (multidim WR)
  - hourly_heatmap (time of day)
  - LLM journal top themes (last 20 trades)

Designed as the single morning command for an operator. Runs in ~30s
when LLM journal is cached, ~3 min on first run.

Usage:
    python scripts/master_dashboard.py [--no-llm] [--hours 24]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def section(title: str):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def run_script(script: str, args: list[str] | None = None, capture: bool = True) -> str:
    cmd = [sys.executable, str(ROOT / "scripts" / script)] + (args or [])
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True,
                           cwd=ROOT, timeout=180, encoding="utf-8", errors="replace")
        return r.stdout + (r.stderr if r.returncode else "")
    except subprocess.TimeoutExpired:
        return f"[timeout running {script}]"
    except Exception as e:
        return f"[error running {script}: {e}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip LLM journal (saves ~$0.02 + 10s on first call)")
    ap.add_argument("--hours", type=int, default=24,
                    help="Lookback for why_no_trade (default 24)")
    ap.add_argument("--write-md", default=None,
                    help="Write full report to MD file")
    args = ap.parse_args()

    output_lines = []

    def out(msg: str):
        # Strip non-ascii to avoid Windows cp1252 console crashes.
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        output_lines.append(msg)

    out(f"# Quant Sentinel Master Dashboard — "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    section("1. LEARNING STATE HEALTH")
    health = run_script("learning_health_check.py")
    out(health)

    section(f"2. WHY NO TRADE (last {args.hours}h)")
    wht = run_script("why_no_trade.py", ["--hours", str(args.hours)])
    out(wht)

    section("3. FACTOR PREDICTIVE POWER (chi-square)")
    fp = run_script("factor_predictive_power.py", ["--db", "both", "--min-n", "5"])
    out(fp)

    section("4. WR CUBE (multidim breakdown)")
    cube = run_script("wr_cube.py", ["--db", "both", "--min-n", "5"])
    out(cube)

    section("5. HOURLY HEATMAP (UTC + DoW)")
    hm = run_script("hourly_heatmap.py", ["--db", "both", "--min-n", "3"])
    out(hm)

    if not args.no_llm and os.getenv("OPENAI_API_KEY"):
        section("6. LLM TRADE JOURNAL — top 20 themes")
        lj = run_script("llm_journal.py", ["--n", "20"])
        out(lj)
    else:
        section("6. LLM TRADE JOURNAL — SKIPPED (--no-llm or no OPENAI_API_KEY)")

    if args.write_md:
        out_path = ROOT / args.write_md if not Path(args.write_md).is_absolute() else Path(args.write_md)
        out_path.parent.mkdir(exist_ok=True, parents=True)
        out_path.write_text("\n".join(output_lines), encoding="utf-8")
        print(f"\nFull report -> {out_path}")


if __name__ == "__main__":
    main()
