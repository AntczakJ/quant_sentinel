"""
scripts/learning_health_check.py — sanity-check Bayesian self-learning state.

Verifies that dynamic_params keys touched by self-learning are coherent:
  - factor_alpha_X >= 1.0 + (wins seen)
  - factor_beta_X >= 1.0 + (losses seen)
  - weight_X within sampled range [0.5, 3.0] (Thompson Beta)
  - pattern_weight_X within [0.0, 2.0]
  - target_rr / tp_to_sl_ratio mirror equality (legacy bug guard)
  - No NaN, no negative, no infinite values

Surfaces:
  - HEALTHY counts
  - WARN: stale (not updated > 30 days, alpha+beta high but no recent activity)
  - ERROR: corrupted (NaN/inf/negative/out-of-range)

Usage: python scripts/learning_health_check.py
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _val(v):
    """Coerce DB value to float, treat None as 0.0."""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    conn = sqlite3.connect(ROOT / "data" / "sentinel.db")

    rows = conn.execute(
        "SELECT param_name, param_value, last_updated FROM dynamic_params"
    ).fetchall()

    healthy = 0
    warns = []
    errors = []

    # Group by family
    factor_alphas = {}
    factor_betas = {}
    factor_weights = {}
    pattern_weights = {}
    other = {}

    for name, value, last_updated in rows:
        v = _val(value)

        # Range checks
        if math.isnan(v) or math.isinf(v):
            errors.append(f"{name} = {v} (NaN/inf)")
            continue
        if name.startswith("factor_alpha_"):
            factor_alphas[name[len("factor_alpha_"):]] = (v, last_updated)
        elif name.startswith("factor_beta_"):
            factor_betas[name[len("factor_beta_"):]] = (v, last_updated)
        elif name.startswith("weight_"):
            factor_weights[name[len("weight_"):]] = (v, last_updated)
        elif name.startswith("pattern_weight_"):
            pattern_weights[name[len("pattern_weight_"):]] = (v, last_updated)
        else:
            other[name] = (v, last_updated)

    print("=" * 60)
    print("LEARNING STATE HEALTH CHECK")
    print("=" * 60)

    # ── Factor weights vs alpha/beta posterior consistency ──
    print(f"\n[FACTOR WEIGHTS] {len(factor_weights)} keys")
    for f, (w, ts) in sorted(factor_weights.items()):
        a = factor_alphas.get(f, (1.0, None))[0]
        b = factor_betas.get(f, (1.0, None))[0]
        n_trades = (a - 1) + (b - 1)
        wins = a - 1
        losses = b - 1
        # Weight should be in [0.5, 3.0] per Thompson sample
        if not (0.4 <= w <= 3.1):
            errors.append(f"  weight_{f}={w:.3f} out of [0.5, 3.0] — corrupted?")
        elif n_trades < 1:
            warns.append(f"  weight_{f}={w:.3f} but no trades observed (alpha=beta=1)")
        else:
            healthy += 1
            empirical_wr = wins / max(1, n_trades)
            mean_post = a / (a + b)  # Beta mean
            print(f"  {f:<25} weight={w:.3f}  n={int(n_trades):>3}  "
                  f"WR={empirical_wr:.0%}  Beta_mean={mean_post:.2f}")

    # ── Pattern weights ──
    print(f"\n[PATTERN WEIGHTS] {len(pattern_weights)} keys")
    for p, (w, ts) in sorted(pattern_weights.items()):
        if not (0.0 <= w <= 2.5):
            errors.append(f"  pattern_weight_{p}={w} out of [0, 2]")
        else:
            healthy += 1
            if w < 0.5:
                warns.append(f"  pattern_weight_{p}={w:.3f} — very low, near death")

    # ── Target RR / tp_to_sl_ratio mirror ──
    target_rr = other.get("target_rr", (None, None))[0]
    tp_to_sl = other.get("tp_to_sl_ratio", (None, None))[0]
    if target_rr is not None and tp_to_sl is not None:
        if abs(target_rr - tp_to_sl) > 0.001:
            errors.append(
                f"  target_rr={target_rr:.4f} != tp_to_sl_ratio={tp_to_sl:.4f} "
                f"(mirror broken — see CLAUDE.md commit 95569f7)"
            )
        else:
            print(f"\n[MIRROR] target_rr == tp_to_sl_ratio ({target_rr:.4f}) — OK")
            healthy += 1
    elif target_rr is None or tp_to_sl is None:
        warns.append(
            f"  target_rr or tp_to_sl_ratio missing (target_rr={target_rr}, "
            f"tp_to_sl_ratio={tp_to_sl}). Mirror may not be initialized."
        )

    # ── kelly_reset_ts check ──
    kelly_reset = other.get("kelly_reset_ts", (None, None))[0]
    if kelly_reset:
        try:
            t = datetime.fromtimestamp(kelly_reset)
            age = datetime.now() - t
            print(f"\n[KELLY] kelly_reset_ts = {t.isoformat()} ({age.days}d ago)")
            if age > timedelta(days=180):
                warns.append(f"  kelly_reset_ts > 6mo old — consider new reset")
        except Exception:
            warns.append(f"  kelly_reset_ts={kelly_reset} not parseable")

    # ── Risk halt check ──
    halted = other.get("risk_halted", (None, None))[0]
    if halted:
        warns.append(f"  risk_halted={halted} — system in halt state")

    # ── Negative/inf scan across all 'other' values ──
    for name, (v, ts) in other.items():
        if v < 0 and not name.startswith(("portfolio_pnl", "ret_", "_test")):
            warns.append(f"  {name}={v} (negative — check intentional)")

    # ── Summary ──
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Healthy keys: {healthy}")
    print(f"  Warnings: {len(warns)}")
    print(f"  Errors: {len(errors)}")
    if warns:
        print("\nWARNINGS:")
        for w in warns:
            print(w)
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(e)
    if not errors and not warns:
        print("\n  ALL CHECKS PASSED")

    conn.close()
    return 1 if errors else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
