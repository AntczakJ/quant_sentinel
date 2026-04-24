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
warnings.filterwarnings('ignore')

# Ustaw lokalne DATABASE_URL jeśli nie ustawione (żeby nie mutować Turso)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "data/sentinel.db"

import numpy as np
import pandas as pd
from src.core.logger import logger as _logger


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

def fetch_training_data(symbol="GC=F", target_bars=3000) -> pd.DataFrame:
    """
    Pobiera jak najwięcej danych historycznych.

    Strategia (priorytet):
      1. 1h data (max 2 lata, ~12k bars) — best balance of depth + resolution
      2. 15m data (max 60 dni, ~4k bars) — highest resolution, limited depth
      3. 1d data (max 10 lat) — fallback for deep history

    NOTE: GC=F (Gold Futures) is a close proxy for XAU/USD (Spot Gold),
    but has contango/backwardation. Acceptable for training features.
    """
    import yfinance as yf
    from src.core.logger import logger

    logger.info(f"Fetching training data for {symbol}...")

    all_dfs = []
    ticker = yf.Ticker(symbol)

    # Strategy 1: 1h data — 2 years, ~12,000 bars (best for ML training)
    try:
        df_1h = ticker.history(period="2y", interval="1h")
        if df_1h is not None and len(df_1h) > 100:
            df_1h = _normalize_df(df_1h)
            all_dfs.append(("1h", df_1h))
            logger.info(f"  1h: {len(df_1h)} bars (2 years)")
    except Exception as e:
        logger.warning(f"  1h failed: {e}")

    # Strategy 2: 15m data — 60 days, ~4,000 bars (high resolution)
    try:
        df_15m = ticker.history(period="60d", interval="15m")
        if df_15m is not None and len(df_15m) > 100:
            df_15m = _normalize_df(df_15m)
            all_dfs.append(("15m", df_15m))
            logger.info(f"  15m: {len(df_15m)} bars (60 days)")
    except Exception as e:
        logger.warning(f"  15m failed: {e}")

    # Strategy 3: 1d data — up to 10 years (macro regime training)
    try:
        df_1d = ticker.history(period="10y", interval="1d")
        if df_1d is not None and len(df_1d) > 100:
            df_1d = _normalize_df(df_1d)
            all_dfs.append(("1d", df_1d))
            logger.info(f"  1d: {len(df_1d)} bars (max history)")
    except Exception as e:
        logger.warning(f"  1d failed: {e}")

    if not all_dfs:
        raise ValueError(f"No data fetched for {symbol}")

    # Select best: prefer 1h (most bars at good resolution)
    priority = {"1h": 1, "15m": 2, "1d": 3}
    all_dfs.sort(key=lambda x: (priority.get(x[0], 99), -len(x[1])))
    best_tf, best_df = all_dfs[0]

    # OHLC validation — remove broken candles
    before = len(best_df)
    best_df = best_df[
        (best_df['high'] >= best_df['low']) &
        (best_df[['open', 'high', 'low', 'close']] > 0).all(axis=1)
    ].reset_index(drop=True)
    after = len(best_df)
    if before != after:
        logger.warning(f"  Removed {before - after} invalid candles")

    logger.info(f"Training data: {best_tf}, {len(best_df)} bars")
    return best_df


def fetch_usdjpy_aligned(xau_df: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
    """Fetch USDJPY historical aligned to the training XAU dataframe.

    USDJPY is the primary USD-strength proxy for gold — gold's single
    most important macro driver. We don't have DXY access so USDJPY
    carries the macro signal. Returns a dataframe with 'close' column
    indexed compatibly with xau_df so compute_features can merge.

    Returns empty DataFrame on fetch failure (compute_features handles
    None/empty gracefully by zeroing the macro features).
    """
    import yfinance as yf
    from src.core.logger import logger

    # Map xau interval → yfinance period window
    # (USDJPY has same availability windows as most FX on yfinance)
    period = "2y" if interval == "1h" else ("60d" if interval == "15m" else "10y")
    try:
        uj = yf.Ticker("JPY=X").history(period=period, interval=interval)
        if uj is None or len(uj) < 100:
            logger.warning(f"USDJPY fetch returned empty for {interval}/{period}")
            return pd.DataFrame()
        uj = _normalize_df(uj)
        logger.info(f"USDJPY: {len(uj)} bars ({interval}/{period})")
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

def train_xgboost(train_df: pd.DataFrame, precomputed_features=None) -> dict:
    """Trenuj XGBoost z walk-forward validation."""
    print("\n" + "=" * 60)
    print("🌳 TRENING XGBOOST")
    print("=" * 60)

    from src.ml.ml_models import ml

    t0 = time.time()
    acc = ml.train_xgb(train_df, precomputed_features=precomputed_features)
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

def train_lstm(train_df: pd.DataFrame, epochs: int = 50, precomputed_features=None) -> dict:
    """Trenuj LSTM z persystentnm scalerem."""
    print("\n" + "=" * 60)
    print("🧠 TRENING LSTM")
    print("=" * 60)

    from src.ml.ml_models import ml

    t0 = time.time()
    model = ml.train_lstm(train_df, precomputed_features=precomputed_features)
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
    parser.add_argument("--symbol", type=str, default="GC=F", help="Symbol do trenowania (default: GC=F / Gold)")
    args = parser.parse_args()

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
    df = fetch_training_data(args.symbol)
    train_df, val_df, holdout_df = split_data(df)

    # ---- 1a. Fetch USDJPY aligned (macro proxy for USD strength) ----
    # Gold's main driver is USD; USDJPY is our per-bar-historical proxy
    # (DXY not accessible, UUP/TLT/VIXY have no good intraday history).
    # Graceful degradation — compute_features zeros macro if df is empty.
    print("\n📈 Fetching USDJPY (macro proxy)...")
    usdjpy_df = fetch_usdjpy_aligned(df, interval="1h")
    if len(usdjpy_df) > 0:
        print(f"   ✅ {len(usdjpy_df)} USDJPY bars aligned")
    else:
        print("   ⚠️  USDJPY fetch failed — training WITHOUT macro features")

    # ---- 1b. Pre-compute features ONCE (reused by XGBoost + LSTM) ----
    print("\n⚙️  Pre-computing features...")
    from src.analysis.compute import compute_features
    t_feat = time.time()
    precomputed = compute_features(train_df, usdjpy_df=usdjpy_df if len(usdjpy_df) else None)
    print(f"   ✅ {len(precomputed)} rows, {len(precomputed.columns)} features ({time.time()-t_feat:.1f}s)")

    # ---- 2. XGBoost ----
    results['xgb'] = train_xgboost(train_df, precomputed_features=precomputed)

    # ---- 3. LSTM ----
    results['lstm'] = train_lstm(train_df, epochs=args.epochs, precomputed_features=precomputed)

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

    # ---- 3c. DPformer-lite (Decomposition + LSTM + Attention Fusion) ----
    # DISABLED 2026-04-24: Val accuracy 78-80% was flagged as likely data
    # leakage during the audit (docs/research/2026-04-24_SYNTHESIS_audit_report.md).
    # ensemble_weight_dpformer is already 0.0 so it contributes nothing live,
    # but train_all.py still burned ~12 min retraining it. Re-enable only
    # after investigating the leak and confirming holdout Sharpe > 0.
    print("\n⏭️  DPformer-lite skipped (suspected data leak, weight=0.0)")
    results['dpformer'] = {"skipped": True, "reason": "leak_investigation_pending"}

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

    # ---- 8. Calibration fit (Platt Scaling) ----
    try:
        from src.ml.model_calibration import get_calibrator
        cal = get_calibrator()
        cal.fit_all()
        status = cal.get_status()
        for model, info in status.items():
            if info.get('calibrated'):
                print(f"   Calibration fitted: {model} (A={info['a']:.3f}, B={info['b']:.3f})")
            else:
                print(f"   Calibration: {model} — insufficient data (will auto-fit after 50 trades)")
    except Exception as e:
        print(f"   Calibration skipped: {e}")

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


