#!/usr/bin/env python3
"""
train_rl.py — trenowanie agenta RL na historycznych danych.
"""

import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np
from src.rl_agent import TradingEnv, DQNAgent
from src.logger import logger

# Ustawienia trenowania
EPISODES = 5          # liczba epizodów (przebiegów symulacji)
SEQ_LEN = 20            # długość okna stanu (liczba świec)
INITIAL_BALANCE = 10000
TRANSACTION_COST = 0.001

def fetch_historical_data(symbol="GC=F", period="1mo", interval="15m"):
    """Pobiera dane historyczne z yfinance."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        raise ValueError(f"Nie udało się pobrać danych dla {symbol}")
    # Reset indeksu i uproszczenie
    df = df.reset_index()
    df.columns = ['time', 'open', 'high', 'low', 'close', 'volume', 'dividends', 'splits']
    df = df[['open', 'high', 'low', 'close', 'volume']]
    print(f"Pobrano {len(df)} świec.")
    return df

def main():
    # 1. Pobierz dane
    print("Pobieranie danych historycznych...")
    data = fetch_historical_data()
    if data.empty:
        logger.error("Brak danych – trenowanie przerwane.")
        return

    # 2. Stwórz środowisko
    env = TradingEnv(data, initial_balance=INITIAL_BALANCE, transaction_cost=TRANSACTION_COST)
    state = env.reset()
    state_size = len(state)
    action_size = 3  # hold, buy, sell

    # 3. Zainicjuj agenta
    agent = DQNAgent(state_size, action_size)

    # 4. Trenowanie
    scores = []
    for episode in range(EPISODES):
        state = env.reset()
        total_reward = 0
        done = False
        step = 0
        while not done:
            action = agent.act(state)
            next_state, reward, done, _ = env.step(action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            step += 1
            if step % 10 == 0:
                agent.replay(batch_size=32)

        scores.append(total_reward)  # ← DODANE
        # Wyświetlaj co epizod (nie co 10, bo masz tylko 5)
        avg = np.mean(scores[-min(5, len(scores)):])
        logger.info(
            f"Epizod {episode + 1}/{EPISODES} – nagroda: {total_reward:.4f} – średnia: {avg:.4f} – epsilon: {agent.epsilon:.3f}")

    # 5. Zapisz model
    os.makedirs("models", exist_ok=True)
    model_path = "models/rl_agent.keras"
    agent.save(model_path)
    logger.info(f"Model zapisany do {model_path}")

    print("Trenowanie zakończone.")

if __name__ == "__main__":
    main()