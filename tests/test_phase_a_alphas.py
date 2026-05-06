"""Tests for Phase A alphas + Phase B sizing + Phase C/D scaffolds."""
import datetime as dt
import numpy as np
import pytest


# ── Phase A: time alphas ───────────────────────────────────────────

def test_lbma_fix_window_morning():
    from src.analysis.time_alphas import in_lbma_fix_window
    # Mid morning fix: 10:30 UTC ±5 min = 10:25-11:05
    t = dt.datetime(2026, 5, 6, 10, 30, tzinfo=dt.timezone.utc)
    res = in_lbma_fix_window(t)
    assert res["in_window"] is True
    assert res["fix_time"] == "AM"


def test_lbma_outside_window():
    from src.analysis.time_alphas import in_lbma_fix_window
    t = dt.datetime(2026, 5, 6, 8, 0, tzinfo=dt.timezone.utc)
    res = in_lbma_fix_window(t)
    assert res["in_window"] is False


def test_january_seasonality_yes():
    from src.analysis.time_alphas import january_long_bias
    assert january_long_bias(dt.datetime(2026, 1, 15, tzinfo=dt.timezone.utc))
    assert january_long_bias(dt.datetime(2026, 2, 10, tzinfo=dt.timezone.utc))


def test_january_seasonality_no():
    from src.analysis.time_alphas import january_long_bias
    assert not january_long_bias(dt.datetime(2026, 5, 15, tzinfo=dt.timezone.utc))
    assert not january_long_bias(dt.datetime(2026, 2, 25, tzinfo=dt.timezone.utc))


def test_eom_window():
    from src.analysis.time_alphas import end_of_month_window
    # 2026-05 last day = 31. Days 29/30/31 are EOM
    assert end_of_month_window(dt.datetime(2026, 5, 31, tzinfo=dt.timezone.utc))
    assert end_of_month_window(dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc))
    assert not end_of_month_window(dt.datetime(2026, 5, 15, tzinfo=dt.timezone.utc))


# ── Phase B: sizing science ────────────────────────────────────────

def test_vol_target_multiplier():
    from src.risk.sizing import vol_target_multiplier
    # When realized vol = target → mult = 1.0
    assert vol_target_multiplier(0.08, target_vol=0.08) == 1.0
    # High vol → reduce
    assert vol_target_multiplier(0.16, target_vol=0.08) == 0.5
    # Low vol → increase, capped
    mult = vol_target_multiplier(0.04, target_vol=0.08)
    assert 1.4 < mult <= 1.5  # capped at 1.5


def test_dd_multiplier_at_peak():
    from src.risk.sizing import dd_multiplier
    # No drawdown → 1.0
    assert dd_multiplier(10000, 10000) == 1.0
    # 5% DD with k=2 → 0.95^2 = 0.9025
    m = dd_multiplier(9500, 10000)
    assert abs(m - 0.9025) < 0.001
    # 20% DD → 0.64
    m = dd_multiplier(8000, 10000)
    assert abs(m - 0.64) < 0.001


def test_dd_multiplier_floor():
    from src.risk.sizing import dd_multiplier
    # Catastrophic DD shouldn't return 0
    m = dd_multiplier(100, 10000)
    assert m >= 0.1


def test_scientific_size_default_off():
    """All toggles default OFF — return base lot × kelly only."""
    from src.risk.sizing import scientific_size
    result = scientific_size(
        kelly_fraction=0.5, base_lot=0.01,
        realized_vol_20d=0.10,
        current_equity=10000, peak_equity=10000,
        apply_vol_target=False, apply_dd_control=False, apply_ec_filter=False,
    )
    assert result["lot"] == 0.005  # 0.01 × 0.5
    assert result["skipped"] is False


def test_scientific_size_full_stack():
    """All toggles on — multipliers compose."""
    from src.risk.sizing import scientific_size
    result = scientific_size(
        kelly_fraction=0.5, base_lot=0.01,
        realized_vol_20d=0.10,  # higher than 0.08 target → vol mult 0.8
        current_equity=9500, peak_equity=10000,  # 5% DD → mult 0.9025
        apply_vol_target=True, apply_dd_control=True, apply_ec_filter=False,
    )
    # Expected: 0.01 × 0.5 × 0.8 × 0.9025 = 0.00361
    assert 0.003 < result["lot"] < 0.004
    assert result["breakdown"]["vol_target_mult"] == 0.8
    assert abs(result["breakdown"]["dd_mult"] - 0.9025) < 0.001


# ── Phase C: strategy scaffolds ────────────────────────────────────

def test_mean_reversion_oversold():
    """Oversold + capitulation volume → LONG fade signal."""
    from src.trading.strategies import mean_reversion
    import pandas as pd
    # Build df with closing crash + volume spike on last bar
    bars = 25
    closes = list(np.linspace(100, 99, bars - 1)) + [88]  # crash on last
    vols = [100] * (bars - 1) + [500]  # 5× volume spike
    df = pd.DataFrame({
        "close": closes,
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "volume": vols,
    })
    sig = mean_reversion.detect_setup(df, atr=2.0, rsi=20)
    assert sig is not None
    assert sig.direction == "LONG"


def test_mean_reversion_no_signal_normal():
    """Normal market → no signal."""
    from src.trading.strategies import mean_reversion
    import pandas as pd
    bars = 25
    df = pd.DataFrame({
        "close": np.linspace(100, 102, bars),
        "high": np.linspace(100.5, 102.5, bars),
        "low": np.linspace(99.5, 101.5, bars),
        "volume": [100] * bars,
    })
    sig = mean_reversion.detect_setup(df, atr=1.0, rsi=55)
    assert sig is None


def test_strategy_signal_dataclass():
    from src.trading.strategies import StrategySignal
    sig = StrategySignal(
        strategy_name="test", direction="LONG", confidence=0.7,
        entry=3300, sl=3290, tp=3320,
    )
    assert sig.strategy_name == "test"
    assert sig.direction == "LONG"


# ── Phase D: HRP allocator ─────────────────────────────────────────

def test_hrp_weights_sum_to_1():
    from src.risk.hrp_allocator import hrp_weights
    np.random.seed(42)
    returns = np.random.randn(100, 4) * 0.01  # 4 assets, 100 periods
    weights = hrp_weights(returns, ["A", "B", "C", "D"])
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.01


def test_hrp_falls_back_on_too_few():
    from src.risk.hrp_allocator import hrp_weights
    returns = np.array([[0.01, 0.02], [0.01, 0.02]])  # only 2 periods
    weights = hrp_weights(returns, ["A", "B"])
    # Should equal-weight fallback
    assert weights["A"] == 0.5
    assert weights["B"] == 0.5


def test_hrp_correlation_to_distance():
    from src.risk.hrp_allocator import correlation_to_distance
    corr = np.array([[1.0, 0.5], [0.5, 1.0]])
    d = correlation_to_distance(corr)
    # d_ii = 0; d_ij = sqrt(0.5 × (1 - 0.5)) = 0.5
    assert abs(d[0, 0]) < 0.001
    assert abs(d[0, 1] - 0.5) < 0.001


# ── End-to-end scaffold smoke ──────────────────────────────────────

def test_all_phase_a_modules_importable():
    """Smoke check — all phase A/B/C/D modules import without errors."""
    from src.analysis.time_alphas import in_lbma_fix_window  # noqa
    from src.analysis.gvz_regime import get_gvz_regime  # noqa
    from src.analysis.cot_bias import get_cot_extreme_bias  # noqa
    from src.risk.sizing import scientific_size  # noqa
    from src.risk.hrp_allocator import hrp_weights  # noqa
    from src.trading.strategies import StrategySignal  # noqa
    from src.trading.strategies import mean_reversion, vol_breakout, news_llm  # noqa
