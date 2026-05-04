"""
src/trading/confluence_v2.py — next-generation confluence scoring (DRAFT).

Designed 2026-05-04 evening from 10-agent deep research convergence:
- Modern SMC literature (OTE, IFVG, breaker blocks, anchored VWAP)
- Confluence audit (current binary count, no time-decay, redundant signals)
- Bayesian factor research (5 correlated pairs to merge)
- Pre-entry gate audit (7 missing high-impact gates)
- Volume profile gap (XAU volume=0 makes 5 features dead-weight)

This module is **NOT YET WIRED** into scanner. Designed as drop-in replacement
for confluence_count + score_setup_quality once validated on N>=50 cohort.

Key design decisions:

1. **Merged factor pairs** (correlation > 0.6):
   - structure_break = bos OR choch
   - ob_presence = ob_main OR ob_count >= 1
   - liquidity_event = grab AND mss
   - regime_confirmation = macro AND ichimoku same direction
   - reversal_signal = rsi_divergence OR (inside_bar + RSI extreme)

2. **Time-decay on ALL signals** (not just OB):
   weight = max(0.3, exp(-0.04 * bars_ago))
   — 100% at bar 0, 67% at bar 10, 30% floor at bar 30+

3. **Signal class separation**:
   - structural: 1+ required (structure_break, liquidity_event, ob_presence)
   - confirmation: 1+ required (rsi_optimal, engulfing, pin_bar)
   - context: 0+ allowed (regime_confirmation, killzone, vwap_align)
   Total: structural >= 1 AND confirmation >= 1 → setup valid.

4. **Direction-conditional weighting** read from hierarchical Bayesian
   table `factor_combo_outcomes` (sparse → empirical Bayes shrinkage to
   regime-marginal estimate).

5. **New high-impact factors** (ICT 2024-2026):
   - ote_zone (50-79% retracement of dealing range)
   - ifvg (inversion FVG retest after sweep)
   - breaker_block (failed OB flipped polarity)
   - anchored_vwap_confluence (price near multiple VWAP anchors)

API (drop-in replacement for confluence_count + score):
    from src.trading.confluence_v2 import score_v2
    result = score_v2(analysis, direction, tf, macro_regime)
    # result: dict with score, p_win_estimate, factors_v2, conflicts, decay_applied
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ── Config: signal class membership ──────────────────────────────────

STRUCTURAL_FACTORS = {"structure_break", "liquidity_event", "ob_presence", "breaker_block"}
CONFIRMATION_FACTORS = {"rsi_optimal", "engulfing", "pin_bar", "ifvg"}
CONTEXT_FACTORS = {"regime_confirmation", "killzone", "vwap_align", "ote_zone"}


# ── Time-decay function ──────────────────────────────────────────────

def time_decay(bars_ago: int, half_life: float = 17.0, floor: float = 0.3) -> float:
    """Exponential decay with floor.

    bars_ago=0 → 1.0
    bars_ago=10 → 0.67 (close to half-life)
    bars_ago=17 → 0.5 (half-life)
    bars_ago=30 → 0.30 (floor)
    """
    if bars_ago < 0:
        bars_ago = 0
    raw = math.exp(-math.log(2) / half_life * bars_ago)
    return max(floor, raw)


# ── Factor merging (5 correlated pairs) ──────────────────────────────

def derive_merged_factors(analysis: dict, direction: str) -> dict[str, float]:
    """Compute merged factor presence + age from raw analysis dict.

    Returns: dict of factor_name → strength [0.0..1.0]
    where 0 = absent, 1 = fresh+strong, fractional = decayed/weakened.
    """
    out: dict[str, float] = {}

    # 1. structure_break = bos OR choch (most-recent age wins)
    bos_age = analysis.get("bos_bars_ago")
    choch_age = analysis.get("choch_bars_ago")
    bos_match = (analysis.get("bos_bullish") and direction == "LONG") or \
                (analysis.get("bos_bearish") and direction == "SHORT")
    choch_match = (analysis.get("choch_bullish") and direction == "LONG") or \
                  (analysis.get("choch_bearish") and direction == "SHORT")
    if bos_match or choch_match:
        # Use freshest age
        ages = []
        if bos_match and bos_age is not None:
            ages.append(bos_age)
        if choch_match and choch_age is not None:
            ages.append(choch_age)
        out["structure_break"] = time_decay(min(ages)) if ages else 0.5

    # 2. ob_presence = ob_main OR ob_count
    if analysis.get("ob_price") is not None:
        ob_age = analysis.get("ob_bars_ago", 10)
        out["ob_presence"] = time_decay(ob_age)
    elif (analysis.get("ob_count") or 0) >= 1:
        out["ob_presence"] = 0.5  # weaker — generic OB count

    # 3. liquidity_event = grab AND mss (causal pair)
    if analysis.get("liquidity_grab") and analysis.get("mss"):
        grab_dir = analysis.get("liquidity_grab_dir", "")
        mss_dir = analysis.get("mss_direction", "")
        # Direction must match
        expected = "bullish" if direction == "LONG" else "bearish"
        if grab_dir == expected and mss_dir == expected:
            grab_age = analysis.get("grab_bars_ago", 5)
            out["liquidity_event"] = time_decay(grab_age)

    # 4. regime_confirmation = macro + ichimoku same direction
    macro_regime = analysis.get("macro_regime", "neutralny")
    ichi_match = (
        (direction == "LONG" and analysis.get("ichimoku_above_cloud") and macro_regime == "zielony")
        or (direction == "SHORT" and analysis.get("ichimoku_below_cloud") and macro_regime == "czerwony")
    )
    if ichi_match:
        out["regime_confirmation"] = 1.0

    # 5. reversal_signal = rsi_divergence OR (extreme RSI + inside_bar)
    rsi = analysis.get("rsi", 50)
    has_div = (
        (direction == "LONG" and analysis.get("rsi_divergence_bullish"))
        or (direction == "SHORT" and analysis.get("rsi_divergence_bearish"))
    )
    inside_bar_extreme = (
        analysis.get("inside_bar")
        and ((direction == "LONG" and rsi < 30) or (direction == "SHORT" and rsi > 70))
    )
    if has_div or inside_bar_extreme:
        out["reversal_signal"] = 0.8 if has_div else 0.5

    # ── Confirmation factors (no merge) ────────────────────────────
    # rsi_optimal
    if direction == "LONG" and 35 <= rsi <= 50:
        out["rsi_optimal"] = 1.0
    elif direction == "SHORT" and 50 <= rsi <= 65:
        out["rsi_optimal"] = 1.0

    # engulfing (direction-aligned)
    eng_score = analysis.get("engulfing_score", 0)
    if (direction == "LONG" and analysis.get("engulfing_dir") == "bullish") or \
       (direction == "SHORT" and analysis.get("engulfing_dir") == "bearish"):
        if abs(eng_score) >= 0.5:
            out["engulfing"] = abs(eng_score)

    # pin_bar
    pin_score = analysis.get("pin_bar_score", 0)
    if (direction == "LONG" and analysis.get("pin_bar_dir") == "bullish") or \
       (direction == "SHORT" and analysis.get("pin_bar_dir") == "bearish"):
        if abs(pin_score) >= 0.5:
            out["pin_bar"] = abs(pin_score)

    # ── Context factors ────────────────────────────────────────────
    if analysis.get("is_killzone"):
        out["killzone"] = 1.0

    if analysis.get("vwap_above") is not None:
        # Bonus when LONG above VWAP, SHORT below — trending entry
        if (direction == "LONG" and analysis.get("vwap_above"))  or \
           (direction == "SHORT" and not analysis.get("vwap_above")):
            out["vwap_align"] = 1.0

    # ── New ICT 2024+ factors (placeholders — detection logic TBD) ──
    if analysis.get("ote_zone"):
        out["ote_zone"] = 1.0

    if analysis.get("ifvg_retest"):
        out["ifvg"] = 1.0

    if analysis.get("breaker_block"):
        out["breaker_block"] = 0.8

    return out


# ── Conflict detector ─────────────────────────────────────────────────

def detect_conflicts(analysis: dict, direction: str) -> list[str]:
    """Surface signals that contradict each other within the same setup.

    Examples:
      - LONG with bearish FVG nearby
      - SHORT with bullish OB nearby
      - LONG in czerwony regime
    """
    conflicts = []

    # FVG direction conflict
    fvg_dir = analysis.get("fvg_dir") or analysis.get("fvg_type")
    if direction == "LONG" and fvg_dir == "bearish":
        conflicts.append("fvg_bearish_vs_LONG")
    elif direction == "SHORT" and fvg_dir == "bullish":
        conflicts.append("fvg_bullish_vs_SHORT")

    # Macro regime mismatch (already penalized in score, but flag for UI)
    macro = analysis.get("macro_regime")
    if direction == "LONG" and macro == "czerwony":
        conflicts.append("LONG_in_czerwony")
    elif direction == "SHORT" and macro == "zielony":
        conflicts.append("SHORT_in_zielony")

    # Trend conflict
    trend = (analysis.get("trend") or "").lower()
    if direction == "LONG" and "bear" in trend:
        conflicts.append("LONG_with_bear_trend")
    elif direction == "SHORT" and "bull" in trend:
        conflicts.append("SHORT_with_bull_trend")

    return conflicts


@dataclass
class ConfluenceV2Result:
    score: float
    p_win_estimate: float
    factors_v2: dict[str, float] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    structural_count: int = 0
    confirmation_count: int = 0
    context_count: int = 0
    valid: bool = False
    reason: str = ""


def score_v2(
    analysis: dict,
    direction: str,
    tf: str = "5m",
    macro_regime: Optional[str] = None,
) -> ConfluenceV2Result:
    """Compute confluence_v2 score.

    Validity rule: structural >= 1 AND confirmation >= 1.
    Final score in 0..100, with conflicts subtracting points.
    p_win_estimate is a Bayesian estimate (placeholder until factor_combo_outcomes
    table wired up).
    """
    factors = derive_merged_factors(analysis, direction)
    conflicts = detect_conflicts(analysis, direction)

    structural_count = sum(1 for f in factors if f in STRUCTURAL_FACTORS)
    confirmation_count = sum(1 for f in factors if f in CONFIRMATION_FACTORS)
    context_count = sum(1 for f in factors if f in CONTEXT_FACTORS)

    # Validity: must have at least one structural + one confirmation
    valid = structural_count >= 1 and confirmation_count >= 1
    reason = ""
    if not valid:
        if structural_count < 1:
            reason = "no_structural_factor"
        else:
            reason = "no_confirmation_factor"

    # Score: weighted sum (placeholders until factor_combo_outcomes ready)
    # Structural: 25 points each, Confirmation: 15, Context: 8
    # Time-decay applied via factor strength
    score = 0.0
    for f, strength in factors.items():
        if f in STRUCTURAL_FACTORS:
            score += 25 * strength
        elif f in CONFIRMATION_FACTORS:
            score += 15 * strength
        elif f in CONTEXT_FACTORS:
            score += 8 * strength

    # Conflict penalty
    score -= len(conflicts) * 10

    # Cap at 100, floor at 0
    score = max(0.0, min(100.0, score))

    # P(WIN) estimate (placeholder — until hierarchical Bayesian ready)
    # Anchor at cohort baseline 33% with score-weighted bonus.
    # Once factor_combo_outcomes table exists, this becomes lookup.
    p_win = 0.33 + (score - 50) * 0.005
    p_win = max(0.0, min(1.0, p_win))

    return ConfluenceV2Result(
        score=round(score, 1),
        p_win_estimate=round(p_win, 3),
        factors_v2=factors,
        conflicts=conflicts,
        structural_count=structural_count,
        confirmation_count=confirmation_count,
        context_count=context_count,
        valid=valid,
        reason=reason,
    )
