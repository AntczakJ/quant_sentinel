"""
src/analysis/regime_routing.py — Phase V2 regime-aware strategy routing.

The Phase V1 classifier (`classify_regime`) is currently cosmetic — it's
exposed via /api/macro/context for the dashboard but `scanner.py` does
NOT consume it for any decision. Per CLAUDE.md research note, this is
"likely the biggest single WR lever — bigger than any new voter."

This module ships the routing layer behind an env flag so live behavior
is unchanged until validated by backtest A/B. Set `QUANT_REGIME_V2=1` to
activate.

Routing dimensions:
  1. min_score floor per (regime, tf) — block weak setups in chop, allow
     looser in strong trends.
  2. direction filter per regime — e.g., trending_high_vol bull only LONG.
  3. voter weight multipliers per regime — boost trend voters in trends,
     boost MR voters (smc, attention) in ranging.

All overrides are READ-ONLY (return values to caller); the existing
scoring/filter pipeline applies them. This keeps the routing layer
reviewable in isolation.

Usage from scanner.py (when activated):
    from src.analysis.regime_routing import get_routing
    if os.environ.get("QUANT_REGIME_V2") == "1":
        routing = get_routing(regime, tf)
        if routing.block_entry:
            log_rejection("regime_v2_block")
            continue
        min_score = routing.min_score_floor or default_min_score
        if direction not in routing.allowed_directions:
            continue
        # voter weight overrides applied later in ensemble call
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

Regime = Literal["squeeze", "trending_high_vol", "trending_low_vol", "ranging"]
MacroRegime = Literal["zielony", "czerwony", "neutralny"]
TF = Literal["5m", "15m", "30m", "1h", "4h"]
Direction = Literal["LONG", "SHORT"]


@dataclass
class RegimeRouting:
    """Per-(regime, tf) routing decisions.

    block_entry        — drop the cascade for this TF entirely
    min_score_floor    — override the dynamic_params min_score_<tf>
    allowed_directions — restrict to LONG / SHORT / both
    voter_weight_mult  — per-voter multiplier dict applied to ensemble weights
    notes              — human-readable rationale for the dashboard / audit log
    """
    block_entry: bool = False
    min_score_floor: float | None = None
    allowed_directions: tuple[Direction, ...] = ("LONG", "SHORT")
    voter_weight_mult: dict[str, float] = field(default_factory=dict)
    notes: str = ""


# ── Routing matrix ─────────────────────────────────────────────────────
# Calibrated from research note + factor_edge_2026-05-04.md findings:
#   - bos +21.8pp WR (trend follow signal)
#   - macro -13.9pp (counter-signal? leads into bad LONG in bull regime)
#   - overlap session 51.5% WR vs london 14.3%
#
# Conservative defaults — when in doubt, use "ranging" routing.

_ROUTING_MATRIX: dict[Regime, dict[TF, RegimeRouting]] = {
    # SQUEEZE — bands compressed, breakout direction unknown.
    # Block all entries until breakout direction is clear.
    "squeeze": {
        tf: RegimeRouting(
            block_entry=True,
            notes="squeeze: wait for breakout direction"
        )
        for tf in ("5m", "15m", "30m", "1h", "4h")
    },
    # TRENDING HIGH VOL — strong directional move, ATR expanded.
    # Trust trend voters (lstm/dqn/v2_xgb), boost their weight.
    # Lower min_score floor since trend continuation has natural edge.
    "trending_high_vol": {
        "5m":  RegimeRouting(min_score_floor=40, voter_weight_mult={"lstm": 1.3, "dqn": 1.3, "v2_xgb": 1.2}, notes="trend: relax threshold, boost trend voters"),
        "15m": RegimeRouting(min_score_floor=42, voter_weight_mult={"lstm": 1.3, "dqn": 1.3, "v2_xgb": 1.2}, notes="trend: relax threshold, boost trend voters"),
        "30m": RegimeRouting(min_score_floor=45, voter_weight_mult={"lstm": 1.2, "dqn": 1.2}, notes="trend: standard"),
        "1h":  RegimeRouting(min_score_floor=48, voter_weight_mult={"lstm": 1.1}, notes="trend HTF: tighter"),
        "4h":  RegimeRouting(min_score_floor=50, notes="trend HTF: standard"),
    },
    # TRENDING LOW VOL — directional but ATR muted.
    # Standard routing, slight boost to SMC voter (it shines on retracements).
    "trending_low_vol": {
        "5m":  RegimeRouting(min_score_floor=45, voter_weight_mult={"smc": 1.15, "attention": 1.10}, notes="trend low-vol: SMC retracements"),
        "15m": RegimeRouting(min_score_floor=48, voter_weight_mult={"smc": 1.15, "attention": 1.10}, notes=""),
        "30m": RegimeRouting(min_score_floor=50, voter_weight_mult={"smc": 1.10}, notes=""),
        "1h":  RegimeRouting(min_score_floor=52, notes=""),
        "4h":  RegimeRouting(min_score_floor=55, notes=""),
    },
    # RANGING — chop, no clear direction.
    # Tighter thresholds (only the best setups), boost mean-reversion voters.
    # Still allow both directions but require A grade or higher.
    "ranging": {
        "5m":  RegimeRouting(min_score_floor=55, voter_weight_mult={"smc": 1.20, "attention": 1.20, "lstm": 0.7, "dqn": 0.7}, notes="ranging: SMC/attention only, mute trend voters"),
        "15m": RegimeRouting(min_score_floor=55, voter_weight_mult={"smc": 1.20, "attention": 1.20, "lstm": 0.7, "dqn": 0.7}, notes=""),
        "30m": RegimeRouting(min_score_floor=58, voter_weight_mult={"smc": 1.15, "attention": 1.15}, notes=""),
        "1h":  RegimeRouting(min_score_floor=60, voter_weight_mult={"smc": 1.10}, notes=""),
        "4h":  RegimeRouting(min_score_floor=62, notes="ranging HTF: very tight"),
    },
}


# Macro overlay — applied AFTER market_regime routing.
# In strong macro bias, restrict counter-direction trades.
_MACRO_DIRECTION_FILTER: dict[MacroRegime, tuple[Direction, ...]] = {
    "zielony": ("LONG",),         # bullish gold macro → only LONG
    "czerwony": ("SHORT",),       # bearish gold macro → only SHORT
    "neutralny": ("LONG", "SHORT"),
}


def get_routing(
    market_regime: Regime,
    tf: TF,
    macro_regime: MacroRegime | None = None,
) -> RegimeRouting:
    """Return the routing decision for the given (market_regime, tf, macro_regime)."""
    base = _ROUTING_MATRIX.get(market_regime, {}).get(tf) or RegimeRouting()
    if macro_regime and macro_regime in _MACRO_DIRECTION_FILTER:
        macro_dirs = _MACRO_DIRECTION_FILTER[macro_regime]
        # Intersect existing allowed_directions with macro filter
        new_allowed = tuple(d for d in base.allowed_directions if d in macro_dirs)
        if not new_allowed:
            # Conflict — macro forbids both. Block entry.
            return RegimeRouting(
                block_entry=True,
                notes=f"{base.notes} + macro={macro_regime} blocks all directions",
            )
        # Mutate a copy
        return RegimeRouting(
            block_entry=base.block_entry,
            min_score_floor=base.min_score_floor,
            allowed_directions=new_allowed,
            voter_weight_mult=dict(base.voter_weight_mult),
            notes=f"{base.notes} + macro={macro_regime}",
        )
    return base


def is_active() -> bool:
    """Phase V2 is OFF by default — opt-in via env flag."""
    return os.environ.get("QUANT_REGIME_V2") == "1"


def explain_routing(market_regime: Regime, tf: TF, macro_regime: MacroRegime | None = None) -> dict:
    """Diagnostic: return the routing decision + inputs as a dict for dashboards."""
    r = get_routing(market_regime, tf, macro_regime)
    return {
        "active": is_active(),
        "market_regime": market_regime,
        "tf": tf,
        "macro_regime": macro_regime,
        "block_entry": r.block_entry,
        "min_score_floor": r.min_score_floor,
        "allowed_directions": list(r.allowed_directions),
        "voter_weight_mult": dict(r.voter_weight_mult),
        "notes": r.notes,
    }
