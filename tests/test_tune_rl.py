"""tests/test_tune_rl.py — Smoke tests for the Optuna sweep harness.

These tests monkey-patch data loading so we never hit yfinance during CI,
and shrink episodes/trials to the minimum needed to exercise every code
path (sampling, training, pruning checkpoint, winner retrain).
"""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    # Steer all artifacts into tmp so tests leave no droppings.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "models").mkdir()
    (tmp_path / "reports").mkdir()
    yield


def _fake_ohlc(n: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, 0.01, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1 + rng.uniform(0.0, 0.005, n))
    low = close * (1 - rng.uniform(0.0, 0.005, n))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(1000, 5000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def _patch_data(monkeypatch) -> None:
    """Replace yfinance-backed fetch with deterministic synthetic data."""
    import tune_rl

    def fake_basket(symbols, cfg_key):
        return {sym: _fake_ohlc(n=500, seed=hash((sym, cfg_key)) & 0xFFFF)
                for sym in symbols}

    monkeypatch.setattr(tune_rl, "load_basket", fake_basket)


def test_hparams_net_config_shape():
    from tune_rl import HParams
    hp = HParams(lr=1e-3, gamma=0.95, epsilon_decay=0.995, epsilon_min=0.01,
                 tau=0.005, n_step=3, batch_size=32, net_width=64, net_depth=3,
                 dropout=0.1, noise_std=0.001, sl_atr_mult=1.5, target_rr=2.5,
                 per_alpha=0.6, data_config="2y_1h")
    layers = hp.net_config
    assert len(layers) == 3
    assert layers[0] == 64
    assert layers[-1] == 32  # last layer halved


def test_splits_are_disjoint():
    from tune_rl import build_splits
    basket = {"A": _fake_ohlc(300, 1), "B": _fake_ohlc(400, 2)}
    s = build_splits(basket, train_frac=0.6, val_frac=0.2)
    for sym in basket:
        # No overlap, lengths sum to original.
        total = len(s.train[sym]) + len(s.val[sym]) + len(s.test[sym])
        assert total == len(basket[sym])
        # Test slice is the tail — must not appear in train.
        train_tail = s.train[sym].iloc[-1]["close"]
        test_head = s.test[sym].iloc[0]["close"]
        # Not the same bar (would indicate split bug).
        assert train_tail != test_head or len(s.train[sym]) == 0


def test_smoke_sweep_runs_end_to_end(monkeypatch):
    """Full sweep: 2 trials x 3 episodes using synthetic data. Must complete."""
    _patch_data(monkeypatch)
    import optuna
    import tune_rl

    heartbeat = tune_rl.Heartbeat("smoke", n_trials=2, episodes=3)
    obj = tune_rl.SweepObjective(symbols=("A", "B"),
                                 episodes=3, val_every=3,
                                 heartbeat=heartbeat)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=0),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=0, n_warmup_steps=0),
    )
    study.optimize(obj, n_trials=2, catch=(RuntimeError,))
    # At least one trial finished (not pruned outright).
    states = [t.state for t in study.trials]
    assert any(s == optuna.trial.TrialState.COMPLETE for s in states), \
        f"no completed trials: {states}"


def test_heartbeat_file_written(monkeypatch):
    _patch_data(monkeypatch)
    import optuna
    import tune_rl

    hb = tune_rl.Heartbeat("hb_test", n_trials=1, episodes=3)
    obj = tune_rl.SweepObjective(symbols=("A",), episodes=3, val_every=3,
                                 heartbeat=hb)
    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=0))
    study.optimize(obj, n_trials=1, callbacks=[lambda s, t: hb.finish_trial(t, s)],
                   catch=(RuntimeError,))
    hb.finish("completed")
    hb_path = Path("data/sweep_heartbeat.json")
    assert hb_path.exists()
    import json
    payload = json.loads(hb_path.read_text())
    assert payload["status"] == "completed"
    assert payload["study_name"] == "hb_test"
