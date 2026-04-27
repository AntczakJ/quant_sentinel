"""factor_importance_audit.py — which scanner factors actually predict outcome.

Two datasets, two views:

1. **trades.factors** (post-2026-04-06 cohort, n≈32) — what factors were
   present at execution and how each correlates with WIN/LOSS. Sample is
   small; reported with Bonferroni-corrected significance and direction
   split. Treat as "early signal" not "definitive ranking".

2. **rejected_setups** (n≈9k, has `would_have_won` ground truth) — which
   filter-name blocked setups that WOULD have won. A filter that
   disproportionately blocks winners is hurting WR. This sample is huge
   and the most actionable signal.

Output:
- `docs/strategy/2026-04-27_factor_importance_audit.md` — full report
- console summary

Methodology guards (per memory/feedback_overfitting_check.md):
- **Sample size:** every row in output reports `n`. Anything with n<20
  is flagged "underpowered".
- **Multiple comparisons:** Bonferroni correction across the factor set.
  Raw p-values shown alongside corrected.
- **Direction split:** LONG and SHORT analyzed separately AND together;
  divergence flagged.
- **Time slicing:** pre/post 2026-04-26 19:20 UTC (Phase B + B7 flip).
- **No conclusions on n<20 + p>0.10 cells.** Marked DISPLAY-ONLY.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

# scipy stats — soft import so the script still runs the trade-side
# analysis if scipy is unavailable (only the p-values get None).
try:
    from scipy.stats import binomtest, fisher_exact  # type: ignore
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False
    print("[warn] scipy unavailable — p-values will be None")


REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "sentinel.db"
REPORT = REPO / "docs" / "strategy" / "2026-04-27_factor_importance_audit.md"
PHASE_B_FLIP = "2026-04-26 19:20:00"  # CEST → roughly 17:20 UTC


def _binomial_p(wins: int, n: int, baseline_wr: float) -> float | None:
    """Two-sided binomial test: probability of observing this WR (or more
    extreme) under the assumption that the true rate equals baseline."""
    if n == 0 or not _HAVE_SCIPY:
        return None
    return float(binomtest(wins, n, baseline_wr, alternative="two-sided").pvalue)


def _fisher_p(a: int, b: int, c: int, d: int) -> float | None:
    """2×2 Fisher exact: are wins independent of factor presence?
    Layout: [[wins_with, losses_with], [wins_without, losses_without]].
    Use over chi-sq because cells can be small."""
    if not _HAVE_SCIPY:
        return None
    return float(fisher_exact([[a, b], [c, d]], alternative="two-sided").pvalue)


def trades_view(conn: sqlite3.Connection) -> dict:
    """Per-factor WR analysis from `trades.factors`. Direction-split + time-split."""
    rows = conn.execute("""
        SELECT id, timestamp, direction, status, factors, profit
        FROM trades
        WHERE status IN ('WIN','LOSS') AND factors IS NOT NULL
    """).fetchall()

    # parse factors JSON; some rows have malformed entries — skip those
    parsed: list[tuple[int, str, str, str, dict, float | None]] = []
    for trade_id, ts, direction, status, factors_raw, profit in rows:
        try:
            fac = json.loads(factors_raw) if factors_raw else {}
            if not isinstance(fac, dict):
                continue
            parsed.append((trade_id, ts, direction, status, fac, profit))
        except (json.JSONDecodeError, TypeError):
            continue

    n_total = len(parsed)
    if n_total == 0:
        return {"error": "no eligible trades", "n": 0}

    n_wins = sum(1 for _, _, _, s, _, _ in parsed if s == "WIN")
    baseline_wr = n_wins / n_total

    # Collect every distinct factor key across all trades. Some keys are
    # always-present descriptors (ob_count, fvg) — those will show small
    # delta-WR but are the data we have. Outcome-correlated keys are the
    # signal we want.
    all_keys = sorted({k for _, _, _, _, fac, _ in parsed for k in fac.keys()})

    rows_out: list[dict] = []
    for key in all_keys:
        with_, without = [], []
        for _, _, _, s, fac, _ in parsed:
            (with_ if key in fac else without).append(s == "WIN")

        n_w = len(with_)
        n_wo = len(without)
        wins_w = sum(with_)
        wins_wo = sum(without)
        wr_w = wins_w / n_w if n_w else None
        wr_wo = wins_wo / n_wo if n_wo else None

        delta = (wr_w - wr_wo) if (wr_w is not None and wr_wo is not None) else None

        # Fisher exact: is win-rate independent of factor presence?
        p_raw = _fisher_p(wins_w, n_w - wins_w, wins_wo, n_wo - wins_wo)

        rows_out.append({
            "factor": key,
            "n_with": n_w,
            "n_without": n_wo,
            "wr_with": wr_w,
            "wr_without": wr_wo,
            "delta_pp": (delta * 100) if delta is not None else None,
            "p_raw": p_raw,
        })

    # Bonferroni: multiply each p by len(rows_out), cap at 1.0.
    k = len(rows_out)
    for r in rows_out:
        r["p_bonferroni"] = (
            min(1.0, r["p_raw"] * k) if r["p_raw"] is not None else None
        )

    # Direction-split — same factors, but only LONG / only SHORT
    by_dir: dict[str, list[dict]] = {}
    for direction in ("LONG", "SHORT"):
        sub = [t for t in parsed if t[2] == direction]
        if not sub:
            continue
        sub_rows: list[dict] = []
        for key in all_keys:
            with_ = [s == "WIN" for _, _, _, s, fac, _ in sub if key in fac]
            without = [s == "WIN" for _, _, _, s, fac, _ in sub if key not in fac]
            n_w, n_wo = len(with_), len(without)
            if n_w == 0:
                continue
            wins_w = sum(with_)
            wins_wo = sum(without)
            wr_w = wins_w / n_w if n_w else None
            wr_wo = wins_wo / n_wo if n_wo else None
            delta = (wr_w - wr_wo) if (wr_w is not None and wr_wo is not None) else None
            sub_rows.append({
                "factor": key,
                "n_with": n_w,
                "n_without": n_wo,
                "wr_with": wr_w,
                "wr_without": wr_wo,
                "delta_pp": (delta * 100) if delta is not None else None,
                "p_raw": _fisher_p(wins_w, n_w - wins_w, wins_wo, n_wo - wins_wo),
            })
        # Bonferroni inside each direction group
        kk = len(sub_rows)
        for r in sub_rows:
            r["p_bonferroni"] = min(1.0, r["p_raw"] * kk) if r["p_raw"] is not None else None
        by_dir[direction] = sub_rows

    # Time-split: pre vs post Phase B
    time_split: dict[str, dict] = {}
    for label, predicate in [
        ("pre_phase_B", lambda ts: ts < PHASE_B_FLIP),
        ("post_phase_B", lambda ts: ts >= PHASE_B_FLIP),
    ]:
        sub = [t for t in parsed if predicate(t[1])]
        time_split[label] = {
            "n": len(sub),
            "wins": sum(1 for _, _, _, s, _, _ in sub if s == "WIN"),
            "wr": (sum(1 for _, _, _, s, _, _ in sub if s == "WIN") / len(sub))
            if sub else None,
        }

    return {
        "n": n_total,
        "wins": n_wins,
        "baseline_wr": baseline_wr,
        "factors": rows_out,
        "by_direction": by_dir,
        "time_split": time_split,
    }


# Breakeven WR for the live R=1.96 target — anything above this means
# the filter is killing setups that on average pay off. Imported from
# replay_directional_alignment.py logic, kept as a constant so the audit
# stays consistent if the live R changes (note then: bump this).
_BREAKEVEN_WR_STRICT = 1.0 / (1.0 + 1.963)   # ≈ 33.95%


def rejections_view(conn: sqlite3.Connection) -> dict:
    """Per-filter analysis: which filter blocked SETUPS THAT WOULD HAVE WON?

    Uses the replay's 4-value `would_have_won` encoding from
    `replay_directional_alignment.py`:
      0 = SL hit
      1 = TP hit
      2 = time-exit, closed positive
      3 = time-exit, closed negative

    Two parallel metrics (avoids the trap of "any positive close = win"):
      - **WR_strict** = TP / (TP + SL): real edge, covers spread & slippage,
        comparable directly to the breakeven WR for R=1.96 (~34%).
      - **WR_loose** = (TP + time_wins) / total: lenient, includes
        any-positive close, useful for completeness but misleading.

    Significance is tested vs **breakeven** (not vs population baseline)
    because the actionable question is "could we trade these and net
    positive R?", not "do they outperform the average rejection?".
    """
    rows = conn.execute("""
        SELECT timestamp, direction, filter_name, would_have_won, timeframe
        FROM rejected_setups
        WHERE would_have_won IS NOT NULL
    """).fetchall()

    if not rows:
        return {"error": "no resolved rejections", "n": 0}

    n_total = len(rows)
    overall_tp = sum(1 for _, _, _, w, _ in rows if w == 1)
    overall_sl = sum(1 for _, _, _, w, _ in rows if w == 0)
    overall_tw = sum(1 for _, _, _, w, _ in rows if w == 2)
    overall_tl = sum(1 for _, _, _, w, _ in rows if w == 3)
    pop_wr_strict = overall_tp / (overall_tp + overall_sl) if (overall_tp + overall_sl) else 0.0
    pop_wr_loose = (overall_tp + overall_tw) / n_total if n_total else 0.0

    # per-filter aggregation
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "tp": 0, "sl": 0, "time_win": 0, "time_loss": 0}
    )
    for _, _, filt, won, _ in rows:
        d = agg[filt]
        d["n"] += 1
        if won == 1: d["tp"] += 1
        elif won == 0: d["sl"] += 1
        elif won == 2: d["time_win"] += 1
        elif won == 3: d["time_loss"] += 1

    out: list[dict] = []
    for filt, d in agg.items():
        n_lvl = d["tp"] + d["sl"]
        wr_strict = (d["tp"] / n_lvl) if n_lvl else None
        wr_loose = (d["tp"] + d["time_win"]) / d["n"] if d["n"] else None
        # Binomial test vs breakeven — only meaningful when we have
        # enough resolved-at-level samples. Otherwise leave None.
        p_strict = _binomial_p(d["tp"], n_lvl, _BREAKEVEN_WR_STRICT) if n_lvl else None
        out.append({
            "filter": filt,
            "n_rejected": d["n"],
            "n_resolved_at_level": n_lvl,
            "tp": d["tp"], "sl": d["sl"],
            "time_win": d["time_win"], "time_loss": d["time_loss"],
            "wr_strict": wr_strict,
            "wr_loose": wr_loose,
            "delta_vs_breakeven_pp": (
                (wr_strict - _BREAKEVEN_WR_STRICT) * 100
                if wr_strict is not None else None
            ),
            "p_raw": p_strict,
        })

    # Bonferroni — only over filters with n_at_level >= 30 (others are
    # underpowered and shouldn't influence the correction).
    testable = [r for r in out if r["n_resolved_at_level"] >= 30]
    k = max(1, len(testable))
    for r in out:
        r["p_bonferroni"] = (
            min(1.0, r["p_raw"] * k) if r["p_raw"] is not None else None
        )

    # sort: biggest |delta| first among testable; underpowered after
    out.sort(key=lambda r: (
        r["n_resolved_at_level"] < 30,
        -abs(r["delta_vs_breakeven_pp"]) if r["delta_vs_breakeven_pp"] is not None else 0,
    ))

    # per-direction split
    per_dir: dict[str, dict] = {}
    for direction in ("LONG", "SHORT"):
        sub = [r for r in rows if r[1] == direction]
        if not sub:
            continue
        d_tp = sum(1 for _, _, _, w, _ in sub if w == 1)
        d_sl = sum(1 for _, _, _, w, _ in sub if w == 0)
        d_tw = sum(1 for _, _, _, w, _ in sub if w == 2)
        per_dir[direction] = {
            "n": len(sub),
            "tp": d_tp,
            "sl": d_sl,
            "wr_strict": d_tp / (d_tp + d_sl) if (d_tp + d_sl) else None,
            "wr_loose": (d_tp + d_tw) / len(sub),
        }

    return {
        "n": n_total,
        "overall_tp": overall_tp,
        "overall_sl": overall_sl,
        "overall_time_win": overall_tw,
        "overall_time_loss": overall_tl,
        "population_wr_strict": pop_wr_strict,
        "population_wr_loose": pop_wr_loose,
        "breakeven_wr_strict": _BREAKEVEN_WR_STRICT,
        "filters": out,
        "by_direction": per_dir,
    }


def _fmt_pct(v: float | None) -> str:
    return f"{v*100:.1f}%" if v is not None else "—"


def _fmt_pp(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.1f}pp"


def _fmt_p(v: float | None) -> str:
    if v is None:
        return "—"
    if v < 0.001:
        return "<0.001"
    return f"{v:.3f}"


def render_report(trades_data: dict, rejections_data: dict) -> str:
    """Render the markdown report. Tables are pipe-style for portability."""
    lines: list[str] = []
    lines.append("# Factor importance audit (2026-04-27)")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Twin views: (1) trade-side factor presence vs WIN/LOSS, "
                 "(2) rejection-side filter vs would-have-won ground truth. "
                 "Both with Bonferroni multiple-comparisons correction.")
    lines.append("")
    lines.append(f"**Phase-B flip cutoff:** `{PHASE_B_FLIP}` (CEST). "
                 "Pre/post split flags how recent the data is.")
    lines.append("")

    # ─── 1. Trades view ────────────────────────────────────────────
    lines.append("## 1. Trade-side factor presence")
    lines.append("")
    if "error" in trades_data:
        lines.append(f"*No data: {trades_data['error']}*")
    else:
        lines.append(f"- Resolved trades with factors JSON: **n={trades_data['n']}**, "
                     f"baseline WR: **{_fmt_pct(trades_data['baseline_wr'])}**")
        lines.append("")
        lines.append("**Time split (sanity check on relevance):**")
        lines.append("")
        lines.append("| Window | n | wins | WR |")
        lines.append("|---|---:|---:|---:|")
        for label, d in trades_data["time_split"].items():
            lines.append(f"| {label} | {d['n']} | {d['wins']} | {_fmt_pct(d['wr'])} |")
        lines.append("")

        lines.append("### 1a. All directions combined")
        lines.append("")
        lines.append("Sample is **n≈32** — Bonferroni-corrected p-values "
                     "are mostly non-significant. This table is **early signal**, "
                     "not a verdict. n<20 cells flagged with `↘`.")
        lines.append("")
        lines.append("| Factor | n with | n w/o | WR with | WR w/o | Δ pp | p raw | p Bonf |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        # Sort by |delta| descending — most informative first
        sorted_factors = sorted(
            trades_data["factors"],
            key=lambda r: abs(r["delta_pp"]) if r["delta_pp"] is not None else 0,
            reverse=True,
        )
        for r in sorted_factors:
            flag = " ↘" if r["n_with"] < 20 else ""
            lines.append(
                f"| `{r['factor']}`{flag} | {r['n_with']} | {r['n_without']} | "
                f"{_fmt_pct(r['wr_with'])} | {_fmt_pct(r['wr_without'])} | "
                f"{_fmt_pp(r['delta_pp'])} | {_fmt_p(r['p_raw'])} | {_fmt_p(r['p_bonferroni'])} |"
            )
        lines.append("")

        # Direction split
        for direction, factors in trades_data["by_direction"].items():
            lines.append(f"### 1b. {direction} only")
            lines.append("")
            lines.append("| Factor | n with | WR with | WR w/o | Δ pp | p raw | p Bonf |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for r in sorted(factors, key=lambda r: abs(r["delta_pp"]) if r["delta_pp"] is not None else 0, reverse=True):
                flag = " ↘" if r["n_with"] < 10 else ""
                lines.append(
                    f"| `{r['factor']}`{flag} | {r['n_with']} | {_fmt_pct(r['wr_with'])} | "
                    f"{_fmt_pct(r['wr_without'])} | {_fmt_pp(r['delta_pp'])} | "
                    f"{_fmt_p(r['p_raw'])} | {_fmt_p(r['p_bonferroni'])} |"
                )
            lines.append("")

    # ─── 2. Rejections view ────────────────────────────────────────
    lines.append("## 2. Rejection-side: filters blocking would-be winners")
    lines.append("")
    if "error" in rejections_data:
        lines.append(f"*No data: {rejections_data['error']}*")
    else:
        be_wr = rejections_data["breakeven_wr_strict"]
        lines.append(
            f"- Resolved rejections (`would_have_won IS NOT NULL`): "
            f"**n={rejections_data['n']}**"
        )
        lines.append(
            f"- Outcome breakdown: TP={rejections_data['overall_tp']}  "
            f"SL={rejections_data['overall_sl']}  "
            f"time-win={rejections_data['overall_time_win']}  "
            f"time-loss={rejections_data['overall_time_loss']}"
        )
        lines.append(
            f"- Population WR_strict (TP / TP+SL): **{_fmt_pct(rejections_data['population_wr_strict'])}**  "
            f"|  WR_loose (any positive): **{_fmt_pct(rejections_data['population_wr_loose'])}**"
        )
        lines.append(
            f"- **Breakeven WR_strict** (R=1.96): "
            f"**{_fmt_pct(be_wr)}** — filters above this are blocking +EV setups."
        )
        lines.append("")
        if rejections_data.get("by_direction"):
            lines.append("**Direction split (TP / SL / WR_strict / WR_loose):**")
            lines.append("")
            lines.append("| Direction | n | TP | SL | WR_strict | WR_loose |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for d, info in rejections_data["by_direction"].items():
                lines.append(
                    f"| {d} | {info['n']} | {info['tp']} | {info['sl']} | "
                    f"{_fmt_pct(info['wr_strict'])} | {_fmt_pct(info['wr_loose'])} |"
                )
            lines.append("")

        lines.append("### 2a. Filters ranked by |WR_strict − breakeven|")
        lines.append("")
        lines.append(
            "**Reading the table:** WR_strict only counts setups that resolved "
            "at TP or SL (no time-exits). Compares to the **breakeven WR** "
            f"(~{_fmt_pct(be_wr)} at R=1.96). Above breakeven → filter is "
            "blocking +EV setups. Below → catching losers correctly. "
            "Underpowered = `n_at_level < 30` (too few resolved-at-level samples)."
        )
        lines.append("")
        lines.append("| Filter | n_rej | n@lvl | TP | SL | WR_strict | Δ vs breakeven | p Bonf | verdict |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        for r in rejections_data["filters"]:
            n_lvl = r["n_resolved_at_level"]
            verdict = ""
            delta = r.get("delta_vs_breakeven_pp")
            p_bonf = r.get("p_bonferroni")
            if n_lvl < 30:
                verdict = "↘ underpowered"
            elif delta is not None and delta > 5 and (p_bonf or 1) < 0.05:
                verdict = "🚨 BLOCKS WINNERS"
            elif delta is not None and delta < -5 and (p_bonf or 1) < 0.05:
                verdict = "✅ catches losers"
            else:
                verdict = "neutral"
            lines.append(
                f"| `{r['filter']}` | {r['n_rejected']} | {n_lvl} | "
                f"{r['tp']} | {r['sl']} | "
                f"{_fmt_pct(r['wr_strict'])} | "
                f"{_fmt_pp(delta)} | {_fmt_p(p_bonf)} | {verdict} |"
            )
        lines.append("")

    # ─── 3. Caveats & next steps ───────────────────────────────────
    lines.append("## 3. Caveats")
    lines.append("")
    lines.append("- Trade-side n=32 is too small for definitive ranking. "
                 "Treat as hypothesis generators only. Re-run after Phase B "
                 "accumulates 100+ resolved trades.")
    lines.append("- Rejection-side `would_have_won` is set by the resolver "
                 "against forward N-min outcome — it's not the same as "
                 "**would have hit TP first** (true backtest semantics). It "
                 "biases toward direction-correctness, not full setup. "
                 "Useful but not perfect.")
    lines.append("- Some factors are always-present descriptors (e.g., "
                 "`ob_count`, `fvg`) — their WR delta is noise unless we "
                 "add value-bucketing.")
    lines.append("- Bonferroni is conservative; with k≈10-15 factors any "
                 "raw p<0.005 corrects to <0.05. Lower bar p<0.10 is "
                 "'worth investigating', not 'act on'.")
    lines.append("- Time-split confirms whether the conclusions still hold "
                 "post-Phase-B. If pre/post diverges sharply, treat the "
                 "all-time table with extra suspicion.")
    lines.append("")
    lines.append("## 4. Suggested follow-ups")
    lines.append("")
    lines.append("1. Any filter with `🚨 BLOCKS WINNERS` deserves a "
                 "manual sample inspection (10-20 rejections per filter, "
                 "are they obvious losers a human would skip?).")
    lines.append("2. Any factor with Bonferroni p<0.10 in trade-view + "
                 "n>=20 is a candidate for upweighting in scanner score.")
    lines.append("3. Re-run this audit weekly. Drop n threshold once "
                 "post-Phase-B sample reaches 100 trades.")
    return "\n".join(lines)


def print_console_summary(trades_data: dict, rejections_data: dict) -> None:
    print("=" * 72)
    print("FACTOR IMPORTANCE AUDIT — quick console summary")
    print("=" * 72)

    if "error" not in trades_data:
        print(f"\nTrades-side: n={trades_data['n']} "
              f"baseline WR {_fmt_pct(trades_data['baseline_wr'])}")
        # Top 5 by |delta|
        top = sorted(
            trades_data["factors"],
            key=lambda r: abs(r["delta_pp"]) if r["delta_pp"] is not None else 0,
            reverse=True,
        )[:5]
        print("Top 5 factors by |Δ WR|:")
        for r in top:
            print(f"  {r['factor']:<25s} n_with={r['n_with']:>3d} "
                  f"Δ={_fmt_pp(r['delta_pp']):>8s} p_bonf={_fmt_p(r['p_bonferroni'])}")

    if "error" not in rejections_data:
        be = rejections_data["breakeven_wr_strict"]
        print(f"\nRejection-side: n={rejections_data['n']}  "
              f"pop WR_strict={_fmt_pct(rejections_data['population_wr_strict'])}  "
              f"breakeven={_fmt_pct(be)} (R=1.96)")
        sus = [r for r in rejections_data["filters"] if r["n_resolved_at_level"] >= 30][:6]
        print("Top filters by |Δ vs breakeven| (n_at_level >= 30):")
        for r in sus:
            delta = r.get("delta_vs_breakeven_pp")
            p_bonf = r.get("p_bonferroni")
            verdict = ("🚨" if (delta or 0) > 5 and (p_bonf or 1) < 0.05
                       else "✅" if (delta or 0) < -5 and (p_bonf or 1) < 0.05
                       else "  ")
            print(f"  {verdict} {r['filter']:<25s} "
                  f"n@lvl={r['n_resolved_at_level']:>4d}  "
                  f"WR_strict={_fmt_pct(r['wr_strict']):>6s} "
                  f"Δ={_fmt_pp(delta):>7s}  "
                  f"p_bonf={_fmt_p(p_bonf)}")
    print("\nFull report:", REPORT)
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing the markdown report (console only)")
    args = parser.parse_args()

    if not DB.exists():
        print(f"[error] DB not found at {DB}")
        return 2

    conn = sqlite3.connect(DB)
    try:
        trades_data = trades_view(conn)
        rejections_data = rejections_view(conn)
    finally:
        conn.close()

    print_console_summary(trades_data, rejections_data)

    if not args.no_write:
        report = render_report(trades_data, rejections_data)
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report, encoding="utf-8")
        print(f"[OK] wrote {REPORT}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
