"""Tests for src/risk/portfolio.py."""
import pytest
from unittest.mock import MagicMock

from src.risk.portfolio import (
    trade_r_units, open_trades_r, would_breach_cap, get_max_open_r,
)


def test_trade_r_units_basic():
    """Trade risking 1% of $10k equity = R 0.01? Wait — R = $-risk / equity.
    SL distance $10, lot 0.01, oz 100 → $-risk = 10 × 100 × 0.01 = $10.
    On $10k equity → R = $10 / $10k = 0.001 (0.1%)."""
    r = trade_r_units(entry=3300, sl=3290, lot=0.01, equity=10000.0)
    assert r == pytest.approx(0.001, rel=0.01), f"Expected ~0.001, got {r}"


def test_trade_r_units_full_percent():
    """SL distance $100, lot 0.01, equity $10k → 1R = $100 → 0.01."""
    r = trade_r_units(entry=3400, sl=3300, lot=0.01, equity=10000.0)
    assert r == pytest.approx(0.01, rel=0.01)


def test_trade_r_units_invalid_returns_zero():
    assert trade_r_units(0, 100, 0.01) == 0.0
    assert trade_r_units(100, 0, 0.01) == 0.0
    assert trade_r_units(100, 100, 0) == 0.0
    assert trade_r_units(100, 100, 0.01, equity=0) == 0.0


def test_open_trades_r_sums_correctly():
    db = MagicMock()
    # Two open trades: one risking $10, one risking $20 on $10k equity
    db._query.return_value = [
        (3300, 3290, 0.01),  # $-risk=$10 → R=0.001
        (3400, 3380, 0.01),  # $-risk=$20 → R=0.002
    ]
    db.get_param.return_value = 10000.0
    total = open_trades_r(db)
    assert total == pytest.approx(0.003, rel=0.01)


def test_get_max_open_r_default(monkeypatch):
    monkeypatch.delenv("QUANT_MAX_OPEN_R", raising=False)
    assert get_max_open_r() == 2.0


def test_get_max_open_r_env(monkeypatch):
    monkeypatch.setenv("QUANT_MAX_OPEN_R", "3.5")
    assert get_max_open_r() == 3.5


def test_would_breach_cap_under_limit():
    """Existing 0.5R + new 0.5R = 1.0R, under default 2.0 cap."""
    db = MagicMock()
    db._query.return_value = [
        # Existing trade with $5000 risk on $10k equity → 0.5R
        (3500, 3000, 0.10),
    ]
    db.get_param.return_value = 10000.0
    # New trade $5000 risk → 0.5R additional
    breaches, info = would_breach_cap(db, new_entry=3500, new_sl=3000, new_lot=0.10)
    assert not breaches
    assert info["total_r_after"] == pytest.approx(1.0, rel=0.01)


def test_would_breach_cap_over_limit():
    """3 large open trades + a 4th would breach 2.0R cap."""
    db = MagicMock()
    db._query.return_value = [
        (3500, 3000, 0.15),  # 0.75R
        (3500, 3000, 0.15),  # 0.75R
        (3500, 3000, 0.10),  # 0.50R = total 2.00R existing
    ]
    db.get_param.return_value = 10000.0
    # New trade adds 0.5R → 2.5R total > 2.0R cap
    breaches, info = would_breach_cap(db, 3500, 3000, 0.10)
    assert breaches
    assert info["total_r_after"] > info["cap"]
