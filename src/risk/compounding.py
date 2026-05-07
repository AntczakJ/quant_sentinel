"""src/risk/compounding.py — equity-tier compounding optimizer.

Standard sizing: lot scales linearly with balance.
Tier-based compounding: lot scales in DISCRETE TIERS to avoid noise
on small balance changes. Top tier gets bonus risk fraction (compound
the win cycle harder).

Math:
  Tier 1 ($10k-15k):    1.0× base lot (standard)
  Tier 2 ($15k-25k):    1.1× base lot (compound aggression begins)
  Tier 3 ($25k-50k):    1.25× base lot (proven track)
  Tier 4 ($50k-100k):   1.4× base lot (battle-tested)
  Tier 5 (>$100k):      1.5× base lot (conservative ceiling)

Each tier requires REACHING + STAYING IN for 30 days before bonus
kicks in. Drop back tier on equity decline. Anti-martingale safe —
losing back to lower tier reduces aggression.

Pairs with vol-target + DD-control sizing wrappers (Phase B).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


# Tier thresholds (USD equity) → lot multiplier
TIERS = [
    (10000, 1.0),
    (15000, 1.1),
    (25000, 1.25),
    (50000, 1.4),
    (100000, 1.5),
]

TIER_PERSIST_DAYS = 30  # must stay in tier 30 days before bonus applies


def get_current_tier(equity: float) -> tuple[int, float]:
    """Return (tier_index_0_based, multiplier) for current equity."""
    selected = (0, 1.0)
    for i, (threshold, mult) in enumerate(TIERS):
        if equity >= threshold:
            selected = (i, mult)
    return selected


def get_eligible_tier(db_path: Optional[str] = None,
                       equity: Optional[float] = None) -> tuple[int, float, str]:
    """Return tier the operator is ELIGIBLE for, considering persist requirement.

    Operator must have CURRENT equity in tier AND have stayed in tier
    ≥ TIER_PERSIST_DAYS. Otherwise fall back to lower tier.

    Returns: (tier_index, multiplier, status_msg)
    """
    db_path = db_path or str(ROOT / "data" / "sentinel.db")

    # Get current equity
    if equity is None:
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT param_value FROM dynamic_params WHERE param_name = 'portfolio_balance'"
            ).fetchone()
            equity = float(row[0]) if row and row[0] else 10000.0
            conn.close()
        except Exception:
            equity = 10000.0

    current_tier_idx, current_mult = get_current_tier(equity)

    # If tier 0, no persist check needed
    if current_tier_idx == 0:
        return 0, 1.0, "tier_0_baseline"

    # Check persist: when did equity first cross THIS tier's threshold?
    tier_threshold = TIERS[current_tier_idx][0]
    try:
        conn = sqlite3.connect(db_path)
        # Compute equity history: cumulative sum of profit + 10k baseline
        rows = conn.execute(
            "SELECT timestamp, profit FROM trades "
            "WHERE status IN ('WIN','LOSS','PROFIT') "
            "AND timestamp >= datetime('now', '-90 days') "
            "ORDER BY timestamp"
        ).fetchall()
        conn.close()
        cum = 10000.0
        first_cross = None
        for ts, p in rows:
            cum += float(p or 0)
            if cum >= tier_threshold and first_cross is None:
                first_cross = dt.datetime.strptime(ts.split(".")[0], "%Y-%m-%d %H:%M:%S")
        if first_cross is None:
            # Crossed before our 90-day window — assume persisted
            return current_tier_idx, current_mult, f"tier_{current_tier_idx}_persisted_pre_window"
        days_in_tier = (dt.datetime.now() - first_cross).days
        if days_in_tier >= TIER_PERSIST_DAYS:
            return current_tier_idx, current_mult, f"tier_{current_tier_idx}_persisted_{days_in_tier}d"
        # Not enough days — fall back one tier
        return max(0, current_tier_idx - 1), TIERS[max(0, current_tier_idx - 1)][1], (
            f"tier_{current_tier_idx}_pending_{days_in_tier}d/{TIER_PERSIST_DAYS}d"
        )
    except Exception:
        # Conservative: use lower tier on uncertainty
        return max(0, current_tier_idx - 1), TIERS[max(0, current_tier_idx - 1)][1], "tier_uncertain"


def compounded_lot(base_lot: float, equity: Optional[float] = None) -> dict:
    """Return compounded lot using current tier eligibility.

    Env opt-in: QUANT_TIER_COMPOUNDING=1.

    Returns dict:
        lot: final compounded lot
        tier: tier index
        multiplier: applied multiplier
        status: persist status string
    """
    if os.environ.get("QUANT_TIER_COMPOUNDING") != "1":
        return {"lot": base_lot, "tier": 0, "multiplier": 1.0, "status": "disabled"}
    tier, mult, status = get_eligible_tier(equity=equity)
    return {
        "lot": round(base_lot * mult, 4),
        "tier": tier,
        "multiplier": mult,
        "status": status,
    }
