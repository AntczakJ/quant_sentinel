#!/usr/bin/env python3
"""
train_all.py — MASTER PIPELINE trenowania wszystkich modeli ML Quant Sentinel.

🎯 CEL: Dążenie do 100% skuteczności przez systematyczne trenowanie i walidację.

WYMAGANIA (.env):
    ENABLE_ML=True
    ENABLE_RL=True
    ENABLE_BAYES=True
    DATABASE_URL=data/sentinel.db     # Lokalna baza do trenowania (nie Turso!)

UŻYCIE:
    python train_all.py                    # Pełny pipeline
    python train_all.py --skip-rl          # Bez RL (szybciej)
    python train_all.py --skip-backtest    # Bez backtestingu
    python train_all.py --epochs 100       # Więcej epok LSTM
    python train_all.py --rl-episodes 500  # Więcej epizodów RL

PIPELINE:
    1. Pobieranie danych (yfinance, wiele interwałów, łączenie chunków)
    2. Podział chronologiczny: Train (70%) / Validation (15%) / Holdout (15%)
    3. Trening XGBoost (walk-forward validation, feature importance)
    4. Trening LSTM (walk-forward, scaler persistence)
    5. Trening DQN (Double DQN, ulepszone reward shaping)
    6. Optymalizacja Bayesowska parametrów tradingowych
    7. Backtest na danych holdout
    8. Raport zbiorczy + zapis metryk do bazy

KLUCZ DO WYSOKIEJ SKUTECZNOŚCI:
    ┌─────────────────────────────────────────────────────────────────┐
    │ 1. WIĘCEJ DANYCH — im dłuższa historia, tym lepsze modele      │
    │ 2. WIĘCEJ EPIZODÓW — RL potrzebuje setek epizodów              │
    │ 3. REGULARNE RETRENOWANIE — rynek się zmienia                  │
    │ 4. SELF-LEARNING — bot uczy się z własnych trade'ów            │
    │ 5. ENSEMBLE — kombinacja modeli > pojedynczy model             │
    │ 6. BAYESIAN OPT — automatyczna optymalizacja parametrów        │
    │ 7. FILTROWANIE — odrzucaj słabe sygnały (min score, min TP)    │
    └─────────────────────────────────────────────────────────────────┘
"""

import os
import sys
import time
import argparse
import warnings
import random
import json
from pathlib import Path
warnings.filterwarnings('ignore')

# ────────────────────────────────────────────────────────────────────
# Determinism (2026-04-29 audit, P1.8). Same code + same data must
# produce same weights — without this, reproduce-bug-fix-test cycle
# is impossible. Block copied from scripts/train_v2.py:43-48.
# ────────────────────────────────────────────────────────────────────
os.environ.setdefault("PYTHONHASHSEED", "42")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")
os.environ.setdefault("TF_CUDNN_DETERMINISTIC", "1")
random.seed(42)

# Ustaw lokalne DATABASE_URL jeśli nie ustawione (żeby nie mutować Turso)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "data/sentinel.db"

import numpy as np
np.random.seed(42)

import pandas as pd
from src.core.logger import logger as _logger

# Warehouse paths — use TwelveData parquet (training-vs-inference parity).
# Pre-2026-04-29 the trainer pulled yfinance GC=F (Gold Futures) which is a
# DIFFERENT instrument from the live TwelveData XAU/USD spot ($65-75 price
# gap). See docs/strategy/2026-04-29_audit_3_reprodeploy.md P0.2.
_WAREHOUSE = Path(__file__).resolve().parent / "data" / "historical"


# =====================================================================
# 0. GPU DETECTION
# =====================================================================

def _print_gpu_info():
    """Wydrukuj informacje o dostępności GPU."""
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices('GPU')
        if gpus:
            print(f"🎮 GPU: {len(gpus)} GPU(s) — {[g.name for g in gpus]}")
            print(f"   TensorFlow (LSTM/DQN) będzie używać GPU")
            policy = tf.keras.mixed_precision.global_policy()
            if 'float16' in policy.name:
                print(f"   Mixed precision: {policy.name} (faster training)")
        else:
            print("💻 GPU nie wykryte — TensorFlow używa CPU")

        try:
            from src.ml.ml_models import _XGB_PARAMS
            if 'cuda' in str(_XGB_PARAMS.get('device', '')) or 'gpu' in str(_XGB_PARAMS.get('tree_method', '')):
                print(f"🎮 XGBoost: GPU acceleration aktywna ({_XGB_PARAMS})")
            else:
                print(f"💻 XGBoost: CPU histogram mode (tree_method=hist, n_jobs=-1)")
        except Exception:
            pass

        try:
            import torch
            if torch.cuda.is_available():
                print(f"🎮 PyTorch: CUDA ({torch.cuda.get_device_name(0)})")
            else:
                try:
                    import torch_directml
                    print(f"🎮 PyTorch: DirectML")
                except Exception:
                    print("💻 PyTorch: CPU mode")
        except Exception:
            pass
    except Exception as e:
        print(f"⚠️ GPU detection: {e}")


# =====================================================================
# 1. POBIERANIE DANYCH
# =====================================================================

def fetch_training_data(source: str = "warehouse", tf: str = "1h",
                        symbol: str = "XAU_USD") -> pd.DataFrame:
    """
    Load training data. Default: TwelveData warehouse parquet (matches
    inference data source). Legacy yfinance kept for emergency fallback.

    2026-04-29: switched from yfinance GC=F (futures) to warehouse XAU/USD
    spot. The $65-75 price gap meant every prediction was on out-of-distribution
    data. See docs/strategy/2026-04-29_audit_3_reprodeploy.md P0.2.

    Args:
        source: 'warehouse' (default — TwelveData parquet) or 'yfinance' (legacy fallback)
        tf:     '5min' | '15min' | '30min' | '1h' | '4h' | '1day'
        symbol: warehouse subdir name ('XAU_USD' = spot gold, 'XAG_USD' = silver, ...)
    """
    from src.core.logger import logger

    if source == "warehouse":
        parquet_path = _WAREHOUSE / symbol / f"{tf}.parquet"
        if not parquet_path.exists():
            raise FileNotFoundError(
                f"Warehouse miss: {parquet_path}. Run "
                "scripts/data_collection/build_data_warehouse.py first, "
                "or pass --source yfinance for legacy training (NOT recommended)."
            )
        df = pd.read_parquet(parquet_path)
        logger.info(f"Training data: warehouse {symbol}/{tf}, {len(df)} bars "
                    f"({df['datetime'].min()} → {df['datetime'].max()})")
        # OHLC validation — remove broken candles
        before = len(df)
        df = df[
            (df['high'] >= df['low']) &
            (df[['open', 'high', 'low', 'close']] > 0).all(axis=1)
        ].reset_index(drop=True)
        if len(df) != before:
            logger.warning(f"  Removed {before - len(df)} invalid candles")
        return df

    # ─── Legacy yfinance path (emergency fallback only) ───
    logger.warning(
        "yfinance training source = OUT-OF-DISTRIBUTION vs live inference "
        "(GC=F futures vs TwelveData XAU/USD spot, $65-75 gap). "
        "Use --source warehouse unless you know exactly why you're not."
    )
    import yfinance as yf
    yf_symbol = symbol if "=" in symbol else "GC=F"
    logger.info(f"Fetching training data for {yf_symbol} (yfinance legacy)...")
    ticker = yf.Ticker(yf_symbol)
    period = "2y" if tf == "1h" else ("60d" if tf in ("15m", "15min") else "10y")
    yf_interval = tf.replace("min", "m")
    df = ticker.history(period=period, interval=yf_interval)
    if df is None or len(df) < 100:
        raise ValueError(f"No yfinance data for {yf_symbol}")
    df = _normalize_df(df)
    before = len(df)
    df = df[
        (df['high'] >= df['low']) &
        (df[['open', 'high', 'low', 'close']] > 0).all(axis=1)
    ].reset_index(drop=True)
    if len(df) != before:
        logger.warning(f"  Removed {before - len(df)} invalid candles")
    logger.info(f"Training data: yfinance {yf_symbol}/{tf}, {len(df)} bars")
    return df


def fetch_usdjpy_aligned(xau_df: pd.DataFrame, source: str = "warehouse",
                         tf: str = "1h") -> pd.DataFrame:
    """Load USDJPY aligned to the training XAU dataframe.

    Default: warehouse parquet (TwelveData, matches inference). Legacy
    yfinance JPY=X kept as emergency fallback.

    Returns empty DataFrame on miss (compute_features handles None/empty
    gracefully by zeroing the macro features).
    """
    from src.core.logger import logger

    if source == "warehouse":
        parquet_path = _WAREHOUSE / "USD_JPY" / f"{tf}.parquet"
        if not parquet_path.exists():
            logger.warning(f"USDJPY warehouse miss: {parquet_path} — training without macro")
            return pd.DataFrame()
        try:
            uj = pd.read_parquet(parquet_path)
            logger.info(f"USDJPY: {len(uj)} bars (warehouse {tf})")
            return uj
        except Exception as e:
            logger.warning(f"USDJPY warehouse read failed: {e}")
            return pd.DataFrame()

    # ─── Legacy yfinance path ───
    import yfinance as yf
    period = "2y" if tf == "1h" else ("60d" if tf in ("15m", "15min") else "10y")
    yf_interval = tf.replace("min", "m")
    try:
        uj = yf.Ticker("JPY=X").history(period=period, interval=yf_interval)
        if uj is None or len(uj) < 100:
            logger.warning(f"USDJPY fetch returned empty for {yf_interval}/{period}")
            return pd.DataFrame()
        uj = _normalize_df(uj)
        logger.info(f"USDJPY: {len(uj)} bars (yfinance {yf_interval}/{period})")
        return uj
    except Exception as e:
        logger.warning(f"USDJPY fetch failed: {e}")
        return pd.DataFrame()


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizuj DataFrame z yfinance do standardowego formatu."""
    df = df.reset_index()
    col_map = {c: c.lower() for c in df.columns}
    df.rename(columns=col_map, inplace=True)
    required = ['open', 'high', 'low', 'close', 'volume']
    available = [c for c in required if c in df.columns]
    df = df[available].dropna()
    return df


def split_data(df: pd.DataFrame, train_pct=0.70, val_pct=0.15):
    """
    Podział chronologiczny: Train / Validation / Holdout.
    """
    n = len(df)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))

    train_df = df.iloc[:train_end].reset_index(drop=True)
    val_df = df.iloc[train_end:val_end].reset_index(drop=True)
    holdout_df = df.iloc[val_end:].reset_index(drop=True)

    print(f"📐 Podział danych:")
    print(f"   Train:   {len(train_df):>6d} ({train_pct:.0%})")
    print(f"   Valid:   {len(val_df):>6d} ({val_pct:.0%})")
    print(f"   Holdout: {len(holdout_df):>6d} ({1 - train_pct - val_pct:.0%})")

    return train_df, val_df, holdout_df


# =====================================================================
# 2. TRENING XGBOOST
# =====================================================================

def train_xgboost(train_df: pd.DataFrame, precomputed_features=None,
                  precomputed_target=None) -> dict:
    """Trenuj XGBoost z walk-forward validation.

    precomputed_target: optional binary 0/1 Series aligned to features
    (e.g. triple-barrier TP-hit indicator). When None, ml.train_xgb
    falls back to legacy compute_target."""
    print("\n" + "=" * 60)
    print("🌳 TRENING XGBOOST")
    print("=" * 60)

    from src.ml.ml_models import ml

    t0 = time.time()
    acc = ml.train_xgb(train_df, precomputed_features=precomputed_features,
                       precomputed_target=precomputed_target)
    elapsed = time.time() - t0

    if acc is not None:
        print(f"   ✅ Walk-forward accuracy: {acc:.1%}")
        print(f"   ⏱️  Czas: {elapsed:.1f}s")

        # Feature importance
        if ml.xgb is not None and hasattr(ml.xgb, 'feature_importances_'):
            from src.ml.ml_models import FEATURE_COLS
            importances = dict(zip(FEATURE_COLS, ml.xgb.feature_importances_))
            top5 = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"   📊 Top 5 features:")
            for feat, imp in top5:
                print(f"      {feat}: {imp:.3f}")
    else:
        print(f"   ❌ Trening nie powiódł się (za mało danych?)")

    return {"accuracy": acc or 0, "time": elapsed}


# =====================================================================
# 3. TRENING LSTM
# =====================================================================

def train_lstm(train_df: pd.DataFrame, epochs: int = 50, precomputed_features=None,
               precomputed_target=None) -> dict:
    """Trenuj LSTM z persystentnm scalerem.

    precomputed_target: optional binary 0/1 Series — same contract as
    train_xgboost. None → legacy compute_target."""
    print("\n" + "=" * 60)
    print("🧠 TRENING LSTM")
    print("=" * 60)

    from src.ml.ml_models import ml

    t0 = time.time()
    model = ml.train_lstm(train_df, precomputed_features=precomputed_features,
                          precomputed_target=precomputed_target)
    elapsed = time.time() - t0

    if model is not None:
        # Odczytaj metryki z bazy
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            val_acc = db.get_param("lstm_last_accuracy", 0)
            wf_acc = db.get_param("lstm_walkforward_accuracy", 0)
            print(f"   Validation accuracy: {val_acc:.1%}")
            print(f"   Walk-forward accuracy: {wf_acc:.1%}")
        except (ImportError, AttributeError, TypeError):
            print(f"   Model trained successfully")
        print(f"   ⏱️  Czas: {elapsed:.1f}s")
        print(f"   💾 Scaler zapisany do models/lstm_scaler.pkl")
    else:
        print(f"   ❌ Trening nie powiódł się")

    return {"model": model is not None, "time": elapsed}


# =====================================================================
# 4. TRENING DQN (Double DQN)
# =====================================================================

def train_dqn(train_df: pd.DataFrame, episodes: int = 300, data_hash: str = None) -> dict:
    """Trenuj agenta DQN z ulepszonym reward shaping.

    Ulepszenia:
    - Cosine LR annealing (lepszza konwergencja w późnych epizodach)
    - Soft target updates (Polyak averaging)
    - Early stopping: zatrzymaj jeśli brak poprawy przez patience epizodów
    """
    print("\n" + "=" * 60)
    print("🤖 TRENING DQN (Double DQN)")
    print("=" * 60)

    from src.ml.rl_agent import TradingEnv, DQNAgent

    if len(train_df) < 50:
        print("   ❌ Za mało danych")
        return {"error": "insufficient data"}

    env = TradingEnv(train_df, initial_balance=10000, transaction_cost=0.001,
                     noise_std=0.001)
    state = env.reset()
    state_size = len(state)
    agent = DQNAgent(state_size, action_size=3)

    # Resume z checkpointu jeśli istnieje
    checkpoint_path = "models/rl_agent.keras"
    resumed = False
    if os.path.exists(checkpoint_path) and os.path.exists(checkpoint_path + '.params'):
        try:
            agent.load(checkpoint_path)
            resumed = True
            print(f"   🔄 Wznowiono z checkpointu: ε={agent.epsilon:.3f}, "
                  f"train_step={agent.train_step}, memory={len(agent.memory)}")
        except Exception as e:
            print(f"   ⚠️ Checkpoint load failed ({e}) — trening od zera")
            agent = DQNAgent(state_size, action_size=3)

    print(f"   State size: {state_size}")
    print(f"   Episodes: {episodes}")
    print(f"   Memory: {agent.memory.maxlen} (loaded: {len(agent.memory)})")
    print(f"   LR schedule: cosine {agent.lr_start} → {agent.lr_min}")
    print(f"   Target update: soft (tau={agent.tau})")
    print(f"   Noise augmentation: 0.1%")

    t0 = time.time()
    scores = []
    best_reward = -float('inf')
    best_avg = -float('inf')
    patience = 80               # early-stop patience (episodes without improvement)
    no_improve_count = 0
    info = {}

    for episode in range(episodes):
        state = env.reset()
        total_reward = 0
        done = False
        step = 0

        # Update LR (cosine annealing)
        agent.update_lr(episode, episodes)

        while not done:
            action = agent.act(state)
            next_state, reward, done, info = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            step += 1
            if step % 4 == 0:
                agent.replay(batch_size=64)

        scores.append(total_reward)
        if total_reward > best_reward:
            best_reward = total_reward

        # Early stopping check (rolling avg over last 20 episodes)
        if len(scores) >= 20:
            current_avg = np.mean(scores[-20:])
            if current_avg > best_avg + 1e-4:
                best_avg = current_avg
                no_improve_count = 0
                # Save best model weights
                best_weights = agent.model.get_weights()
            else:
                no_improve_count += 1
        else:
            no_improve_count = 0

        if (episode + 1) % 50 == 0:
            avg = np.mean(scores[-20:])
            wr = info.get('win_rate', 0) * 100
            trades = info.get('total_trades', 0)
            wins = info.get('wins', 0)
            losses = info.get('losses', 0)
            be = info.get('breakevens', 0)
            lr_now = float(agent.model.optimizer.learning_rate)
            print(f"   Ep {episode+1}/{episodes}: avg_reward={avg:.4f}, "
                  f"WR={wr:.0f}% ({wins}W/{losses}L/{be}BE of {trades}), "
                  f"bal=${info.get('balance', 0):.0f}, "
                  f"e={agent.epsilon:.3f}, lr={lr_now:.5f}")

        # Early stop: no improvement for `patience` episodes
        if no_improve_count >= patience and episode >= 100:
            print(f"   ⚡ Early stop at episode {episode+1} (no improvement for {patience} eps)")
            # Restore best weights
            if 'best_weights' in dir():
                agent.model.set_weights(best_weights)
            break

    elapsed = time.time() - t0

    # Zapisz model
    os.makedirs("models", exist_ok=True)
    agent.save("models/rl_agent.keras", data_hash=data_hash)
    print(f"\n   ✅ Model zapisany (ep {len(scores)}/{episodes})")
    print(f"   📈 Najlepsza nagroda: {best_reward:.4f}")
    print(f"   ⏱️  Czas: {elapsed:.1f}s")

    # Metryki do bazy
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("rl_best_reward", best_reward)
        db.set_param("rl_episodes_trained", episodes)
    except (ImportError, AttributeError, TypeError):
        pass

    return {"best_reward": best_reward, "episodes": episodes, "time": elapsed}


# =====================================================================
# 5. OPTYMALIZACJA BAYESOWSKA
# =====================================================================

def run_bayesian_optimization() -> dict:
    """Uruchom optymalizację Bayesowską parametrów tradingowych."""
    print("\n" + "=" * 60)
    print("🔮 OPTYMALIZACJA BAYESOWSKA")
    print("=" * 60)

    try:
        from src.learning.self_learning import run_learning_cycle

        # Tymczasowo włącz Bayes
        import src.core.config
        old_bayes = src.core.config.ENABLE_BAYES
        src.core.config.ENABLE_BAYES = True

        t0 = time.time()
        run_learning_cycle()
        elapsed = time.time() - t0

        src.core.config.ENABLE_BAYES = old_bayes

        # Odczytaj zoptymalizowane parametry
        from src.core.database import NewsDB
        db = NewsDB()
        params = {}
        for p in ['risk_percent', 'min_tp_distance_mult', 'target_rr', 'min_score']:
            val = db.get_param(p, None)
            if val is not None:
                params[p] = val

        print(f"   ✅ Zoptymalizowane parametry:")
        for k, v in params.items():
            print(f"      {k}: {v:.3f}" if isinstance(v, float) else f"      {k}: {v}")
        print(f"   ⏱️  Czas: {elapsed:.1f}s")

        return {"params": params, "time": elapsed}
    except Exception as e:
        print(f"   ⚠️ Optymalizacja pominięta: {e}")
        return {"error": str(e)}


# =====================================================================
# 6. BACKTEST
# =====================================================================

def run_backtest(holdout_df: pd.DataFrame) -> dict:
    """Uruchom backtest na danych holdout."""
    from src.analysis.backtest import run_full_backtest
    return run_full_backtest(holdout_df)


# =====================================================================
# 7. RAPORT KOŃCOWY
# =====================================================================

def print_final_report(results: dict):
    """Wydrukuj podsumowanie treningu."""
    print("\n" + "🏆" * 30)
    print("🏆 PODSUMOWANIE TRENINGU QUANT SENTINEL")
    print("🏆" * 30)

    # XGBoost
    xgb = results.get('xgb', {})
    print(f"\n🌳 XGBoost:")
    print(f"   Walk-forward accuracy: {xgb.get('accuracy', 0):.1%}")

    # LSTM
    lstm = results.get('lstm', {})
    print(f"\n🧠 LSTM:")
    print(f"   Trained: {'✅' if lstm.get('model') else '❌'}")

    # DQN
    dqn = results.get('dqn', {})
    print(f"\n🤖 DQN:")
    print(f"   Best reward: {dqn.get('best_reward', 0):.4f}")
    print(f"   Episodes: {dqn.get('episodes', 0)}")

    # Bayesian
    bayes = results.get('bayes', {})
    if 'params' in bayes:
        print(f"\n🔮 Bayesian Optimization:")
        for k, v in bayes['params'].items():
            print(f"   {k}: {v}")

    # Backtest
    bt = results.get('backtest', {})
    if bt:
        print(f"\n📊 Backtest (holdout):")
        for model_name, r in bt.items():
            if isinstance(r, dict) and 'accuracy' in r:
                print(f"   {model_name:>10s}: {r['accuracy']:.1%} accuracy, {r.get('sharpe', 0):.2f} Sharpe")

    # Sugestie dalszego trenowania
    print(f"\n💡 WSKAZÓWKI DO DALSZEJ POPRAWY:")
    print(f"   1. Uruchom bota (python run.py) — self-learning uczy się z każdego trade'a")
    print(f"   2. Po zebraniu 50+ trade'ów, uruchom ponownie: python train_all.py")
    print(f"   3. Zwiększ epizody RL: python train_all.py --rl-episodes 1000")
    print(f"   4. Włącz Bayesian optimization w .env: ENABLE_BAYES=True")
    print(f"   5. Trenuj regularnie (co tydzień) — rynek się zmienia!")
    print(f"   6. Monitoruj logi: logs/sentinel.log")

    total_time = sum(v.get('time', 0) for v in results.values() if isinstance(v, dict))
    print(f"\n⏱️  Łączny czas treningu: {total_time:.0f}s ({total_time/60:.1f} min)")


# =====================================================================
# MAIN
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Quant Sentinel — Master Training Pipeline")
    parser.add_argument("--skip-rl", action="store_true", help="Pomiń trening DQN (szybciej)")
    parser.add_argument("--skip-backtest", action="store_true", help="Pomiń backtest")
    parser.add_argument("--skip-bayes", action="store_true", help="Pomiń optymalizację Bayesowską")
    parser.add_argument("--epochs", type=int, default=50, help="Liczba epok LSTM (default: 50)")
    parser.add_argument("--rl-episodes", type=int, default=300, help="Liczba epizodów RL (default: 300)")
    parser.add_argument("--symbol", type=str, default="XAU_USD",
                        help="Symbol (warehouse subdir or yfinance ticker). Default: XAU_USD")
    parser.add_argument("--source", choices=["warehouse", "yfinance"], default="warehouse",
                        help="Data source: 'warehouse' (TwelveData parquet, matches inference) "
                             "or 'yfinance' (legacy GC=F futures, OUT-OF-DISTRIBUTION). Default: warehouse")
    parser.add_argument("--tf", type=str, default="1h",
                        help="Training TF: 5min/15min/30min/1h/4h/1day. Default: 1h")
    parser.add_argument("--seed", type=int, default=42, help="Global RNG seed (for reproducibility)")
    parser.add_argument("--target", choices=["binary", "triple_barrier"], default="binary",
                        help="Training target: 'binary' (legacy compute_target — flagged "
                             "tautological by audit) or 'triple_barrier' (TP-hit binary "
                             "from data/historical/labels/triple_barrier_*.parquet, "
                             "directly aligned with how we trade). Default: binary.")
    parser.add_argument("--target-direction", choices=["long", "short"], default="long",
                        help="Direction to train against when --target triple_barrier. "
                             "Default: long. (For per-direction split, train two models "
                             "via two CLI invocations.)")
    args = parser.parse_args()

    # Apply seed to ALL libraries — including TensorFlow which needs an
    # explicit `tf.random.set_seed` whenever TF_DETERMINISTIC_OPS=1 is
    # active (otherwise random ops crash: "Random ops require a seed to
    # be set when determinism is enabled"). Always run, not just when
    # --seed override differs from 42 (that older gating left default
    # runs without TF seeding).
    os.environ["PYTHONHASHSEED"] = str(args.seed)
    random.seed(args.seed)
    np.random.seed(args.seed)
    try:
        import tensorflow as tf
        tf.keras.utils.set_random_seed(args.seed)
    except ImportError:
        pass

    print("=" * 60)
    print("🚀 QUANT SENTINEL — MASTER TRAINING PIPELINE")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"LSTM epochs: {args.epochs}")
    print(f"RL episodes: {args.rl_episodes}")
    print(f"Skip RL: {args.skip_rl}")
    print(f"Skip backtest: {args.skip_backtest}")
    print(f"Skip Bayes: {args.skip_bayes}")
    print()
    _print_gpu_info()
    print()

    results = {}

    # ---- 1. Dane ----
    df = fetch_training_data(source=args.source, tf=args.tf, symbol=args.symbol)
    train_df, val_df, holdout_df = split_data(df)

    # ---- 1a. Fetch USDJPY aligned (macro proxy for USD strength) ----
    # Gold's main driver is USD; USDJPY is our per-bar-historical proxy
    # (DXY not accessible, UUP/TLT/VIXY have no good intraday history).
    # Graceful degradation — compute_features zeros macro if df is empty.
    print("\n📈 Fetching USDJPY (macro proxy)...")
    usdjpy_df = fetch_usdjpy_aligned(df, source=args.source, tf=args.tf)
    if len(usdjpy_df) > 0:
        print(f"   ✅ {len(usdjpy_df)} USDJPY bars aligned")
    else:
        print("   ⚠️  USDJPY fetch failed — training WITHOUT macro features")

    # ---- 1b. Pre-compute features ONCE (reused by XGBoost + LSTM) ----
    print("\n⚙️  Pre-computing features...")
    from src.analysis.compute import compute_features, FEATURE_COLS
    t_feat = time.time()
    precomputed = compute_features(train_df, usdjpy_df=usdjpy_df if len(usdjpy_df) else None)
    print(f"   ✅ {len(precomputed)} rows, {len(precomputed.columns)} features ({time.time()-t_feat:.1f}s)")

    # Pin FEATURE_COLS at training time (P2.1 from master audit). Inference
    # MUST use the EXACT same list — saving alongside model artifacts so
    # ensemble_models can read it back and assert dim parity.
    os.makedirs("models", exist_ok=True)
    feature_cols_path = Path("models/feature_cols.json")
    feature_cols_path.write_text(json.dumps({
        "feature_cols": list(FEATURE_COLS),
        "n_features": len(FEATURE_COLS),
        "trained_at": pd.Timestamp.utcnow().isoformat(),
        "source": getattr(args, "source", "warehouse"),
        "tf": getattr(args, "tf", "1h"),
        "symbol": args.symbol,
    }, indent=2))
    print(f"   📌 FEATURE_COLS pinned: {len(FEATURE_COLS)} cols → {feature_cols_path}")

    # ---- 1c. Optional triple-barrier target (P1.3) ----
    precomputed_target = None
    if args.target == "triple_barrier":
        # Search for matching parquet under data/historical/labels/.
        # We accept any (tp, sl, max_holding) combo for the given (symbol, tf)
        # — caller is responsible for picking the labels they want via filename.
        labels_dir = _WAREHOUSE / "labels"
        glob_pat = f"triple_barrier_{args.symbol}_{args.tf}_*.parquet"
        candidates = sorted(labels_dir.glob(glob_pat))
        if not candidates:
            raise FileNotFoundError(
                f"No triple-barrier parquet matching {glob_pat} under {labels_dir}. "
                f"Run `python tools/build_triple_barrier_labels.py --tf {args.tf} "
                f"--symbol {args.symbol}` first."
            )
        # Prefer the most-recently-modified file (typically the one user just rebuilt).
        labels_path = max(candidates, key=lambda p: p.stat().st_mtime)
        print(f"\n📋 Loading triple-barrier labels: {labels_path.name}")
        labels_df = pd.read_parquet(labels_path)
        # Align labels to feature index by datetime. precomputed feature index
        # is positional (RangeIndex post-dropna); we need a join on datetime.
        # Both sources agree on the 'datetime' column from the warehouse parquet.
        label_col = f"label_{args.target_direction}"
        if label_col not in labels_df.columns:
            raise KeyError(f"{labels_path} missing column {label_col}")
        merged = train_df.merge(
            labels_df[["datetime", label_col]], on="datetime", how="left"
        )
        # Map -1/0/1 -> binary 0/1 (TP-hit vs not). LOSS and TIMEOUT both
        # collapse to "did NOT hit TP" — the model learns "predict P(TP hit)"
        # which directly aligns with how we trade.
        precomputed_target = (merged[label_col] == 1).astype(int)
        n_pos = int(precomputed_target.sum())
        n_total = len(precomputed_target)
        print(f"   target=triple_barrier ({args.target_direction}): "
              f"{n_pos}/{n_total} positives ({n_pos/n_total*100:.1f}% TP rate)")
    else:
        print(f"\n📋 Target: binary (legacy compute_target — flagged tautological by audit)")

    # ---- 2. XGBoost ----
    results['xgb'] = train_xgboost(train_df, precomputed_features=precomputed,
                                   precomputed_target=precomputed_target)

    # ---- 3. LSTM ----
    results['lstm'] = train_lstm(train_df, epochs=args.epochs, precomputed_features=precomputed,
                                 precomputed_target=precomputed_target)

    # ---- 3b. Attention (TFT-lite) ----
    try:
        print("\n" + "=" * 60)
        print("  ATTENTION MODEL (TFT-lite)")
        print("=" * 60)
        from src.ml.attention_model import train_attention_model
        t0 = time.time()
        attn_model, attn_acc = train_attention_model(train_df, usdjpy_df=usdjpy_df if len(usdjpy_df) else None)
        elapsed = time.time() - t0
        if attn_model:
            print(f"   Walk-forward accuracy: {attn_acc:.1%}")
            print(f"   Time: {elapsed:.1f}s")
        else:
            print("   Failed (insufficient data?)")
        results['attention'] = {"accuracy": attn_acc, "time": elapsed}
    except Exception as e:
        print(f"   Attention skipped: {e}")
        results['attention'] = {"error": str(e)}

    # ---- 3c. DPformer-lite — DROPPED 2026-04-29 ----
    # Audit confirmed the leak: np.convolve(mode='same') uses a symmetric
    # kernel that pulls 10 future bars into trend at bar t. Explains the
    # outlier val_acc 78-80%. Voter dropped from default_weights and from
    # the models track-record loop in src/ml/ensemble_models.py. Keep this
    # stub in case a downstream consumer reads the dict key.
    # See docs/strategy/2026-04-29_audit_1_data_leaks.md P1.1.
    print("\n⏭️  DPformer-lite DROPPED (future-leak — audit P1.1)")
    results['dpformer'] = {"skipped": True, "reason": "DROPPED 2026-04-29 — future leak in decompose_model.py:48"}

    # ---- 4. DQN ----
    if not args.skip_rl:
        import hashlib
        _dh = hashlib.sha256(train_df[['close']].values.tobytes()).hexdigest()[:16]
        results['dqn'] = train_dqn(train_df, episodes=args.rl_episodes, data_hash=_dh)
    else:
        print("\n⏭️  DQN pominięty (--skip-rl)")
        results['dqn'] = {"skipped": True}

    # ---- 5. Bayesian Optimization ----
    if not args.skip_bayes:
        results['bayes'] = run_bayesian_optimization()
    else:
        print("\n⏭️  Bayesian pominięty (--skip-bayes)")
        results['bayes'] = {"skipped": True}

    # ---- 6. Backtest on holdout ----
    if not args.skip_backtest:
        results['backtest'] = run_backtest(holdout_df)
    else:
        print("\n  Backtest skipped (--skip-backtest)")
        results['backtest'] = {"skipped": True}

    # ---- 7. Post-training: ONNX export ----
    print("\n" + "=" * 60)
    print("  POST-TRAINING: ONNX Export + Calibration")
    print("=" * 60)
    try:
        from src.analysis.compute import convert_keras_to_onnx, convert_xgboost_to_onnx
        import pickle

        # LSTM → ONNX
        if os.path.exists("models/lstm.keras"):
            result = convert_keras_to_onnx("models/lstm.keras", "models/lstm.onnx")
            if result:
                print(f"   LSTM exported to ONNX: models/lstm.onnx")

        # XGBoost → ONNX
        if os.path.exists("models/xgb.pkl"):
            with open("models/xgb.pkl", "rb") as f:
                xgb_model = pickle.load(f)
            n_features = xgb_model.n_features_in_ if hasattr(xgb_model, 'n_features_in_') else 31
            result = convert_xgboost_to_onnx(xgb_model, n_features, "models/xgb.onnx")
            if result:
                print(f"   XGBoost exported to ONNX: models/xgb.onnx")

        # DQN → ONNX
        if os.path.exists("models/rl_agent.keras"):
            result = convert_keras_to_onnx("models/rl_agent.keras", "models/rl_agent.onnx")
            if result:
                print(f"   DQN exported to ONNX: models/rl_agent.onnx")
    except Exception as e:
        print(f"   ONNX export skipped: {e}")

    # ---- 8. Calibration fit — DISABLED 2026-04-29 ----
    # The Platt fit_from_history function regresses TRADE WIN/LOSS labels
    # against P(LONG-wins) raw outputs from a mix of LONG and SHORT trades —
    # meaningless correlation produced negative `a` (≈-0.17), mathematically
    # inverting every signal. Re-running cal.fit_all() here would just refit
    # the same broken pattern. Kill-switch DISABLE_CALIBRATION=1 in .env
    # bypasses calibration at inference; keep it that way until per-direction
    # calibration is rebuilt (Batch D, post-retrain). See
    # docs/strategy/2026-04-29_pretraining_master.md P0.1/P1.6/P1.7.
    print(f"   Calibration fit SKIPPED — see audit P0.1 (kill-switch DISABLE_CALIBRATION=1 active)")

    # ---- 9. Model validation on val_df ----
    try:
        print(f"\n   Validation set ({len(val_df)} bars):")
        from src.analysis.backtest import backtest_xgb, backtest_lstm
        val_xgb = backtest_xgb(val_df)
        if 'accuracy' in val_xgb:
            print(f"   XGBoost val: acc={val_xgb['accuracy']:.1%} MCC={val_xgb.get('mcc', 0):.3f} Sharpe={val_xgb.get('sharpe', 0):.2f}")
        val_lstm = backtest_lstm(val_df)
        if 'accuracy' in val_lstm:
            print(f"   LSTM val:    acc={val_lstm['accuracy']:.1%} MCC={val_lstm.get('mcc', 0):.3f} Sharpe={val_lstm.get('sharpe', 0):.2f}")
    except Exception as e:
        print(f"   Validation skipped: {e}")

    # ---- 10. Raport ----
    print_final_report(results)

    print("\n✅ Pipeline zakończony pomyślnie!")
    return results


if __name__ == "__main__":
    main()


