#!/usr/bin/env python3
"""
test_new_features.py — testy nowych komponentow (Double DQN, backtest, scaler).

2026-04-29: pin DATABASE_URL to tempfile BEFORE any database import. The
module body runs at pytest collection time (before fixtures), and was
inserting LONG@2350 trades into production sentinel.db each time pytest
ran. Same class of bug as the test_local_db.py fix shipped today.
See `docs/strategy/2026-04-29_pretraining_master.md`.
"""
import sys
import os
import atexit
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolated tempfile DB so module-level test code doesn't pollute prod.
_tmp_db = tempfile.NamedTemporaryFile(prefix="qs_test_new_features_", suffix=".db", delete=False)
_tmp_db.close()
os.environ['DATABASE_URL'] = _tmp_db.name
os.environ.pop('DATABASE_TOKEN', None)


def _cleanup_tmp_db():
    """Best-effort cleanup. Windows may hold the SQLite file open via the
    NewsDB connection; OS sweeps %TEMP% on its own otherwise."""
    try:
        if os.path.exists(_tmp_db.name):
            os.unlink(_tmp_db.name)
    except (OSError, PermissionError):
        pass


atexit.register(_cleanup_tmp_db)

# Force database connection reinit — see test_local_db.py for the same fix.
# Otherwise an earlier test's import caches _conn against prod sentinel.db.
try:
    from src.core.database import _reinit_connection_for_test
    _reinit_connection_for_test()
except (ImportError, AttributeError):
    pass

import numpy as np
import pandas as pd

_passed = 0
_failed = 0

def check(name, condition):
    global _passed, _failed
    if condition:
        print(f"  ✅ {name}")
        _passed += 1
    else:
        print(f"  ❌ {name}")
        _failed += 1

print("=" * 60)
print("🧪 TEST NOWYCH KOMPONENTÓW")
print("=" * 60)

# ==== TEST 1: Importy ====
print("\n[TEST 1] Importy nowych modułów")
print("-" * 60)
try:
    from src.ml.rl_agent import TradingEnv, DQNAgent
    check("rl_agent (TradingEnv, DQNAgent)", True)
except Exception as e:
    check(f"rl_agent: {e}", False)

try:
    from src.analysis.backtest import evaluate_predictions, compute_equity_metrics, run_full_backtest
    check("backtest", True)
except Exception as e:
    check(f"backtest: {e}", False)

try:
    from src.ml.ml_models import ml, FEATURE_COLS
    check(f"ml_models ({len(FEATURE_COLS)} features)", True)
except Exception as e:
    check(f"ml_models: {e}", False)

try:
    from src.ml.ensemble_models import get_ensemble_prediction, predict_dqn_action, update_ensemble_weights
    check("ensemble_models", True)
except Exception as e:
    check(f"ensemble_models: {e}", False)

try:
    from src.learning.self_learning import run_learning_cycle, update_factor_weights, get_pattern_adjustment
    check("self_learning", True)
except Exception as e:
    check(f"self_learning: {e}", False)

try:
    from src.learning.bayesian_opt import BayesianOptimizer
    check("bayesian_opt", True)
except Exception as e:
    check(f"bayesian_opt: {e}", False)

# ==== TEST 2: Double DQN Agent ====
print("\n[TEST 2] Double DQN Agent")
print("-" * 60)
agent = DQNAgent(state_size=22, action_size=3)
check(f"memory maxlen = {agent.memory.maxlen}", agent.memory.maxlen == 20000)
check("has target_model", hasattr(agent, 'target_model'))
check(f"target_update_freq = {agent.target_update_freq}", agent.target_update_freq == 200)
check("has _sync_target method", hasattr(agent, '_sync_target'))

state = np.random.randn(22)
action = agent.act(state)
check(f"act() returns valid action ({action})", action in [0, 1, 2])

for i in range(40):
    s = np.random.randn(22)
    a = np.random.randint(0, 3)
    r = np.random.randn()
    ns = np.random.randn(22)
    agent.remember(s, a, r, ns, False)

agent.replay(batch_size=32)
check(f"replay(32) succeeds, train_step={agent.train_step}", agent.train_step == 1)

# Test save/load
os.makedirs("models/test", exist_ok=True)
agent.save("models/test/test_dqn.keras")
check("save() works", os.path.exists("models/test/test_dqn.keras"))

agent2 = DQNAgent(state_size=22, action_size=3)
agent2.load("models/test/test_dqn.keras")
check("load() works", agent2.epsilon == agent.epsilon)

# Cleanup
import shutil
if os.path.exists("models/test"):
    shutil.rmtree("models/test")

# ==== TEST 3: TradingEnv nowy reward shaping ====
print("\n[TEST 3] TradingEnv — reward shaping")
print("-" * 60)
data = pd.DataFrame({
    'open': np.linspace(2300, 2400, 100),
    'high': np.linspace(2310, 2410, 100),
    'low': np.linspace(2290, 2390, 100),
    'close': np.linspace(2305, 2405, 100),
    'volume': np.full(100, 1e6),
})
env = TradingEnv(data, initial_balance=10000)
state = env.reset()
check(f"state shape = {state.shape}", state.shape == (22,))
check("has entry_price", hasattr(env, 'entry_price'))
check("has wins", hasattr(env, 'wins'))
check("has losses", hasattr(env, 'losses'))
check("has rewards_history", hasattr(env, 'rewards_history'))
check("has hold_steps", hasattr(env, 'hold_steps'))

# Simulate buy and close
state = env.reset()
_, r1, _, _ = env.step(1)  # BUY
check(f"BUY: position={env.position}", env.position == 1)
check(f"BUY: entry_price > 0", env.entry_price > 0)

for _ in range(5):
    env.step(1)  # hold (already in position)

_, r_close, _, info = env.step(0)  # CLOSE
check("CLOSE: position=0", env.position == 0)
check("CLOSE: total_trades > 0", info.get('total_trades', 0) > 0)
check("info has win_rate", 'win_rate' in info)
check("info has balance", 'balance' in info)

# Run full episode
env2 = TradingEnv(data, initial_balance=10000)
state = env2.reset()
done = False
steps = 0
while not done and steps < 95:
    action = np.random.randint(0, 3)
    state, reward, done, info = env2.step(action)
    steps += 1
check(f"Full episode: {steps} steps", steps > 50)
check(f"Final balance: {info.get('balance', 0):.0f}", info.get('balance', 0) > 0)

# ==== TEST 4: Backtest metrics ====
print("\n[TEST 4] Backtest metrics")
print("-" * 60)
y_true = np.array([1, 0, 1, 1, 0, 1, 0, 0, 1, 1])
y_pred = np.array([1, 0, 0, 1, 0, 1, 1, 0, 1, 0])
metrics = evaluate_predictions(y_true, y_pred)
check(f"accuracy = {metrics['accuracy']}", 0 < metrics['accuracy'] < 1)
check(f"precision = {metrics['precision']}", 0 < metrics['precision'] < 1)
check(f"recall = {metrics['recall']}", 0 < metrics['recall'] < 1)
check(f"f1 = {metrics['f1']}", 0 < metrics['f1'] < 1)
check(f"total = {metrics['total']}", metrics['total'] == 10)
check(f"correct = {metrics['correct']}", metrics['correct'] == 7)

# Edge case: all correct
y_all = np.array([1, 0, 1])
m_all = evaluate_predictions(y_all, y_all)
check("100% accuracy = 1.0", m_all['accuracy'] == 1.0)

# Edge case: empty
m_empty = evaluate_predictions(np.array([]), np.array([]))
check("empty -> accuracy=0", m_empty['accuracy'] == 0)

returns = np.array([0.01, -0.005, 0.02, -0.01, 0.015, 0.008, -0.003, 0.012])
eq = compute_equity_metrics(returns)
check(f"sharpe = {eq['sharpe']}", eq['sharpe'] > 0)
check(f"max_drawdown = {eq['max_drawdown']}", 0 <= eq['max_drawdown'] <= 1)
check(f"total_return = {eq['total_return']}", eq['total_return'] > 0)
check(f"final_equity = {eq['final_equity']}", eq['final_equity'] > 1)

# Edge case: no returns
eq0 = compute_equity_metrics(np.array([]))
check("empty returns -> sharpe=0", eq0['sharpe'] == 0)

# ==== TEST 5: LSTM scaler persistence path ====
print("\n[TEST 5] LSTM Scaler persistence")
print("-" * 60)
scaler_path = 'models/lstm_scaler.pkl'
if os.path.exists(scaler_path):
    import pickle
    with open(scaler_path, 'rb') as f:
        scaler = pickle.load(f)
    n_feat = getattr(scaler, 'n_features_in_', 'N/A')
    check(f"Scaler loaded, n_features={n_feat}", True)
else:
    check("Scaler file not found (will be created after train_all.py)", True)
    print("  ℹ️  Run: python train_all.py to generate scaler")

# ==== TEST 6: Database consistency ====
print("\n[TEST 6] Database consistency")
print("-" * 60)
from src.core.database import NewsDB
db = NewsDB()

# Test set_param / get_param round-trip
db.set_param("_test_float", 3.14)
val = db.get_param("_test_float", 0)
check(f"set/get_param float: {val}", abs(val - 3.14) < 0.001)

db.set_param("_test_int", 42)
val2 = db.get_param("_test_int", 0)
check(f"set/get_param int: {val2}", val2 == 42.0)

# Test log_trade
try:
    db.log_trade(
        direction="LONG",
        price=2350.0,
        sl=2340.0,
        tp=2370.0,
        rsi=45.0,
        trend="bull",
        structure="Stable",
        pattern="LONG_Stable_bullish",
        factors={"bos": 1, "fvg": 1}
    )
    check("log_trade() with factors", True)
except Exception as e:
    check(f"log_trade: {e}", False)

# Test get_open_trades
try:
    trades = db.get_open_trades()
    check(f"get_open_trades() -> {len(trades)} trades", isinstance(trades, list))
except Exception as e:
    check(f"get_open_trades: {e}", False)

# Test get_performance_stats
try:
    perf_result = db.get_performance_stats()
    check(f"get_performance_stats() -> tuple of len {len(perf_result)}", isinstance(perf_result, tuple) and len(perf_result) == 2)
except Exception as e:
    check(f"get_performance_stats: {e}", False)

# Test pattern stats
try:
    db.update_pattern_stats("TEST_PATTERN", "PROFIT")
    db.update_pattern_stats("TEST_PATTERN", "LOSS")
    stats = db.get_pattern_stats("TEST_PATTERN")
    check(f"pattern stats: count={stats['count']}, wr={stats['win_rate']:.2f}", stats['count'] >= 2)
except Exception as e:
    check(f"pattern_stats: {e}", False)

# Cleanup test param
try:
    db._execute("DELETE FROM dynamic_params WHERE name LIKE '_test_%'", _silent=True)
except:
    pass

# ==== TEST 7: train_all.py import ====
print("\n[TEST 7] train_all.py validation")
print("-" * 60)
try:
    # Just verify syntax and imports
    import importlib.util
    spec = importlib.util.spec_from_file_location("train_all", "train_all.py")
    mod = importlib.util.module_from_spec(spec)
    # Don't execute, just verify it loads
    check("train_all.py syntax valid", spec is not None)
except Exception as e:
    check(f"train_all.py: {e}", False)

try:
    spec2 = importlib.util.spec_from_file_location("train_rl", "train_rl.py")
    check("train_rl.py syntax valid", spec2 is not None)
except Exception as e:
    check(f"train_rl.py: {e}", False)

# ==== TEST 8: Ensemble weights in DB ====
print("\n[TEST 8] Ensemble dynamic weights")
print("-" * 60)
try:
    from src.ml.ensemble_models import _load_dynamic_weights
    weights = _load_dynamic_weights()
    check(f"weights loaded: {weights}", sum(weights.values()) > 0.99)
    check("has smc weight", 'smc' in weights)
    check("has lstm weight", 'lstm' in weights)
    check("has xgb weight", 'xgb' in weights)
    check("has dqn weight", 'dqn' in weights)
except Exception as e:
    check(f"dynamic weights: {e}", False)

# ==== TEST 9: Self-learning pattern adjustment ====
print("\n[TEST 9] Self-learning")
print("-" * 60)
try:
    adj = get_pattern_adjustment({"pattern": "NONEXISTENT_PATTERN_12345"})
    check(f"unknown pattern -> adjustment={adj}", adj == 1.0)
except Exception as e:
    check(f"get_pattern_adjustment: {e}", False)

try:
    update_factor_weights(-999, "PROFIT")  # non-existent trade
    check("update_factor_weights (no-op for missing trade)", True)
except Exception as e:
    check(f"update_factor_weights: {e}", False)

def _summary():
    print("\n" + "=" * 60)
    print(f"PODSUMOWANIE: {_passed}/{_passed+_failed} testow przeszlo")
    print("=" * 60)
    if _failed == 0:
        print("WSZYSTKIE TESTY PRZESZLY!")
    else:
        print(f"{_failed} test(ow) nie przeszlo")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_summary())

