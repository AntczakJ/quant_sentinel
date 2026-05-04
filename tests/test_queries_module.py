"""Regression tests for src/core/queries/ — domain-split DB helpers.

Locks in API contract: function signatures stable, returns expected
shapes, doesn't crash on edge cases.
"""
import pytest


def test_recent_trades_returns_list():
    from src.core.queries.trades import recent_trades
    result = recent_trades(limit=5)
    assert isinstance(result, list)
    if result:
        assert isinstance(result[0], dict)
        assert "id" in result[0]


def test_recent_trades_with_status_filter():
    from src.core.queries.trades import recent_trades
    result = recent_trades(limit=10, status_filter="WIN")
    if result:
        assert all(t["status"] == "WIN" for t in result)


def test_win_rate_zero_trades_safe():
    from src.core.queries.trades import win_rate
    # If filter excludes everything, returns zero-shape dict, not crash
    result = win_rate(direction_filter="NEVERMATCHED")
    assert "n" in result
    assert "wr_pct" in result
    assert result["n"] >= 0


def test_win_rate_returns_dict_keys():
    from src.core.queries.trades import win_rate
    result = win_rate(window_n=10)
    assert set(result.keys()) == {"n", "wins", "wr_pct", "total_pl"}


def test_open_trades_count_returns_int():
    from src.core.queries.trades import open_trades_count
    n = open_trades_count()
    assert isinstance(n, int)
    assert n >= 0


def test_params_get_default():
    from src.core.queries.params import get
    val = get("definitely_not_a_real_key_12345", default="fallback")
    assert val == "fallback"


def test_params_get_float_coerces():
    from src.core.queries.params import get_float
    val = get_float("missing_key", default=2.5)
    assert val == 2.5
    assert isinstance(val, float)


def test_params_get_bool_strict():
    from src.core.queries.params import get_bool
    assert get_bool("missing_key", default=False) is False
    assert get_bool("missing_key", default=True) is True


def test_params_get_all_with_prefix_returns_dict():
    from src.core.queries.params import get_all_with_prefix
    result = get_all_with_prefix("weight_")
    assert isinstance(result, dict)
    # All keys should start with 'weight_'
    for k in result:
        assert k.startswith("weight_")


def test_trades_in_range_returns_list():
    from src.core.queries.trades import trades_in_range
    # Wide range — should return all closed trades
    result = trades_in_range("2025-01-01", "2027-01-01")
    assert isinstance(result, list)
