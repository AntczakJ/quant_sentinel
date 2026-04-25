"""Tests for walk-forward backtest harness."""
from datetime import datetime
import pytest

from src.backtest.walk_forward import (
    generate_windows, walk_forward, WalkForwardResults, WindowResult,
)


def test_generate_windows_basic():
    windows = generate_windows("2024-01-01", "2024-04-01",
                                train_days=30, test_days=7, step_days=7)
    assert len(windows) > 0
    # First window: train start = 2024-01-01
    assert windows[0][0] == datetime(2024, 1, 1)


def test_generate_windows_step_advance():
    windows = generate_windows("2024-01-01", "2024-04-01",
                                train_days=30, test_days=7, step_days=14)
    # Each next window advances by 14 days
    if len(windows) >= 2:
        diff_days = (windows[1][0] - windows[0][0]).days
        assert diff_days == 14


def test_generate_windows_respects_end():
    windows = generate_windows("2024-01-01", "2024-02-01",
                                train_days=30, test_days=7, step_days=7)
    for tr_s, tr_e, te_s, te_e in windows:
        assert te_e <= datetime(2024, 2, 1, 23, 59)


def test_walk_forward_with_mock_runner():
    """Walk-forward end-to-end with mock backtest runner."""
    def mock_runner(start, end):
        return {
            "total_trades": 10, "wins": 6, "losses": 3, "breakevens": 1,
            "win_rate_pct": 60.0, "profit_factor": 1.5,
            "cumulative_profit": 100.0, "max_drawdown_pct": -3.0,
            "return_pct": 1.0,
        }

    results = walk_forward(
        start_date="2024-01-01", end_date="2024-03-01",
        train_days=30, test_days=7, step_days=7,
        backtest_runner=mock_runner,
    )
    assert results.n_windows > 0
    agg = results.aggregate()
    assert agg["win_rate_mean"] == 60.0
    assert agg["profit_factor_mean"] == 1.5


def test_aggregate_handles_empty():
    results = WalkForwardResults(windows=[], config={})
    agg = results.aggregate()
    assert "error" in agg


def test_aggregate_skips_failed_windows():
    windows = [
        WindowResult(0, "2024-01-01", "2024-02-01", "2024-02-01", "2024-02-08",
                     10, 5, 5, 0, 50.0, 1.0, 0.0, 0.0),
        WindowResult(1, "2024-01-08", "2024-02-08", "2024-02-08", "2024-02-15",
                     0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, error="boom"),
    ]
    results = WalkForwardResults(windows=windows, config={})
    agg = results.aggregate()
    # Only the successful window counts
    assert agg["n_windows"] == 1
    assert agg["win_rate_mean"] == 50.0


def test_serialization():
    windows = [
        WindowResult(0, "2024-01-01", "2024-02-01", "2024-02-01", "2024-02-08",
                     10, 5, 5, 0, 50.0, 1.0, 0.0, 0.0),
    ]
    results = WalkForwardResults(windows=windows, config={"foo": "bar"})
    d = results.to_dict()
    assert "config" in d and "windows" in d and "aggregate" in d
