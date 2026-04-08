"""
rl_agent.py — agent uczenia przez wzmocnienie (DQN).
"""

import numpy as np
import random
from collections import deque
import tensorflow as tf
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

    Optimized: prices pre-cached as numpy array — eliminates pandas overhead
    in _state() (called ~600k times during training).
    """
    def __init__(self, data, initial_balance=10000, transaction_cost=0.001):
        self.data = data
        # Pre-cache prices as contiguous numpy array (avoids .iloc[] on every step)
        self._prices = np.ascontiguousarray(data['close'].values, dtype=np.float64)
        self._n = len(self._prices)
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost
        # Pre-allocate state buffer (avoids np.concatenate on every step)
        self._state_buf = np.zeros(22, dtype=np.float64)
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
        # Znormalizowane zwroty procentowe zamiast surowych cen — model uczy się
        # wzorców niezależnych od poziomu ceny, co poprawia generalizację
        start = max(0, self.index - 19)
        end = self.index + 1
        window = self._prices[start:end]
        buf = self._state_buf
        buf[:] = 0.0

        if len(window) >= 2:
            # Zwroty procentowe normalizowane przez zmienność
            returns = np.diff(window) / window[:-1]
            std = np.std(returns) if len(returns) > 1 else 1e-6
            if std < 1e-8:
                std = 1e-6
            normalized = returns / std
            # Wstaw znormalizowane zwroty (max 19 wartości z 20 cen)
            buf[20 - len(normalized):20] = normalized
        else:
            buf[19] = 0.0

        buf[20] = self.balance / self.initial_balance
        buf[21] = self.position
        return buf.copy()  # copy needed since buf is reused

    def step(self, action):
        if self.index >= self._n - 1:
            self.done = True
            return self._state(), 0, self.done, {}

        price = self._prices[self.index]
        next_price = self._prices[self.index + 1]
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
            # Asymetryczny reward: większa kara za straty niż nagroda za zyski
            # Uczy agenta unikać strat zamiast łapać każdy mały ruch
            if pnl > 0:
                reward = pnl * 8
            else:
                reward = pnl * 12  # Większa kara za straty
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
            unrealized = change if self.position == 1 else -change
            reward = unrealized * 1.5
            self.balance += unrealized * price
            self.hold_steps += 1
            # Kara za zbyt długie trzymanie (zachęta do realizacji)
            if self.hold_steps > 30:
                reward -= 0.002

        # Brak pozycji — minimalna kara, ale nie za agresywna
        elif self.position == 0:
            reward = 0.0  # Neutralne — niech uczy się z wyników, nie z kary za czekanie

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

    Ulepszenia:
    - Cosine LR decay: LR maleje od lr_start do lr_min w trakcie treningu
    - Soft target updates (Polyak averaging): tau=0.005 — płynniejsza konwergencja
    """
    def __init__(self, state_size, action_size=3, lr=0.001, gamma=0.95,
                 epsilon=1.0, epsilon_min=0.01, epsilon_decay=0.995,
                 target_update_freq=200, tau=0.005):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=50000)  # Większa pamięć — lepsze replay sampling
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.target_update_freq = target_update_freq
        self.tau = tau              # Polyak averaging coefficient
        self.lr_start = lr
        self.lr_min = lr * 0.1     # decay to 10% of initial LR
        self.train_step = 0
        self.model = self._build(lr)
        self.target_model = self._build(lr)
        self._sync_target_hard()

    def _build(self, lr):
        model = Sequential([
            Dense(64, input_dim=self.state_size, activation='relu'),
            Dense(64, activation='relu'),
            Dense(32, activation='relu'),
            Dense(self.action_size, activation='linear', dtype='float32')
        ])
        model.compile(loss='huber', optimizer=Adam(learning_rate=lr))
        return model

    def _sync_target_hard(self):
        """Full weight copy (used at initialization)."""
        self.target_model.set_weights(self.model.get_weights())

    def _sync_target_soft(self):
        """Polyak averaging: target = tau*online + (1-tau)*target.
        Smoother updates → more stable training."""
        for t_w, o_w in zip(self.target_model.weights, self.model.weights):
            t_w.assign(self.tau * o_w + (1.0 - self.tau) * t_w)

    def remember(self, state, action, reward, next_state, done):
        self.memory.append((state, action, reward, next_state, done))

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        # Direct tensor call avoids per-call Python overhead of model.predict()
        q = self.model(state.reshape(1, -1), training=False).numpy()[0]
        return np.argmax(q)

    def replay(self, batch_size=32):
        if len(self.memory) < batch_size:
            return
        minibatch = random.sample(self.memory, batch_size)

        states     = np.array([s  for s, a, r, ns, d in minibatch], dtype=np.float32)
        next_states= np.array([ns for s, a, r, ns, d in minibatch], dtype=np.float32)
        rewards    = np.array([r  for s, a, r, ns, d in minibatch], dtype=np.float32)
        actions    = np.array([a  for s, a, r, ns, d in minibatch], dtype=np.int32)
        dones      = np.array([d  for s, a, r, ns, d in minibatch], dtype=bool)

        # Double DQN: online model wybiera akcję, target model ocenia wartość
        q_values       = self.model(states,      training=False).numpy()
        q_next_online  = self.model(next_states, training=False).numpy()
        q_next_target  = self.target_model(next_states, training=False).numpy()

        # Vectorized Double-DQN target calculation (no Python loop)
        best_actions = np.argmax(q_next_online, axis=1)
        max_q_next   = q_next_target[np.arange(batch_size), best_actions]
        targets      = rewards + self.gamma * max_q_next * (~dones)
        q_values[np.arange(batch_size), actions] = targets

        self.model.fit(states, q_values, epochs=1, verbose=0, batch_size=batch_size)

        self.train_step += 1

        # Soft target update (Polyak) every step — much smoother than periodic hard copy
        self._sync_target_soft()

        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def update_lr(self, episode: int, total_episodes: int):
        """Cosine annealing LR schedule — decays LR smoothly over training."""
        import math
        progress = episode / max(total_episodes, 1)
        new_lr = self.lr_min + 0.5 * (self.lr_start - self.lr_min) * (1 + math.cos(math.pi * progress))
        self.model.optimizer.learning_rate.assign(new_lr)
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
        """Build state vector for prediction: normalized returns + balance + position.
        Musi być spójne z _state() w TradingEnv."""
        prices = close_prices[-20:] if len(close_prices) >= 20 else close_prices
        buf = np.zeros(22)

        if len(prices) >= 2:
            returns = np.diff(prices) / prices[:-1]
            std = np.std(returns) if len(returns) > 1 else 1e-6
            if std < 1e-8:
                std = 1e-6
            normalized = returns / std
            buf[20 - len(normalized):20] = normalized

        buf[20] = balance
        buf[21] = position
        return buf
