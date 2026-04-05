"""
rl_agent.py — agent uczenia przez wzmocnienie (DQN).
"""

import numpy as np
import random
from collections import deque
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense
from tensorflow.keras.optimizers import Adam
import os
import pickle
from src.logger import logger

class TradingEnv:
    """
    Środowisko tradingowe z ulepszonym reward shaping:
    - Nagroda za zrealizowany P/L (nie za trzymanie)
    - Kara za brak akcji (zachęta do aktywnego tradingu)
    - Kara za zbyt częste zmiany pozycji (overtrading)
    - Sharpe-style normalizacja
    """
    def __init__(self, data, initial_balance=10000, transaction_cost=0.001):
        self.data = data
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost
        self.reset()

    def reset(self):
        self.balance = self.initial_balance
        self.position = 0
        self.entry_price = 0
        self.index = 0
        self.done = False
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.rewards_history = []
        self.hold_steps = 0
        return self._state()

    def _state(self):
        window = self.data['close'].iloc[max(0, self.index - 19):self.index + 1].values
        if len(window) < 20:
            window = np.pad(window, (20-len(window),0), 'constant')
        return np.concatenate([window, [self.balance/self.initial_balance, self.position]])

    def step(self, action):
        if self.index >= len(self.data) - 1:
            self.done = True
            return self._state(), 0, self.done, {}

        price = self.data['close'].iloc[self.index]
        next_price = self.data['close'].iloc[self.index + 1]
        change = (next_price - price) / price
        reward = 0.0

        # Otwarcie pozycji LONG
        if action == 1 and self.position == 0:
            self.position = 1
            self.entry_price = price
            self.balance -= self.transaction_cost * price
            self.hold_steps = 0

        # Otwarcie pozycji SHORT
        elif action == 2 and self.position == 0:
            self.position = -1
            self.entry_price = price
            self.balance -= self.transaction_cost * price
            self.hold_steps = 0

        # Zamknięcie pozycji
        elif action == 0 and self.position != 0:
            pnl = (price - self.entry_price) / self.entry_price if self.position == 1 else (self.entry_price - price) / self.entry_price
            reward = pnl * 10  # Skalowanie nagrody za realizację
            self.balance += pnl * price
            self.total_trades += 1
            if pnl > 0:
                self.wins += 1
            else:
                self.losses += 1
            self.position = 0
            self.entry_price = 0

        # Holding reward/penalty
        elif self.position != 0:
            # Mała nagroda za trzymanie zyskownej pozycji
            unrealized = change if self.position == 1 else -change
            reward = unrealized * 2  # Mniejsza nagroda za niezrealizowany zysk
            self.balance += unrealized * price
            self.hold_steps += 1
            # Kara za zbyt długie trzymanie (zachęta do realizacji)
            if self.hold_steps > 50:
                reward -= 0.001

        # Minimalna kara za brak pozycji (zachęta do wchodzenia)
        elif self.position == 0:
            reward = -0.0001  # Mała kara za czekanie

        self.rewards_history.append(reward)
        self.index += 1

        if self.index >= len(self.data) - 1:
            self.done = True
            # Bonus/kara końcowa za ogólny wynik
            final_return = (self.balance - self.initial_balance) / self.initial_balance
            reward += final_return * 5

        return self._state(), reward, self.done, {
            'balance': self.balance,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'win_rate': self.wins / max(self.total_trades, 1)
        }

class DQNAgent:
    """
    Double DQN Agent — używa target_model do stabilniejszego trenowania.
    """
    def __init__(self, state_size, action_size=3, lr=0.001, gamma=0.95,
                 epsilon=1.0, epsilon_min=0.01, epsilon_decay=0.995,
                 target_update_freq=200):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=10000)  # Większa pamięć replay
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.target_update_freq = target_update_freq
        self.train_step = 0
        self.model = self._build(lr)
        self.target_model = self._build(lr)
        self._sync_target()

    def _build(self, lr):
        model = Sequential([
            Dense(64, input_dim=self.state_size, activation='relu'),
            Dense(64, activation='relu'),
            Dense(32, activation='relu'),
            Dense(self.action_size, activation='linear')
        ])
        model.compile(loss='huber', optimizer=Adam(learning_rate=lr))
        return model

    def _sync_target(self):
        """Kopiuj wagi z modelu online do target."""
        self.target_model.set_weights(self.model.get_weights())

    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        q = self.model.predict(state.reshape(1,-1), verbose=0)[0]
        return np.argmax(q)

    def replay(self, batch_size=32):
        if len(self.memory) < batch_size:
            return
        minibatch = random.sample(self.memory, batch_size)

        states = np.array([s for s, a, r, ns, d in minibatch])
        next_states = np.array([ns for s, a, r, ns, d in minibatch])

        # Double DQN: online model wybiera akcję, target model ocenia wartość
        q_values = self.model.predict(states, verbose=0)
        q_next_online = self.model.predict(next_states, verbose=0)
        q_next_target = self.target_model.predict(next_states, verbose=0)

        for i, (state, action, reward, next_state, done) in enumerate(minibatch):
            target = reward
            if not done:
                # Double DQN: wybierz akcję z online, ale wartość z target
                best_action = np.argmax(q_next_online[i])
                target += self.gamma * q_next_target[i][best_action]
            q_values[i][action] = target

        self.model.fit(states, q_values, epochs=1, verbose=0, batch_size=batch_size)

        self.train_step += 1
        if self.train_step % self.target_update_freq == 0:
            self._sync_target()
            logger.debug(f"🔄 Target network synced at step {self.train_step}")

        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay
    def save(self, path):
        self.model.save(path)
        with open(path+'.params', 'wb') as f:
            pickle.dump({'epsilon':self.epsilon}, f)
    def load(self, path):
        from tensorflow.keras.models import load_model
        self.model = load_model(path)
        with open(path+'.params', 'rb') as f:
            p = pickle.load(f)
            self.epsilon = p['epsilon']

    def build_state(self, close_prices, balance=1.0, position=0):
        """Build state vector for prediction: last 20 close prices + normalized balance + position."""
        if len(close_prices) < 20:
            padded = np.zeros(20)
            padded[-len(close_prices):] = close_prices
        else:
            padded = close_prices[-20:]
        return np.concatenate([padded, [balance, position]])
