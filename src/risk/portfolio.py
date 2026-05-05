"""src/risk/portfolio.py — portfolio-level risk caps.

2026-05-05: shipped per comparative research adoption (#9). Single-asset
XAU today, but adding 2nd asset = total exposure can run to 2× per-trade
cap silently. Bloomberg PORT pattern: aggregate open risk across all
positions, cap total at MAX_OPEN_R.

Risk = R-multiples (lot × distance to SL × contract multiplier / equity).
A trade risking 1% has R=1. Two such concurrent trades = 2R total exposure.

Default `MAX_OPEN_R = 2.0` matches the typical retail prop-desk cap.
Override via env QUANT_MAX_OPEN_R.

This is a PRE-trade gate: scanner calls `would_breach_cap(new_trade_r)`
before placing. Live trades NOT modified.
"""
from __future__ import annotations

import os
from typing import Optional

OZ_PER_LOT = 100.0  # XAU spot standard contract


def trade_r_units(entry: float, sl: float, lot: float,
                  equity: float = 10000.0,
                  oz_per_lot: float = OZ_PER_LOT) -> float:
    """Compute R-units for a single trade.

    R = $-risk-on-trade / $-equity-base
    where $-risk = |entry - sl| × oz_per_lot × lot (USD risk if SL hits)
    and $-equity-base = current equity.

    Returns 0 if any input is invalid.
    """
    try:
        if entry <= 0 or sl <= 0 or lot <= 0 or equity <= 0:
            return 0.0
        usd_risk = abs(entry - sl) * oz_per_lot * lot
        return usd_risk / equity
    except (TypeError, ValueError):
        return 0.0


def open_trades_r(db) -> float:
    """Sum R-units across all currently OPEN trades."""
    try:
        rows = db._query(
            "SELECT entry, sl, lot FROM trades WHERE status = 'OPEN'"
        )
        # Use current equity from dynamic_params if available
        try:
            equity = float(db.get_param("portfolio_balance") or 10000.0)
        except Exception:
            equity = 10000.0
        total = 0.0
        for r in rows:
            entry, sl, lot = (r[0] or 0), (r[1] or 0), (r[2] or 0)
            total += trade_r_units(float(entry), float(sl), float(lot), equity=equity)
        return total
    except Exception:
        return 0.0


def get_max_open_r() -> float:
    """Read the cap from env, with safe default."""
    try:
        return float(os.environ.get("QUANT_MAX_OPEN_R", "2.0"))
    except (TypeError, ValueError):
        return 2.0


def would_breach_cap(db, new_entry: float, new_sl: float, new_lot: float) -> tuple[bool, dict]:
    """Check if adding a new trade would breach MAX_OPEN_R.

    Returns (breaches, info_dict). info_dict has:
        existing_r: R already open
        new_r: R of the candidate trade
        total_r_after: existing_r + new_r
        cap: configured cap
    """
    cap = get_max_open_r()
    try:
        equity = float(db.get_param("portfolio_balance") or 10000.0)
    except Exception:
        equity = 10000.0
    existing = open_trades_r(db)
    new_r = trade_r_units(new_entry, new_sl, new_lot, equity=equity)
    total = existing + new_r
    return (total > cap, {
        "existing_r": round(existing, 3),
        "new_r": round(new_r, 3),
        "total_r_after": round(total, 3),
        "cap": cap,
    })
