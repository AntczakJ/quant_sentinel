#!/usr/bin/env python
"""
scripts/compare_backtests.py — auto-diff two backtest result JSONs.

Use case 2026-05-05 onwards: 1yr baseline (reports/big_backtest_1yr.json)
captured PRE-fixes (London block / A demote / SHORT floor / OTE / etc).
Once 3yr post-audit run finishes, run this to get a markdown diff that
quantifies the lift.

Usage:
  python scripts/compare_backtests.py BASELINE.json CANDIDATE.json
  python scripts/compare_backtests.py reports/big_backtest_1yr.json reports/2026-05-05_post_audit_3yr.json

Output: markdown table to stdout (also writes reports/compare_<ts>.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


METRICS = [
    ("total_trades",       "Total trades",        "{:,}",        False),
    ("closed",             "Closed",              "{:,}",        False),
    ("wins",               "Wins",                "{:,}",        False),
    ("losses",             "Losses",              "{:,}",        False),
    ("breakevens",         "Breakevens",          "{:,}",        False),
    ("win_rate_pct",       "Win Rate",            "{:.1f}%",     False),
    ("profit_factor",      "Profit Factor",       "{:.2f}",      False),
    ("return_pct",         "Return",              "{:+.2f}%",    False),
    ("max_drawdown_pct",   "Max Drawdown",        "{:.2f}%",     True),   # negative is worse
    ("max_consec_losses",  "Max Consec Losses",   "{:,}",        True),
    ("avg_profit",         "Avg P&L per closed",  "${:+.2f}",    False),
    ("cumulative_profit",  "Cumulative P&L",      "${:+,.2f}",   False),
]


def load(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: {path} not found")
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(val, template: str) -> str:
    if val is None:
        return "—"
    try:
        return template.format(val)
    except (TypeError, ValueError):
        return str(val)


def delta_str(base, cand, lower_is_better: bool) -> str:
    if base is None or cand is None:
        return "—"
    try:
        d = cand - base
    except (TypeError, ValueError):
        return "—"
    sign = "+" if d > 0 else ""
    arrow = ""
    if lower_is_better:
        arrow = "✓" if d < 0 else ("✗" if d > 0 else "")
    else:
        arrow = "✓" if d > 0 else ("✗" if d < 0 else "")
    return f"{sign}{d:.2f} {arrow}".strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="Path for markdown output (default: reports/compare_<ts>.md)")
    args = ap.parse_args()

    base = load(args.baseline)
    cand = load(args.candidate)

    # Force UTF-8 stdout on Windows so Δ / arrows / dashes don't blow up cp1252
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (ROOT / "reports" / f"compare_{ts}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append(f"# Backtest comparison — {ts}\n")
    lines.append(f"- **Baseline**: `{args.baseline.name}`")
    lines.append(f"- **Candidate**: `{args.candidate.name}`\n")
    lines.append("| Metric | Baseline | Candidate | Δ |")
    lines.append("|---|---|---|---|")

    for key, label, template, lower_better in METRICS:
        b = base.get(key)
        c = cand.get(key)
        lines.append(
            f"| {label} | {fmt(b, template)} | {fmt(c, template)} | "
            f"{delta_str(b, c, lower_better)} |"
        )

    # Top rejection diff
    base_rej = {r[0]: r[2] for r in (base.get("top_rejections") or [])}
    cand_rej = {r[0]: r[2] for r in (cand.get("top_rejections") or [])}
    if base_rej or cand_rej:
        lines.append("\n## Top rejection-filter activity\n")
        lines.append("| Filter | Baseline | Candidate | Δ |")
        lines.append("|---|---|---|---|")
        all_filters = sorted(set(base_rej) | set(cand_rej))
        for f in all_filters:
            b = base_rej.get(f, 0)
            c = cand_rej.get(f, 0)
            d = c - b
            sign = "+" if d > 0 else ""
            lines.append(f"| `{f}` | {b:,} | {c:,} | {sign}{d:,} |")

    # Ensemble stats diff
    if "ensemble_signals_long" in base or "ensemble_signals_long" in cand:
        lines.append("\n## Ensemble signal distribution\n")
        for k in ("ensemble_confidence_avg", "ensemble_sample_count",
                  "ensemble_signals_long", "ensemble_signals_short",
                  "ensemble_signals_wait"):
            b = base.get(k)
            c = cand.get(k)
            lines.append(f"- `{k}`: baseline={b}, candidate={c}")

    text = "\n".join(lines) + "\n"
    out_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n📄 Saved to {out_path}")


if __name__ == "__main__":
    main()
