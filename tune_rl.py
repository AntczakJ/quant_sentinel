#!/usr/bin/env python3
"""tune_rl.py - Optuna hyperparameter sweep for the DQN RL agent.

Attacks the ~20pp train/OOS overfit gap documented in
memory/rl_training_insights.md by searching over learning rate, network
shape, regularization, reward geometry, and data window. Uses a 3-way
train/val/test split so the sweep never sees the test slice: the final
winner is retrained and then scored on the held-out test period before
being written to disk.

Usage
-----
  # Full overnight run (recommended):
  python tune_rl.py --n-trials 60 --episodes 150 --study-name rl_sweep_v1

  # Resume an interrupted study:
  python tune_rl.py --resume --study-name rl_sweep_v1 --n-trials 60 --episodes 150

  # Smoke test (2 trials, 5 episodes, ~1 minute):
  python tune_rl.py --smoke

  # Inspect leaderboard:
  python tune_rl.py --report --study-name rl_sweep_v1

  # Promote the winner to production slot (also retrains on train+val):
  python tune_rl.py --apply-winner --study-name rl_sweep_v1

Output artifacts
----------------
  data/optuna_rl.db           SQLite storage for study (resume-safe)
  data/sweep_heartbeat.json   Live progress for the frontend widget
  reports/sweep_<name>.json   Leaderboard + best params + test metrics
  models/rl_sweep_winner.*    Winner artifacts (keras + params + onnx)

All writes are scoped to the working directory — no network egress, no
DB writes to data/sentinel.db.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Silence TF before import.
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '1')

import numpy as np
import pandas as pd

try:
    import optuna
    from optuna.pruners import MedianPruner
    from optuna.samplers import TPESampler
except ImportError:
    print("[fatal] optuna not installed. Run: pip install 'optuna>=3.5'", file=sys.stderr)
    raise

import tensorflow as tf
import yfinance as yf

from src.ml.rl_agent import TradingEnv, DQNAgent
from src.ml.training_registry import log_training_run
from src.core.logger import logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ("GC=F", "EURUSD=X", "CL=F")
INITIAL_BALANCE = 10_000
TRANSACTION_COST = 0.001
VAL_EVERY_DEFAULT = 15  # report + pruning checkpoint cadence
STORAGE_DEFAULT = "sqlite:///data/optuna_rl.db"
HEARTBEAT_PATH = Path("data/sweep_heartbeat.json")
CACHE_DIR = Path("data/_sweep_cache")

# Data windows available to the search. Each must yield >= 400 usable bars for
# every symbol in the basket, else the trial is skipped.
DATA_CONFIGS = {
    "2y_1h": {"period": "2y", "interval": "1h"},
    "1y_1h": {"period": "1y", "interval": "1h"},
    "5y_1d": {"period": "5y", "interval": "1d"},
    "2y_4h_synth": {"period": "2y", "interval": "1h", "resample": "4h"},
}


# ---------------------------------------------------------------------------
# Data loading (cached across trials — yfinance is slow and rate-limited)
# ---------------------------------------------------------------------------

def _cache_path(symbol: str, key: str) -> Path:
    safe = symbol.replace("=", "_").replace("/", "_")
    return CACHE_DIR / f"{safe}__{key}.pkl"


def _fetch_symbol(symbol: str, cfg_key: str) -> Optional[pd.DataFrame]:
    """Fetch a single symbol at the given data config. Pickle-cached, 24h TTL."""
    cfg = DATA_CONFIGS[cfg_key]
    path = _cache_path(symbol, cfg_key)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and (time.time() - path.stat().st_mtime) < 86_400:
        try:
            return pd.read_pickle(path)
        except Exception:
            path.unlink(missing_ok=True)

    try:
        df = yf.Ticker(symbol).history(period=cfg["period"], interval=cfg["interval"])
    except Exception as e:
        logger.warning(f"[tune_rl] fetch failed {symbol} {cfg_key}: {e}")
        return None
    if df is None or len(df) < 100:
        return None
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    cols = [c for c in ('open', 'high', 'low', 'close', 'volume') if c in df.columns]
    df = df[cols].dropna().reset_index(drop=True)

    if "resample" in cfg:
        # Resample 1h -> 4h OHLC using standard bar aggregation.
        raw = yf.Ticker(symbol).history(period=cfg["period"], interval=cfg["interval"])
        raw.columns = [c.lower() for c in raw.columns]
        agg = raw.resample(cfg["resample"]).agg({
            'open': 'first', 'high': 'max', 'low': 'min',
            'close': 'last', 'volume': 'sum'
        }).dropna().reset_index(drop=True)
        df = agg[[c for c in cols if c in agg.columns]]

    try:
        df.to_pickle(path)
    except Exception as e:
        logger.warning(f"[tune_rl] cache write failed {path}: {e}")
    return df


def load_basket(symbols: Tuple[str, ...], cfg_key: str) -> Dict[str, pd.DataFrame]:
    """Load all symbols for one data config. Returns dict of usable frames."""
    out: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _fetch_symbol(sym, cfg_key)
        if df is None or len(df) < 400:
            logger.info(f"[tune_rl] skipping {sym} at {cfg_key}: insufficient data")
            continue
        out[sym] = df
    return out


# ---------------------------------------------------------------------------
# 3-way split (train / val / test) — test is held out from the sweep entirely
# ---------------------------------------------------------------------------

@dataclass
class Splits:
    train: Dict[str, pd.DataFrame] = field(default_factory=dict)
    val: Dict[str, pd.DataFrame] = field(default_factory=dict)
    test: Dict[str, pd.DataFrame] = field(default_factory=dict)


def build_splits(basket: Dict[str, pd.DataFrame],
                 train_frac: float = 0.6,
                 val_frac: float = 0.2) -> Splits:
    s = Splits()
    for sym, df in basket.items():
        n = len(df)
        a = int(n * train_frac)
        b = int(n * (train_frac + val_frac))
        s.train[sym] = df.iloc[:a].reset_index(drop=True)
        s.val[sym] = df.iloc[a:b].reset_index(drop=True)
        s.test[sym] = df.iloc[b:].reset_index(drop=True)
    return s


# ---------------------------------------------------------------------------
# Trial training loop
# ---------------------------------------------------------------------------

@dataclass
class HParams:
    lr: float
    gamma: float
    epsilon_decay: float
    epsilon_min: float
    tau: float
    n_step: int
    batch_size: int
    net_width: int
    net_depth: int
    dropout: float
    noise_std: float
    sl_atr_mult: float
    target_rr: float
    per_alpha: float
    data_config: str

    @property
    def net_config(self) -> List[int]:
        # Pyramid: [w, w, w//2, w//2, ...] truncated to depth.
        widths = [self.net_width] * self.net_depth
        if self.net_depth >= 3:
            widths[-1] = max(16, self.net_width // 2)
        return widths


def sample_hparams(trial: optuna.Trial) -> HParams:
    return HParams(
        lr=trial.suggest_float("lr", 1e-4, 3e-3, log=True),
        gamma=trial.suggest_float("gamma", 0.90, 0.995),
        epsilon_decay=trial.suggest_float("epsilon_decay", 0.990, 0.9995),
        epsilon_min=trial.suggest_float("epsilon_min", 0.005, 0.05),
        tau=trial.suggest_float("tau", 0.001, 0.02, log=True),
        n_step=trial.suggest_categorical("n_step", [1, 2, 3, 5]),
        batch_size=trial.suggest_categorical("batch_size", [32, 64, 128]),
        net_width=trial.suggest_categorical("net_width", [32, 64, 128]),
        net_depth=trial.suggest_int("net_depth", 2, 4),
        dropout=trial.suggest_float("dropout", 0.0, 0.3),
        noise_std=trial.suggest_float("noise_std", 0.0, 0.005),
        sl_atr_mult=trial.suggest_float("sl_atr_mult", 1.0, 2.5),
        target_rr=trial.suggest_float("target_rr", 1.5, 3.5),
        per_alpha=trial.suggest_float("per_alpha", 0.4, 0.8),
        data_config=trial.suggest_categorical("data_config", list(DATA_CONFIGS.keys())),
    )


def make_envs(splits_for_cfg: Splits, hp: HParams) -> Tuple[Dict, Dict]:
    train_envs, val_envs = {}, {}
    for sym, df in splits_for_cfg.train.items():
        if len(df) < 80 or sym not in splits_for_cfg.val or len(splits_for_cfg.val[sym]) < 40:
            continue
        train_envs[sym] = TradingEnv(df, initial_balance=INITIAL_BALANCE,
                                     transaction_cost=TRANSACTION_COST,
                                     noise_std=hp.noise_std,
                                     sl_atr_mult=hp.sl_atr_mult,
                                     target_rr=hp.target_rr,
                                     vol_normalize=True)
        val_envs[sym] = TradingEnv(splits_for_cfg.val[sym],
                                   initial_balance=INITIAL_BALANCE,
                                   transaction_cost=TRANSACTION_COST,
                                   noise_std=0.0,
                                   sl_atr_mult=hp.sl_atr_mult,
                                   target_rr=hp.target_rr,
                                   vol_normalize=True)
    return train_envs, val_envs


def eval_mean_return(agent: DQNAgent, envs: Dict[str, TradingEnv]) -> float:
    old_eps = agent.epsilon
    agent.epsilon = 0.0
    returns = []
    for sym, env in envs.items():
        state = env.reset()
        done = False
        info: Dict[str, Any] = {}
        while not done:
            state, _, done, info = env.step(agent.act(state))
        balance = info.get('balance', INITIAL_BALANCE)
        returns.append((balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100.0)
    agent.epsilon = old_eps
    return float(np.mean(returns)) if returns else -999.0


def train_one_trial(trial: optuna.Trial,
                    hp: HParams,
                    splits: Splits,
                    episodes: int,
                    val_every: int,
                    heartbeat: "Heartbeat") -> float:
    """Run one trial: train a DQN with hp, return best val mean return."""
    tf.keras.backend.clear_session()

    train_envs, val_envs = make_envs(splits, hp)
    if not train_envs:
        raise optuna.TrialPruned("no usable envs at sampled data_config")
    symbols = list(train_envs.keys())
    state_size = len(train_envs[symbols[0]].reset())

    agent = DQNAgent(
        state_size=state_size,
        action_size=3,
        lr=hp.lr,
        gamma=hp.gamma,
        epsilon=1.0,
        epsilon_min=hp.epsilon_min,
        epsilon_decay=hp.epsilon_decay,
        target_update_freq=200,
        tau=hp.tau,
        memory_size=20_000,
        n_step=hp.n_step,
        net_config=hp.net_config,
        per_alpha=hp.per_alpha,
        dropout=hp.dropout,
    )

    best_val = -float("inf")
    t0 = time.time()
    for ep in range(episodes):
        sym = random.choice(symbols)
        env = train_envs[sym]
        state = env.reset()
        done = False
        step = 0
        replay_count = 0
        while not done:
            action = agent.act(state)
            next_state, reward, done, _ = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            step += 1
            if step % 8 == 0 and replay_count < 40 and len(agent.memory) >= 256:
                agent.replay(batch_size=hp.batch_size)
                replay_count += 1
        agent.update_lr(ep, episodes)

        if (ep + 1) % val_every == 0:
            val_ret = float(np.mean([
                eval_mean_return(agent, {s: v}) for s, v in val_envs.items()
            ]))
            if val_ret > best_val:
                best_val = val_ret
            trial.report(val_ret, ep + 1)
            heartbeat.update_trial(trial_number=trial.number, episode=ep + 1,
                                   total_episodes=episodes, val_return=val_ret,
                                   best_val=best_val, elapsed=time.time() - t0)
            if trial.should_prune():
                raise optuna.TrialPruned(
                    f"pruned at ep {ep+1} val={val_ret:+.2f}% (< median)")

    # Ensure we always have at least one val score even if val_every > episodes.
    if best_val == -float("inf"):
        best_val = float(np.mean([
            eval_mean_return(agent, {s: v}) for s, v in val_envs.items()
        ]))
    return best_val


# ---------------------------------------------------------------------------
# Heartbeat — so the UI / monitoring can see sweep progress live
# ---------------------------------------------------------------------------

class Heartbeat:
    def __init__(self, study_name: str, n_trials: int, episodes: int):
        self.study_name = study_name
        self.n_trials = n_trials
        self.episodes = episodes
        self.started_at = time.time()
        self.state: Dict[str, Any] = {
            "status": "running",
            "study_name": study_name,
            "n_trials_target": n_trials,
            "episodes_per_trial": episodes,
            "started_at": self.started_at,
            "trial_number": 0,
            "current_episode": 0,
            "current_val_return": None,
            "best_val_so_far": None,
            "completed_trials": 0,
            "pruned_trials": 0,
            "updated_at": self.started_at,
        }

    def _flush(self) -> None:
        try:
            HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.state["updated_at"] = time.time()
            HEARTBEAT_PATH.write_text(json.dumps(self.state), encoding="utf-8")
        except Exception:
            pass  # heartbeat must never break the sweep

    def update_trial(self, trial_number: int, episode: int, total_episodes: int,
                     val_return: float, best_val: float, elapsed: float) -> None:
        self.state.update({
            "trial_number": trial_number,
            "current_episode": episode,
            "total_episodes": total_episodes,
            "current_val_return": round(val_return, 3),
            "current_trial_best": round(best_val, 3),
            "current_trial_elapsed_sec": round(elapsed, 1),
        })
        self._flush()

    def finish_trial(self, trial: optuna.Trial, study: optuna.Study) -> None:
        try:
            best = study.best_value
        except ValueError:
            best = None
        completed = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE)
        pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
        self.state.update({
            "completed_trials": completed,
            "pruned_trials": pruned,
            "best_val_so_far": round(best, 3) if best is not None else None,
            "last_trial_state": trial.state.name,
        })
        self._flush()

    def finish(self, status: str = "completed") -> None:
        self.state["status"] = status
        self._flush()


# ---------------------------------------------------------------------------
# Objective — the callable Optuna drives
# ---------------------------------------------------------------------------

class SweepObjective:
    """Callable objective. Caches data per data_config so we don't refetch."""

    def __init__(self, symbols: Tuple[str, ...], episodes: int,
                 val_every: int, heartbeat: Heartbeat):
        self.symbols = symbols
        self.episodes = episodes
        self.val_every = val_every
        self.heartbeat = heartbeat
        self._split_cache: Dict[str, Splits] = {}

    def _get_splits(self, cfg_key: str) -> Splits:
        if cfg_key not in self._split_cache:
            basket = load_basket(self.symbols, cfg_key)
            if not basket:
                raise RuntimeError(f"no data for {cfg_key}")
            self._split_cache[cfg_key] = build_splits(basket)
        return self._split_cache[cfg_key]

    def __call__(self, trial: optuna.Trial) -> float:
        hp = sample_hparams(trial)
        try:
            splits = self._get_splits(hp.data_config)
        except RuntimeError as e:
            raise optuna.TrialPruned(str(e))
        try:
            return train_one_trial(trial, hp, splits,
                                   episodes=self.episodes,
                                   val_every=self.val_every,
                                   heartbeat=self.heartbeat)
        finally:
            gc.collect()


# ---------------------------------------------------------------------------
# Winner retraining + promotion
# ---------------------------------------------------------------------------

def retrain_and_save_winner(study: optuna.Study, symbols: Tuple[str, ...],
                            episodes: int, output_dir: Path) -> Dict[str, Any]:
    """Retrain best trial on train+val (merged), evaluate on held-out test."""
    best = study.best_trial
    hp = HParams(**{k: v for k, v in best.params.items() if k in HParams.__dataclass_fields__})
    print(f"[winner] retraining best trial #{best.number} "
          f"(val={best.value:+.2f}%) on full train+val ...")

    basket = load_basket(symbols, hp.data_config)
    if not basket:
        raise RuntimeError(f"cannot reload basket for data_config={hp.data_config}")
    splits = build_splits(basket)

    # Merge train + val into a single train set for the winner. Test stays held out.
    merged: Dict[str, pd.DataFrame] = {}
    for sym in splits.train:
        if sym in splits.val:
            merged[sym] = pd.concat([splits.train[sym], splits.val[sym]],
                                    ignore_index=True)
        else:
            merged[sym] = splits.train[sym]

    train_envs, test_envs = {}, {}
    for sym, df in merged.items():
        if len(df) < 80:
            continue
        train_envs[sym] = TradingEnv(df, initial_balance=INITIAL_BALANCE,
                                     transaction_cost=TRANSACTION_COST,
                                     noise_std=hp.noise_std,
                                     sl_atr_mult=hp.sl_atr_mult,
                                     target_rr=hp.target_rr,
                                     vol_normalize=True)
        if sym in splits.test and len(splits.test[sym]) >= 40:
            test_envs[sym] = TradingEnv(splits.test[sym],
                                        initial_balance=INITIAL_BALANCE,
                                        transaction_cost=TRANSACTION_COST,
                                        noise_std=0.0,
                                        sl_atr_mult=hp.sl_atr_mult,
                                        target_rr=hp.target_rr,
                                        vol_normalize=True)

    state_size = len(train_envs[next(iter(train_envs))].reset())
    tf.keras.backend.clear_session()
    agent = DQNAgent(state_size=state_size, action_size=3,
                     lr=hp.lr, gamma=hp.gamma, epsilon=1.0,
                     epsilon_min=hp.epsilon_min, epsilon_decay=hp.epsilon_decay,
                     target_update_freq=200, tau=hp.tau, memory_size=20_000,
                     n_step=hp.n_step, net_config=hp.net_config,
                     per_alpha=hp.per_alpha, dropout=hp.dropout)

    symbols_list = list(train_envs.keys())
    for ep in range(episodes):
        sym = random.choice(symbols_list)
        env = train_envs[sym]
        state = env.reset()
        done = False
        step = 0
        replay_count = 0
        while not done:
            action = agent.act(state)
            next_state, reward, done, _ = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            step += 1
            if step % 8 == 0 and replay_count < 40 and len(agent.memory) >= 256:
                agent.replay(batch_size=hp.batch_size)
                replay_count += 1
        agent.update_lr(ep, episodes)
        if (ep + 1) % 50 == 0:
            print(f"  [winner] ep {ep+1}/{episodes} epsilon={agent.epsilon:.3f}")

    test_return = eval_mean_return(agent, test_envs) if test_envs else float("nan")
    per_symbol = {}
    for sym, env in test_envs.items():
        r = eval_mean_return(agent, {sym: env})
        per_symbol[sym] = round(r, 2)

    output_dir.mkdir(parents=True, exist_ok=True)
    keras_path = output_dir / "rl_sweep_winner.keras"
    agent.save(str(keras_path), data_hash=f"sweep_{study.study_name}")
    print(f"[winner] saved -> {keras_path}  test_return={test_return:+.2f}%")

    # ONNX regen for parity with train_rl.py.
    try:
        from src.analysis.compute import convert_keras_to_onnx
        onnx_path = convert_keras_to_onnx(str(keras_path),
                                          str(output_dir / "rl_sweep_winner.onnx"))
        if onnx_path:
            print(f"[winner] ONNX -> {onnx_path}")
    except Exception as e:
        print(f"[winner] ONNX regen failed: {e}")

    # Registry entry.
    try:
        log_training_run(
            model_type="rl_agent_sweep_winner",
            hyperparams={**asdict(hp), "episodes": episodes,
                         "study_name": study.study_name,
                         "trial_number": best.number},
            data_signature={"symbols": list(test_envs.keys()),
                            "data_config": hp.data_config},
            metrics={"val_return": round(best.value, 2),
                     "test_return": round(test_return, 2),
                     "per_symbol_test": per_symbol},
            artifact_path=str(keras_path),
            notes=f"Optuna sweep winner ({study.study_name})",
        )
    except Exception as e:
        print(f"[winner] registry log failed: {e}")

    return {
        "trial_number": best.number,
        "val_return": round(best.value, 2),
        "test_return": round(test_return, 2),
        "per_symbol_test": per_symbol,
        "hparams": asdict(hp),
        "artifact": str(keras_path),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(study: optuna.Study, extra: Dict[str, Any], path: Path) -> None:
    trials = []
    for t in study.trials:
        if t.state not in (optuna.trial.TrialState.COMPLETE,
                           optuna.trial.TrialState.PRUNED):
            continue
        trials.append({
            "number": t.number,
            "state": t.state.name,
            "value": t.value if t.state == optuna.trial.TrialState.COMPLETE else None,
            "params": t.params,
            "duration_sec": (t.datetime_complete - t.datetime_start).total_seconds()
                if t.datetime_complete and t.datetime_start else None,
        })
    report = {
        "study_name": study.study_name,
        "direction": study.direction.name,
        "n_trials_done": len(study.trials),
        "best_value": study.best_value if study.trials else None,
        "best_params": study.best_params if study.trials else None,
        "trials": trials,
        **extra,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"[report] -> {path}")


def print_leaderboard(study: optuna.Study, top: int = 10) -> None:
    completed = [t for t in study.trials
                 if t.state == optuna.trial.TrialState.COMPLETE]
    completed.sort(key=lambda t: t.value or -1e9, reverse=True)
    print("\n=== Leaderboard (top completed trials) ===")
    for i, t in enumerate(completed[:top]):
        print(f"  #{t.number:>3}  val={t.value:+7.2f}%  "
              f"lr={t.params['lr']:.4f}  gamma={t.params['gamma']:.3f}  "
              f"net={t.params['net_width']}x{t.params['net_depth']}  "
              f"n_step={t.params['n_step']}  data={t.params['data_config']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_study(study_name: str, storage: str, resume: bool) -> optuna.Study:
    Path("data").mkdir(parents=True, exist_ok=True)
    sampler = TPESampler(seed=42, multivariate=True, group=True, n_startup_trials=8)
    pruner = MedianPruner(n_startup_trials=5, n_warmup_steps=30, interval_steps=15)
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        sampler=sampler,
        pruner=pruner,
        load_if_exists=resume,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Optuna RL hyperparameter sweep")
    p.add_argument("--n-trials", type=int, default=60)
    p.add_argument("--episodes", type=int, default=150,
                   help="training episodes per trial")
    p.add_argument("--val-every", type=int, default=VAL_EVERY_DEFAULT)
    p.add_argument("--study-name", default="rl_sweep_v1")
    p.add_argument("--storage", default=STORAGE_DEFAULT)
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--resume", action="store_true",
                   help="load_if_exists — continue previous study")
    p.add_argument("--smoke", action="store_true",
                   help="tiny sanity run (2 trials x 5 episodes)")
    p.add_argument("--report", action="store_true",
                   help="print leaderboard and exit (no training)")
    p.add_argument("--apply-winner", action="store_true",
                   help="retrain best trial on train+val, save to models/")
    p.add_argument("--winner-episodes", type=int, default=300,
                   help="episodes for the winner retrain (apply-winner only)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if args.smoke:
        args.n_trials = 2
        args.episodes = 5
        args.val_every = 5
        args.study_name = f"smoke_{int(time.time())}"

    random.seed(args.seed)
    np.random.seed(args.seed)
    tf.random.set_seed(args.seed)

    symbols = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    study = build_study(args.study_name, args.storage,
                        resume=args.resume or args.report or args.apply_winner)

    if args.report:
        print_leaderboard(study, top=15)
        return 0

    if args.apply_winner:
        try:
            study.best_trial
        except ValueError:
            print("[fatal] study has no completed trials yet", file=sys.stderr)
            return 2
        result = retrain_and_save_winner(study, symbols,
                                         episodes=args.winner_episodes,
                                         output_dir=Path("models"))
        out_path = Path("reports") / f"sweep_{args.study_name}.json"
        write_report(study, {"winner": result}, out_path)
        return 0

    heartbeat = Heartbeat(args.study_name, args.n_trials, args.episodes)
    heartbeat._flush()
    objective = SweepObjective(symbols=symbols,
                               episodes=args.episodes,
                               val_every=args.val_every,
                               heartbeat=heartbeat)

    def _post(study: optuna.Study, trial: optuna.FrozenTrial) -> None:
        heartbeat.finish_trial(trial, study)
        try:
            best = study.best_value
            print(f"[trial {trial.number}] state={trial.state.name} "
                  f"value={trial.value}  best_so_far={best:+.2f}%")
        except ValueError:
            pass

    t_start = time.time()
    try:
        study.optimize(objective, n_trials=args.n_trials, callbacks=[_post],
                       gc_after_trial=True, catch=(RuntimeError,))
    except KeyboardInterrupt:
        print("\n[interrupt] stopping sweep; study state is persisted")
        heartbeat.finish(status="interrupted")
    else:
        heartbeat.finish(status="completed")

    elapsed_min = (time.time() - t_start) / 60.0
    print(f"\n[sweep] finished in {elapsed_min:.1f} min")
    print_leaderboard(study, top=10)

    out_path = Path("reports") / f"sweep_{args.study_name}.json"
    write_report(study, {"elapsed_min": round(elapsed_min, 1)}, out_path)

    if not args.smoke and len([t for t in study.trials
                               if t.state == optuna.trial.TrialState.COMPLETE]) >= 3:
        print("\n[winner] promoting best trial -> models/rl_sweep_winner.*")
        try:
            result = retrain_and_save_winner(study, symbols,
                                             episodes=args.winner_episodes,
                                             output_dir=Path("models"))
            write_report(study, {"elapsed_min": round(elapsed_min, 1),
                                 "winner": result}, out_path)
        except Exception as e:
            print(f"[winner] retrain failed: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
