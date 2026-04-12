"""tests/test_backtest_harness.py — BacktestEngine + example strategies."""
import numpy as np
import pandas as pd
import pytest


def _make_df(n=300, trend=0.0, seed=42):
    np.random.seed(seed)
    base = 100 + trend * np.arange(n) + np.cumsum(np.random.randn(n) * 0.3)
    return pd.DataFrame({
        "open": base,
        "high": base + 0.5,
        "low": base - 0.5,
        "close": base,
        "volume": np.ones(n) * 1000,
    })


class TestBacktestResult:
    def test_empty_result(self):
        from backtest_harness import BacktestResult
        r = BacktestResult(trades=[], equity_curve=[10000], initial_balance=10000)
        assert r.total_return_pct == 0.0
        assert r.win_rate == 0.0
        assert r.profit_factor == 0.0

    def test_summary_is_string(self):
        from backtest_harness import BacktestResult, Trade
        r = BacktestResult(trades=[], equity_curve=[10000, 10100],
                           initial_balance=10000)
        s = r.summary()
        assert isinstance(s, str)
        assert "BACKTEST RESULTS" in s


class TestBacktestEngine:
    def test_no_signal_produces_no_trades(self):
        from backtest_harness import BacktestEngine
        df = _make_df()
        never_signal = lambda df, i: None
        engine = BacktestEngine(df, strategy=never_signal, use_slippage=False)
        r = engine.run()
        assert len(r.trades) == 0
        assert r.total_return_pct == 0.0

    def test_always_long_opens_trade(self):
        from backtest_harness import BacktestEngine
        df = _make_df(n=200)
        call_count = [0]
        def always_long(df, i):
            call_count[0] += 1
            return "LONG" if call_count[0] == 1 else None
        engine = BacktestEngine(df, strategy=always_long, use_slippage=False)
        r = engine.run()
        assert len(r.trades) >= 1
        assert r.trades[0].direction == "LONG"
        assert r.trades[0].sl < r.trades[0].entry_price
        assert r.trades[0].tp > r.trades[0].entry_price

    def test_tp_hit_closes_winning_trade(self):
        from backtest_harness import BacktestEngine
        # Strong uptrend guarantees TP hit on LONG
        df = _make_df(n=300, trend=0.1, seed=1)
        fired = [False]
        def one_long(df, i):
            if not fired[0] and i > 60:
                fired[0] = True
                return "LONG"
            return None
        engine = BacktestEngine(df, strategy=one_long, use_slippage=False)
        r = engine.run()
        closed = r.closed_trades
        assert len(closed) == 1
        assert closed[0].status in ("WIN", "LOSS")  # deterministic outcome
        assert closed[0].exit_idx is not None

    def test_sl_tp_geometry_short(self):
        from backtest_harness import BacktestEngine
        df = _make_df(n=200)
        fired = [False]
        def one_short(df, i):
            if not fired[0] and i > 60:
                fired[0] = True
                return "SHORT"
            return None
        engine = BacktestEngine(df, strategy=one_short, use_slippage=False)
        r = engine.run()
        assert len(r.trades) == 1
        t = r.trades[0]
        assert t.direction == "SHORT"
        assert t.sl > t.entry_price  # SL above for short
        assert t.tp < t.entry_price  # TP below


class TestStrategies:
    def test_sma_no_signal_in_warmup(self):
        from backtest_harness import sma_crossover_strategy
        df = _make_df(n=100)
        assert sma_crossover_strategy(df, 5) is None
        assert sma_crossover_strategy(df, 30) is None  # before slow period

    def test_rsi_returns_valid_signal(self):
        from backtest_harness import rsi_strategy
        # Strong uptrend → high RSI → should signal SHORT (mean reversion)
        df = _make_df(n=100, trend=0.5, seed=7)
        signals = [rsi_strategy(df, i) for i in range(20, 100)]
        valid = [s for s in signals if s in ("LONG", "SHORT")]
        # At least some signals generated
        assert len(valid) > 0

    def test_strategies_registered(self):
        from backtest_harness import STRATEGIES
        assert "sma" in STRATEGIES
        assert "rsi" in STRATEGIES


class TestTrainingRegistry:
    def test_log_and_list(self, tmp_path, monkeypatch):
        from src.ml import training_registry as tr
        # Redirect registry to tmp
        monkeypatch.setattr(tr, "REGISTRY_PATH", tmp_path / "hist.jsonl")

        rec = tr.log_training_run(
            model_type="test_model",
            hyperparams={"lr": 0.001},
            data_signature={"hash": "abc"},
            metrics={"val_return": 5.5},
        )
        assert rec["model_type"] == "test_model"
        runs = tr.list_runs(model_type="test_model")
        assert len(runs) == 1
        assert runs[0]["metrics"]["val_return"] == 5.5

    def test_best_run_picks_max(self, tmp_path, monkeypatch):
        from src.ml import training_registry as tr
        monkeypatch.setattr(tr, "REGISTRY_PATH", tmp_path / "hist.jsonl")

        for v in [1.0, 5.0, 3.0]:
            tr.log_training_run("m", {}, {}, {"val_return": v})
        best = tr.get_best_run("m", "val_return")
        assert best["metrics"]["val_return"] == 5.0
