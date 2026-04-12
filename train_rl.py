#!/usr/bin/env python3
"""
train_rl.py — trenowanie agenta RL (Double DQN) na historycznych danych.

Ulepszenia:
- Pobiera 6 miesięcy danych (zamiast 1 miesiąca)
- Jeśli brak 15m, fallback na 1h lub 1d
- Lepszy logging z metrykami per-epizod (win_rate, balance)
- Zapisuje metryki do bazy danych
"""

import sys
import os

# Suppress TF noise + enable optimizations BEFORE importing TF
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '1'

import yfinance as yf
import pandas as pd
import numpy as np
from src.ml.rl_agent import TradingEnv, DQNAgent
from src.core.logger import logger

# Ustawienia trenowania (override: python train_rl.py 500)
EPISODES = 300
SEQ_LEN = 20            # długość okna stanu (liczba świec)
INITIAL_BALANCE = 10000
TRANSACTION_COST = 0.001

def fetch_historical_data(symbol="GC=F", periods=None, intervals=None):
    """
    Pobiera dane historyczne z yfinance.
    Próbuje kolejne kombinacje period/interval aż znajdzie wystarczająco danych.
    """
    if periods is None:
        periods = ["6mo", "3mo", "1mo"]
    if intervals is None:
        intervals = ["15m", "1h", "1d"]

    ticker = yf.Ticker(symbol)

    for period in periods:
        for interval in intervals:
            try:
                df = ticker.history(period=period, interval=interval)
                if df is not None and len(df) >= 100:
                    df = df.reset_index()
                    # Normalizuj nazwy kolumn
                    col_map = {c: c.lower() for c in df.columns}
                    df.rename(columns=col_map, inplace=True)

                    required = ['open', 'high', 'low', 'close', 'volume']
                    available = [c for c in required if c in df.columns]
                    df = df[available]

                    print(f"✅ Pobrano {len(df)} świec ({symbol}, {period}, {interval})")
                    return df
            except Exception as e:
                print(f"⚠️ Nie udało się pobrać {period}/{interval}: {e}")
                continue

    raise ValueError(f"Nie udało się pobrać danych dla {symbol}")


def main():
    global EPISODES
    if len(sys.argv) > 1:
        try:
            EPISODES = int(sys.argv[1])
        except ValueError:
            pass

    print("=" * 60)
    print(f"🧠 TRENOWANIE AGENTA RL (Double DQN) — {EPISODES} epizodów")
    print("=" * 60)

    # 1. Pobierz dane
    print("\n📊 Pobieranie danych historycznych...")
    data = fetch_historical_data()
    if data.empty:
        logger.error("Brak danych – trenowanie przerwane.")
        return

    # 2. Podział na train/validation (80/20)
    split_idx = int(len(data) * 0.8)
    train_data = data.iloc[:split_idx].reset_index(drop=True)
    val_data = data.iloc[split_idx:].reset_index(drop=True)
    print(f"📈 Train: {len(train_data)} świec | Validation: {len(val_data)} świec")

    # 3. Stwórz środowisko
    env = TradingEnv(train_data, initial_balance=INITIAL_BALANCE, transaction_cost=TRANSACTION_COST)
    state = env.reset()
    state_size = len(state)
    action_size = 3  # hold, buy, sell

    # 4. Zainicjuj agenta
    agent = DQNAgent(state_size, action_size)
    print(f"🤖 Agent: state_size={state_size}, action_size={action_size}")
    print(f"🔧 Double DQN, memory=10000, target_update_freq={agent.target_update_freq}")

    # 5. Trenowanie
    scores = []
    best_reward = -float('inf')
    best_balance = 0
    best_win_rate = 0
    info = {}

    import gc

    for episode in range(EPISODES):
        state = env.reset()
        total_reward = 0
        done = False
        step = 0
        replay_count = 0
        while not done:
            action = agent.act(state)
            next_state, reward, done, info = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            step += 1
            # Replay every 8 steps, max 40 per episode, skip if memory too small
            if step % 8 == 0 and replay_count < 40 and len(agent.memory) >= 256:
                agent.replay(batch_size=32)
                replay_count += 1

        scores.append(total_reward)
        avg = np.mean(scores[-min(20, len(scores)):])
        win_rate = info.get('win_rate', 0) * 100
        balance = info.get('balance', INITIAL_BALANCE)

        if total_reward > best_reward:
            best_reward = total_reward
            best_balance = balance
            best_win_rate = win_rate

        # Update learning rate (cosine annealing)
        agent.update_lr(episode, EPISODES)

        # Every episode: short progress line
        print(f"  [{episode+1}/{EPISODES}] reward={total_reward:.2f} bal=${balance:.0f} ε={agent.epsilon:.3f} replays={replay_count}", flush=True)

        # Every 50 episodes: full status report
        if (episode + 1) % 50 == 0:
            logger.info(
                f"═══ Ep {episode+1}/{EPISODES} ═══ "
                f"avg_reward={avg:.4f} | balance=${balance:.0f} | "
                f"trades={info.get('total_trades', 0)} | win_rate={win_rate:.0f}% | "
                f"best_balance=${best_balance:.0f} | ε={agent.epsilon:.3f}"
            )
            # Save checkpoint every 50 episodes (crash-safe)
            try:
                agent.save("models/rl_agent.keras")
                print(f"  💾 Checkpoint saved (ep {episode+1})", flush=True)
            except Exception as e:
                print(f"  ⚠️ Checkpoint save failed: {e}", flush=True)

        # Memory cleanup every 100 episodes to prevent PyCharm OOM
        if (episode + 1) % 100 == 0:
            gc.collect()
            try:
                import tensorflow as tf
                tf.keras.backend.clear_session()
            except Exception:
                pass

    # 6. Walidacja na danych testowych
    print("\n📊 Walidacja na danych out-of-sample...")
    val_env = TradingEnv(val_data, initial_balance=INITIAL_BALANCE, transaction_cost=TRANSACTION_COST)
    old_epsilon = agent.epsilon
    agent.epsilon = 0.0  # Pure exploitation
    state = val_env.reset()
    done = False
    while not done:
        action = agent.act(state)
        state, _, done, info = val_env.step(action)

    val_balance = info.get('balance', INITIAL_BALANCE)
    val_return = (val_balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    val_trades = info.get('total_trades', 0)
    val_win_rate = info.get('win_rate', 0) * 100
    agent.epsilon = old_epsilon

    print(f"📈 Wynik walidacji: balance=${val_balance:.0f} ({val_return:+.1f}%)")
    print(f"   Transakcje: {val_trades} | Win rate: {val_win_rate:.0f}%")

    # 7. Zapisz model
    os.makedirs("models", exist_ok=True)
    model_path = "models/rl_agent.keras"
    agent.save(model_path)
    logger.info(f"Model zapisany do {model_path}")

    # 8. Zapisz metryki do bazy
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        db.set_param("rl_best_reward", best_reward)
        db.set_param("rl_best_win_rate", best_win_rate)
        db.set_param("rl_val_return", val_return)
        db.set_param("rl_val_win_rate", val_win_rate)
        db.set_param("rl_episodes_trained", EPISODES)
        print("📝 Metryki zapisane do bazy.")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać metryk: {e}")

    print("\n✅ Trenowanie zakończone.")
    print(f"   Najlepsza nagroda: {best_reward:.4f}")
    print(f"   Walidacja: ${val_balance:.0f} ({val_return:+.1f}%)")
    print(f"   Win rate (val): {val_win_rate:.0f}%")

if __name__ == "__main__":
    main()
