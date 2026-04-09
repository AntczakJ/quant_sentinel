"""
tests/test_backtest.py — Tests for backtesting engine (metrics, Monte Carlo, equity)
"""

import pytest
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestEvaluatePredictions:
    def test_perfect_predictions(self):
        from src.backtest import evaluate_predictions
        y_true = np.array([1, 1, 0, 0, 1])
        y_pred = np.array([1, 1, 0, 0, 1])
        result = evaluate_predictions(y_true, y_pred)
        assert result["accuracy"] == 1.0
        assert result["mcc"] == 1.0
        assert result["f1"] == 1.0

    def test_random_predictions(self):
        from src.backtest import evaluate_predictions
        np.random.seed(42)
        y_true = np.random.randint(0, 2, 100)
        y_pred = np.random.randint(0, 2, 100)
        result = evaluate_predictions(y_true, y_pred)
        assert 0.0 <= result["accuracy"] <= 1.0
        assert -1.0 <= result["mcc"] <= 1.0

    def test_empty_input(self):
        from src.backtest import evaluate_predictions
        result = evaluate_predictions(np.array([]), np.array([]))
        assert result["accuracy"] == 0

    def test_includes_mcc(self):
        from src.backtest import evaluate_predictions
        result = evaluate_predictions(np.array([1, 0, 1]), np.array([1, 0, 0]))
        assert "mcc" in result
        assert "tp" in result
        assert "fp" in result


class TestEquityMetrics:
    def test_positive_returns(self):
        from src.backtest import compute_equity_metrics
        returns = np.array([0.01, 0.02, 0.01, -0.005, 0.015])
        result = compute_equity_metrics(returns)
        assert result["total_return"] > 0
        assert result["sharpe"] > 0
        assert result["max_drawdown"] >= 0
        assert "sortino" in result
        assert "calmar" in result
        assert "var_95" in result

    def test_negative_returns(self):
        from src.backtest import compute_equity_metrics
        returns = np.array([-0.01, -0.02, -0.01, -0.005])
        result = compute_equity_metrics(returns)
        assert result["total_return"] < 0
        assert result["max_drawdown"] > 0

    def test_empty_returns(self):
        from src.backtest import compute_equity_metrics
        result = compute_equity_metrics(np.array([]))
        assert result["sharpe"] == 0

    def test_win_rate_and_profit_factor(self):
        from src.backtest import compute_equity_metrics
        returns = np.array([0.05, -0.02, 0.03, -0.01, 0.04])
        result = compute_equity_metrics(returns)
        assert "win_rate" in result
        assert "profit_factor" in result
        assert result["win_rate"] == 0.6  # 3 wins / 5 total


class TestMonteCarlo:
    def test_simulation_returns_valid(self):
        from src.backtest import monte_carlo_simulation
        returns = np.random.normal(0.001, 0.02, 50)
        result = monte_carlo_simulation(returns, n_simulations=100)
        assert "n_simulations" in result
        assert result["n_simulations"] == 100
        assert "final_equity" in result
        assert "max_drawdown" in result
        assert "profitable_pct" in result
        assert 0 <= result["profitable_pct"] <= 100

    def test_insufficient_trades(self):
        from src.backtest import monte_carlo_simulation
        result = monte_carlo_simulation(np.array([0.01, 0.02]))
        assert "error" in result


class TestTransactionCosts:
    def test_costs_reduce_returns(self):
        from src.backtest import apply_transaction_costs
        returns = np.array([0.01, 0.02, -0.01])
        adjusted = apply_transaction_costs(returns, spread_pct=0.001)
        assert all(adjusted < returns)
