"""src/risk/sizing.py — scientific position sizing wrapper.

2026-05-06 (Phase B): unified sizing that combines:
  - Half-Kelly (MacLean/Ziemba — 75% growth, 50% vol, 99% no-halve)
  - Vol-targeting (constant ~target_vol exposure across regimes)
  - Drawdown-controlled multiplier (Lopez de Prado)
  - Equity-curve filter (Robotwealth/qoppac — trade only when 30d > 90d)

Formula:
    f_used = base_kelly × kelly_fraction
                       × min(1, target_vol / realized_vol_20d)
                       × dd_mult(current_equity / peak_equity)
                       × ec_filter(equity_30d_ma > equity_90d_ma)

All env-tunable. Default OFF so existing behavior unchanged.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


# ── Half-Kelly + vol-target ─────────────────────────────────────────

def vol_target_multiplier(realized_vol_20d: float,
                           target_vol: Optional[float] = None) -> float:
    """Return multiplier that scales position to hit target_vol.

    target_vol default 0.08 (8%/yr). When realized vol > target → reduce
    sizing; when realized vol < target → increase up to cap.

    Cap at 1.5 (don't more-than-1.5× base on calm vol — protects against
    pre-crisis low-vol traps).
    """
    if target_vol is None:
        try:
            target_vol = float(os.environ.get("QUANT_TARGET_VOL", 0.08))
        except (TypeError, ValueError):
            target_vol = 0.08
    if realized_vol_20d <= 0:
        return 1.0
    mult = target_vol / realized_vol_20d
    return min(1.5, max(0.25, mult))  # clamp [0.25, 1.5]


# ── Drawdown-controlled sizing ─────────────────────────────────────

def dd_multiplier(current_equity: float, peak_equity: float, k: float = 2.0) -> float:
    """Convex anti-martingale: size_mult = (current/peak)^k.

    At -5% DD → 0.90 (k=2). At -10% → 0.81. At -20% → 0.64.

    k controls aggressiveness:
      k=1  linear (mild)
      k=2  quadratic (recommended)
      k=3  aggressive cut

    Returns 1.0 if at peak, < 1.0 during drawdown.
    """
    if peak_equity <= 0:
        return 1.0
    ratio = current_equity / peak_equity
    if ratio >= 1.0:
        return 1.0
    return max(0.1, ratio ** k)  # floor at 10% — never zero out


# ── Equity-curve filter ─────────────────────────────────────────────

def equity_curve_gate(db_path: Optional[str] = None) -> bool:
    """Return True if 30d equity MA > 90d equity MA (trade allowed).

    Robotwealth/qoppac pattern: trade strategy only when its own equity
    curve is in uptrend. Cuts MaxDD ~30%, costs ~10% return on average.

    Uses SQL on trades table — sums per-day P&L into daily equity.
    """
    db_path = db_path or str(ROOT / "data" / "sentinel.db")
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT timestamp, profit FROM trades "
            "WHERE status IN ('WIN','LOSS','PROFIT') "
            "AND timestamp >= datetime('now', '-91 days') "
            "ORDER BY timestamp"
        ).fetchall()
        conn.close()
        if len(rows) < 30:
            return True  # not enough history — don't gate

        # Build daily equity by date
        from collections import OrderedDict
        daily: dict = OrderedDict()
        for ts, pnl in rows:
            d = (ts or "")[:10]
            daily[d] = daily.get(d, 0.0) + float(pnl or 0)

        # Cumulative equity from $0 baseline (we just need MA comparison)
        eq = []
        cum = 0.0
        for d, v in daily.items():
            cum += v
            eq.append(cum)

        if len(eq) < 30:
            return True
        ma30 = sum(eq[-30:]) / 30
        ma90 = sum(eq[-90:]) / min(90, len(eq))
        return ma30 >= ma90
    except Exception:
        return True  # fail-open — don't block trading on infra issue


# ── Composed sizing function ──────────────────────────────────────

def scientific_size(
    kelly_fraction: float,
    base_lot: float,
    realized_vol_20d: float,
    current_equity: float,
    peak_equity: float,
    *,
    apply_vol_target: Optional[bool] = None,
    apply_dd_control: Optional[bool] = None,
    apply_ec_filter: Optional[bool] = None,
) -> dict:
    """Compose all sizing layers into a final lot.

    Args:
        kelly_fraction: pre-computed Kelly f (typically half-Kelly already capped)
        base_lot: baseline lot if no scaling (e.g. 0.01)
        realized_vol_20d: 20-day annualized vol fraction (e.g. 0.12 = 12%)
        current_equity / peak_equity: $ values for DD calc

    Each layer is env-flag opt-in via:
        QUANT_VOL_TARGETING=1
        QUANT_DD_SIZING=1
        QUANT_EQUITY_CURVE_FILTER=1

    Returns dict:
        lot: final lot
        breakdown: per-layer multipliers
        skipped: True if equity-curve gate blocked
    """
    if apply_vol_target is None:
        apply_vol_target = os.environ.get("QUANT_VOL_TARGETING") == "1"
    if apply_dd_control is None:
        apply_dd_control = os.environ.get("QUANT_DD_SIZING") == "1"
    if apply_ec_filter is None:
        apply_ec_filter = os.environ.get("QUANT_EQUITY_CURVE_FILTER") == "1"

    breakdown = {"kelly_fraction": kelly_fraction}

    # Equity-curve gate — if blocking, return zero size
    if apply_ec_filter:
        gate = equity_curve_gate()
        breakdown["ec_filter_open"] = gate
        if not gate:
            return {"lot": 0.0, "breakdown": breakdown, "skipped": True}
    else:
        breakdown["ec_filter_open"] = None

    # Start from base × kelly
    lot = base_lot * kelly_fraction
    breakdown["after_kelly"] = lot

    if apply_vol_target:
        vt = vol_target_multiplier(realized_vol_20d)
        lot *= vt
        breakdown["vol_target_mult"] = round(vt, 3)
    else:
        breakdown["vol_target_mult"] = None

    if apply_dd_control:
        dd_m = dd_multiplier(current_equity, peak_equity)
        lot *= dd_m
        breakdown["dd_mult"] = round(dd_m, 3)
    else:
        breakdown["dd_mult"] = None

    # Hard floor + cap
    lot = max(0.001, min(lot, 1.0))
    return {"lot": round(lot, 4), "breakdown": breakdown, "skipped": False}
