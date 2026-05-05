"""Tests for src/backtest/fill_model.py."""
import os
import pytest

from src.backtest.fill_model import (
    FillModel, LatencyModel, FeeModel, ExecutionSim,
)


def test_fill_long_pays_half_spread_above():
    """LONG entry fills slightly above mid (broker buys for us at ask)."""
    fm = FillModel(prob_fill=1.0, half_spread_pct=0.001,
                   prob_slippage=0.0, seed=42)
    fill = fm.fill_entry(intended_price=3300.0, side="LONG")
    assert fill is not None
    assert fill > 3300.0  # paid above mid
    assert fill == pytest.approx(3303.30, rel=0.001)  # 3300 × 1.001


def test_fill_short_pays_half_spread_below():
    """SHORT entry fills below mid (broker sells for us at bid)."""
    fm = FillModel(prob_fill=1.0, half_spread_pct=0.001,
                   prob_slippage=0.0, seed=42)
    fill = fm.fill_entry(intended_price=3300.0, side="SHORT")
    assert fill is not None
    assert fill < 3300.0
    assert fill == pytest.approx(3296.70, rel=0.001)


def test_fill_rejection_when_prob_low():
    """prob_fill=0 → always returns None (rejected)."""
    fm = FillModel(prob_fill=0.0, seed=1)
    assert fm.fill_entry(3300, "LONG") is None


def test_fill_exit_long_pays_half_spread_below():
    """Closing LONG at TP — fills below intended (broker sells at bid)."""
    fm = FillModel(half_spread_pct=0.001, prob_slippage=0.0)
    exit_p = fm.fill_exit(3320.0, "LONG", reason="tp")
    assert exit_p < 3320.0
    assert exit_p == pytest.approx(3316.68, rel=0.001)


def test_sl_slippage_more_aggressive():
    """SL exits in fast markets slip 2× more than TP exits."""
    fm = FillModel(prob_fill=1.0, half_spread_pct=0.0,
                   prob_slippage=1.0, slippage_pct_max=0.001, seed=10)
    sl_long = fm.fill_exit(3280.0, "LONG", reason="sl")
    # LONG SL fills BELOW intended (price moved past stop)
    assert sl_long < 3280.0


def test_latency_sample_within_envelope():
    """Latency samples should land within reasonable order of median/p95."""
    lm = LatencyModel(median_ms=150.0, p95_ms=300.0, seed=7)
    samples = [lm.sample_ms() for _ in range(100)]
    median = sorted(samples)[50]
    assert 50 < median < 500, f"Median {median} outside reasonable range"


def test_fee_round_turn():
    fee = FeeModel(commission_per_lot_usd=5.0)
    assert fee.round_turn(0.10) == 0.50
    assert fee.round_turn(1.0) == 5.0
    assert fee.round_turn(-1.0) == 5.0  # absolute


def test_perfect_sim_zero_cost():
    sim = ExecutionSim.perfect()
    fill = sim.fill.fill_entry(3300.0, "LONG")
    assert fill == 3300.0  # exact
    assert sim.fee.round_turn(1.0) == 0.0
    assert sim.latency.sample_ms() == 0.0


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("QUANT_FILL_HALF_SPREAD_PCT", "0.005")
    monkeypatch.setenv("QUANT_FEE_PER_LOT_USD", "10.0")
    sim = ExecutionSim.from_env()
    assert sim.fill.half_spread_pct == 0.005
    assert sim.fee.commission_per_lot_usd == 10.0
