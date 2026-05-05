"""src/backtest/fill_model.py — realistic backtest fill simulation.

2026-05-05: shipped per comparative research adoption (#6) — biggest
backtest-vs-live gap closer. NautilusTrader-style separation of
FillModel + LatencyModel + FeeModel.

Today's backtest fillsuje na bar close — live ma spread + slippage +
broker latency + queue position. The Apr 2026 PF 2.14 / +7.43% result
and "lot inverse to outcome" finding are both suspect until we model
fills realistically.

Models composed:
  - **FillModel** — probabilistic fill at intended price, with spread
    + random slippage on the unfavored side.
  - **LatencyModel** — entry/exit timestamps shifted by configurable
    distribution (e.g., gamma(shape=2, scale=50ms)).
  - **FeeModel** — round-turn commission (e.g., $5/lot).

All env-tunable (QUANT_FILL_*, QUANT_LATENCY_*, QUANT_FEE_*) so existing
backtest stays at "perfect fills" by default — opt-in for realism mode.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from typing import Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Fill model ────────────────────────────────────────────────────────

@dataclass
class FillModel:
    """Probabilistic fill model. Defaults conservative — half-spread cost +
    occasional slippage during fast moves."""
    prob_fill: float = field(default_factory=lambda: _env_float("QUANT_FILL_PROB", 0.99))
    half_spread_pct: float = field(default_factory=lambda: _env_float("QUANT_FILL_HALF_SPREAD_PCT", 0.0003))
    prob_slippage: float = field(default_factory=lambda: _env_float("QUANT_FILL_PROB_SLIPPAGE", 0.10))
    slippage_pct_max: float = field(default_factory=lambda: _env_float("QUANT_FILL_SLIPPAGE_MAX_PCT", 0.0005))
    seed: Optional[int] = None

    def __post_init__(self):
        self._rng = random.Random(self.seed) if self.seed is not None else random

    def fill_entry(self, intended_price: float, side: str) -> Optional[float]:
        """Return realized fill price OR None if not filled.

        side: "LONG"/"SHORT". Entry side gets unfavorable half-spread:
              LONG fills above mid, SHORT below mid.
        """
        if self._rng.random() > self.prob_fill:
            return None  # rejected fill (rare, simulates broker decline)
        # Half-spread on the unfavored side
        if side.upper() == "LONG":
            adj = intended_price * (1.0 + self.half_spread_pct)
        else:
            adj = intended_price * (1.0 - self.half_spread_pct)
        # Random slippage event
        if self._rng.random() < self.prob_slippage:
            slip = self._rng.uniform(0, self.slippage_pct_max)
            if side.upper() == "LONG":
                adj = adj * (1.0 + slip)
            else:
                adj = adj * (1.0 - slip)
        return adj

    def fill_exit(self, intended_price: float, side: str,
                  reason: str = "tp") -> float:
        """Exit fill — half-spread always paid. SL exits get extra slippage
        (gap risk in fast moves). reason: "tp" or "sl"."""
        # Exit side: opposite of entry
        if side.upper() == "LONG":
            adj = intended_price * (1.0 - self.half_spread_pct)  # selling
        else:
            adj = intended_price * (1.0 + self.half_spread_pct)  # buying
        # SL exits in fast markets often slip past trigger
        if reason == "sl" and self._rng.random() < self.prob_slippage:
            slip = self._rng.uniform(0, self.slippage_pct_max * 2.0)  # 2× SL slip
            if side.upper() == "LONG":
                adj = adj * (1.0 - slip)  # SL fills BELOW intended
            else:
                adj = adj * (1.0 + slip)  # SL fills ABOVE intended
        return adj


# ── Latency model ─────────────────────────────────────────────────────

@dataclass
class LatencyModel:
    """Order placement latency. Default: gamma-distributed with median ~150ms,
    p95 ~300ms — matches retail broker FX/CFD round-trip."""
    median_ms: float = field(default_factory=lambda: _env_float("QUANT_LATENCY_MEDIAN_MS", 150.0))
    p95_ms: float = field(default_factory=lambda: _env_float("QUANT_LATENCY_P95_MS", 300.0))
    seed: Optional[int] = None

    def __post_init__(self):
        self._rng = random.Random(self.seed) if self.seed is not None else random

    def sample_ms(self) -> float:
        """Sample one latency in ms. Approximate gamma via log-normal."""
        if self.median_ms <= 0.0:
            return 0.0  # perfect-sim path
        median = self.median_ms
        p95 = max(self.p95_ms, median + 1.0)  # ensure p95 > median
        sigma = (p95 - median) / 1.645
        sigma = max(sigma, 1.0)
        import math
        mu = math.log(median)
        s = sigma / median
        return float(math.exp(self._rng.normalvariate(mu, max(s, 0.1))))


# ── Fee model ─────────────────────────────────────────────────────────

@dataclass
class FeeModel:
    """Round-turn commission. Defaults to $5 per standard lot — typical
    retail FX/CFD spread cost."""
    commission_per_lot_usd: float = field(default_factory=lambda: _env_float("QUANT_FEE_PER_LOT_USD", 5.0))

    def round_turn(self, lot: float) -> float:
        """Total $ commission for opening + closing one position."""
        return abs(lot) * self.commission_per_lot_usd


# ── Composed simulator ────────────────────────────────────────────────

@dataclass
class ExecutionSim:
    """Composed fill + latency + fee for a single trade.

    Usage:
        sim = ExecutionSim()
        entry = sim.fill.fill_entry(intended_entry, "LONG")
        latency_ms = sim.latency.sample_ms()
        exit_price = sim.fill.fill_exit(intended_tp, "LONG", reason="tp")
        commission = sim.fee.round_turn(lot)
        realized_pnl = (exit_price - entry) * 100 * lot - commission
    """
    fill: FillModel = field(default_factory=FillModel)
    latency: LatencyModel = field(default_factory=LatencyModel)
    fee: FeeModel = field(default_factory=FeeModel)

    @classmethod
    def from_env(cls) -> "ExecutionSim":
        """Construct from QUANT_* env vars."""
        return cls(fill=FillModel(), latency=LatencyModel(), fee=FeeModel())

    @classmethod
    def perfect(cls) -> "ExecutionSim":
        """Backward-compat: zero-cost / instantaneous fills."""
        return cls(
            fill=FillModel(prob_fill=1.0, half_spread_pct=0.0,
                           prob_slippage=0.0, slippage_pct_max=0.0),
            latency=LatencyModel(median_ms=0.0, p95_ms=0.0),
            fee=FeeModel(commission_per_lot_usd=0.0),
        )
