"""tests/test_rl_agent.py — Tests for RL agent internals (PER, TradingEnv, DQN save/load)."""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest


# ── SumTree ────────────────────────────────────────────────────────────────

class TestSumTree:
    def test_add_maintains_total(self):
        from src.ml.rl_agent import SumTree
        t = SumTree(capacity=8)
        for p in [1.0, 2.0, 3.0, 4.0]:
            t.add(p, 'x')
        assert t.total == pytest.approx(10.0)

    def test_update_recomputes_total(self):
        from src.ml.rl_agent import SumTree
        t = SumTree(capacity=4)
        for p in [1.0, 2.0, 3.0, 4.0]:
            t.add(p, 'x')
        # Update leaf at idx 3 (first leaf) from 1.0 to 10.0
        t.update(3, 10.0)
        assert t.total == pytest.approx(19.0)

    def test_get_returns_correct_leaf(self):
        from src.ml.rl_agent import SumTree
        t = SumTree(capacity=4)
        for i, p in enumerate([1.0, 2.0, 3.0, 4.0]):
            t.add(p, f'data_{i}')
        _, priority, data = t.get(5.0)  # should land in data_2 (cumsum: 1,3,6,10)
        assert data == 'data_2'
        assert priority == 3.0

    def test_max_priority(self):
        from src.ml.rl_agent import SumTree
        t = SumTree(capacity=4)
        assert t.max_priority == 1.0  # empty → default
        t.add(2.5, 'x')
        t.add(1.5, 'y')
        assert t.max_priority == 2.5


# ── PrioritizedReplayBuffer ────────────────────────────────────────────────

def _fake_experience(seed=0):
    rng = np.random.default_rng(seed)
    state = rng.standard_normal(22)
    next_state = rng.standard_normal(22)
    return (state, int(rng.integers(0, 3)), float(rng.standard_normal()), next_state, False)


class TestPrioritizedReplayBuffer:
    def test_add_and_len(self):
        from src.ml.rl_agent import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=100)
        for i in range(50):
            buf.add(_fake_experience(i))
        assert len(buf) == 50

    def test_sample_returns_batch(self):
        from src.ml.rl_agent import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=100)
        for i in range(50):
            buf.add(_fake_experience(i))
        idxs, exps, weights = buf.sample(16)
        assert len(idxs) == 16
        assert len(exps) == 16
        assert weights.shape == (16,)
        assert weights.max() <= 1.0 + 1e-6

    def test_update_priorities_changes_sampling(self):
        from src.ml.rl_agent import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=10)
        for i in range(10):
            buf.add(_fake_experience(i))
        idxs, _, _ = buf.sample(5)
        # Zero out priorities of these indices — should reduce total
        total_before = buf.tree.total
        buf.update_priorities(idxs, [0.0] * len(idxs))
        assert buf.tree.total < total_before

    def test_beta_annealing(self):
        from src.ml.rl_agent import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=10, beta_start=0.4)
        assert buf.beta == 0.4
        buf.anneal_beta(500, 1000)
        assert buf.beta == pytest.approx(0.7)
        buf.anneal_beta(1000, 1000)
        assert buf.beta == 1.0

    def test_serialization_roundtrip(self):
        from src.ml.rl_agent import PrioritizedReplayBuffer
        buf = PrioritizedReplayBuffer(capacity=20)
        for i in range(10):
            buf.add(_fake_experience(i))
        saved = buf.to_list()
        assert len(saved) == 10
        restored = PrioritizedReplayBuffer.from_list(saved, capacity=20)
        assert len(restored) == 10


# ── TradingEnv ─────────────────────────────────────────────────────────────

def _make_df(n=200, start_price=100.0, trend=0.0):
    prices = start_price + np.cumsum(np.random.default_rng(0).standard_normal(n)) + trend * np.arange(n)
    return pd.DataFrame({
        'open': prices,
        'high': prices + 0.5,
        'low': prices - 0.5,
        'close': prices,
        'volume': np.ones(n) * 100.0,
    })


class TestTradingEnv:
    def test_reset_returns_state(self):
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000)
        state = env.reset()
        assert state.shape == (22,)
        assert env.balance == 10000
        assert env.position == 0

    def test_hold_action_no_cost(self):
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000)
        env.reset()
        env.step(0)  # HOLD
        assert env.balance == 10000
        assert env.position == 0

    def test_buy_opens_long_position(self):
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000)
        env.reset()
        env.step(1)  # BUY
        assert env.position == 1
        assert env.entry_price > 0
        assert env.sl_price < env.entry_price
        assert env.tp_price > env.entry_price

    def test_sell_opens_short_position(self):
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000)
        env.reset()
        env.step(2)  # SELL
        assert env.position == -1
        assert env.sl_price > env.entry_price
        assert env.tp_price < env.entry_price

    def test_vol_normalize_unit_delta(self):
        """vol_normalize: balance change should be pnl * initial_balance, not pnl * entry_price."""
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000, vol_normalize=True)
        env.reset()
        # Open a long, then close manually at entry * 1.01 (+1% pnl)
        env.position = 1
        env.entry_price = 60000.0  # BTC-scale
        env.sl_price = 59000.0
        env.tp_price = 61500.0
        env.balance = 10000.0
        reward = env._close_position(env.entry_price * 1.01)
        # With vol_normalize: balance += 0.01 * 10000 = 100
        assert env.balance == pytest.approx(10100.0, abs=1.0)
        assert reward > 0

    def test_legacy_sizing_price_scaled(self):
        """Legacy (vol_normalize=False): balance change scales with entry price."""
        from src.ml.rl_agent import TradingEnv
        env = TradingEnv(_make_df(), initial_balance=10000, vol_normalize=False)
        env.reset()
        env.position = 1
        env.entry_price = 60000.0
        env.sl_price = 59000.0
        env.tp_price = 61500.0
        env.balance = 10000.0
        env._close_position(env.entry_price * 1.01)
        # Legacy: balance += 0.01 * 60000 = 600 → BTC dominates
        assert env.balance == pytest.approx(10600.0, abs=1.0)


# ── DQNAgent save/load roundtrip ───────────────────────────────────────────

class TestDQNAgentRoundtrip:
    def test_save_load_preserves_state(self):
        from src.ml.rl_agent import DQNAgent
        agent = DQNAgent(state_size=22, action_size=3)
        # Fill memory with a few experiences
        for i in range(40):
            exp = _fake_experience(i)
            agent.memory.add(exp)
        agent.epsilon = 0.25
        agent.train_step = 777

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'test.keras')
            agent.save(path, data_hash='testhash')

            a2 = DQNAgent(state_size=22, action_size=3)
            a2.load(path)

            assert a2.epsilon == pytest.approx(0.25)
            assert a2.train_step == 777
            assert a2._data_hash == 'testhash'
            assert len(a2.memory) == 40

    def test_load_old_deque_format(self):
        """Backward compat: old saves stored memory as list of tuples (not PER format)."""
        from src.ml.rl_agent import DQNAgent, PrioritizedReplayBuffer
        import pickle as _pickle

        agent = DQNAgent(state_size=22, action_size=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'old.keras')
            agent.model.save(path)
            # Manually write old-format params (list of raw experiences, no priorities)
            old_memory = [_fake_experience(i) for i in range(20)]
            with open(path + '.params', 'wb') as f:
                _pickle.dump({
                    'epsilon': 0.5,
                    'train_step': 100,
                    'memory': old_memory,
                }, f)

            a2 = DQNAgent(state_size=22, action_size=3)
            a2.load(path)
            # PER buffer was created from old format
            assert isinstance(a2.memory, PrioritizedReplayBuffer)
            assert len(a2.memory) == 20
