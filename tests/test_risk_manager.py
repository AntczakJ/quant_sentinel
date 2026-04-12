"""
tests/test_risk_manager.py — Tests for the Risk Management module (Phase 1)

Tests:
  - Kelly Criterion calculation
  - Circuit breaker checks
  - Portfolio heat tracking
  - Slippage model (session-aware)
  - Kill switch (halt/resume)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestKellyCriterion:
    """Test Fractional Kelly position sizing."""

    def test_kelly_returns_valid_risk_percent(self):
        from src.trading.risk_manager import RiskManager
        rm = RiskManager()
        result = rm.compute_kelly_risk_percent(default_risk=1.0)
        # Should return a value in valid range [0.25, 3.0] or default 1.0
        assert 0.25 <= result <= 3.0

    def test_kelly_clamps_to_range(self):
        from src.trading.risk_manager import RiskManager
        rm = RiskManager()
        result = rm.compute_kelly_risk_percent(default_risk=1.0)
        assert 0.25 <= result <= 3.0


class TestCircuitBreakers:
    """Test drawdown and consecutive loss circuit breakers."""

    def test_can_trade_when_not_halted(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm._halted = False
        rm._last_cooldown_until = None
        can, reason = rm.check_circuit_breakers(10000)
        assert can is True
        assert reason == "OK"

    def test_blocked_when_halted(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm.halt("test halt")
        can, reason = rm.check_circuit_breakers(10000)
        assert can is False
        assert "halted" in reason.lower() or "halt" in reason.lower()
        rm.resume()  # cleanup

    def test_daily_risk_multiplier_normal(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        mult = rm.get_daily_risk_multiplier(10000)
        assert 0.0 <= mult <= 1.0


class TestSlippageModel:
    """Test session-aware spread model."""

    def test_spread_returns_float(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        spread = rm.get_spread_buffer()
        assert isinstance(spread, float)
        assert spread >= 0

    def test_spread_varies_by_session(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        asian = rm.get_spread_buffer("asian")
        ny = rm.get_spread_buffer("new_york")
        assert asian < ny  # Asian has tighter spreads

    def test_slippage_adjustment(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        entry, sl, tp = rm.adjust_for_slippage(2000.0, 1990.0, 2020.0, "LONG", "london")
        assert entry > 2000.0  # buy higher due to spread
        assert sl < 1990.0     # SL slightly lower
        assert tp < 2020.0     # TP slightly lower


class TestPortfolioHeat:
    """Test aggregate risk tracking."""

    def test_portfolio_heat_returns_tuple(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        can, heat = rm.check_portfolio_heat(10000, 50)
        assert isinstance(can, bool)
        assert isinstance(heat, float)
        assert heat >= 0


class TestVolatilityTargeting:
    """Test volatility-adjusted position sizing."""

    def test_returns_1_for_invalid_atr(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        assert rm.compute_volatility_multiplier(0) == 1.0
        assert rm.compute_volatility_multiplier(-1) == 1.0
        assert rm.compute_volatility_multiplier(None) == 1.0

    def test_higher_vol_reduces_multiplier(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        high_vol = rm.compute_volatility_multiplier(20.0)
        low_vol = rm.compute_volatility_multiplier(2.0)
        assert high_vol < low_vol

    def test_multiplier_is_clamped(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        extreme_high = rm.compute_volatility_multiplier(1000.0)
        extreme_low = rm.compute_volatility_multiplier(0.01)
        assert 0.4 <= extreme_high <= 1.8
        assert 0.4 <= extreme_low <= 1.8


class TestKillSwitch:
    """Test halt/resume mechanism."""

    def test_halt_and_resume(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        rm.halt("unit test")
        assert rm.is_halted is True
        rm.resume()
        assert rm.is_halted is False

    def test_get_status(self):
        from src.trading.risk_manager import get_risk_manager
        rm = get_risk_manager()
        status = rm.get_status()
        assert "halted" in status
        assert "daily_loss_pct" in status
        assert "kelly_risk_pct" in status
        assert "session" in status
        assert "spread_buffer" in status
