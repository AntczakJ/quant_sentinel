"""
rl_agent.py — agent uczenia przez wzmocnienie (DQN).

Optimized:
- GPU detection via centralized compute module
- tf.function compiled inference for faster act()
- Batch replay with pre-allocated tensors
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
from src.core.logger import logger
from src.analysis.compute import detect_gpu, get_tf_batch_size

class TradingEnv:
    """
    Srodowisko tradingowe z realistycznym SL/TP opartym na ATR.

    Kluczowe roznice vs poprzednia wersja:
      - Agent NIE decyduje kiedy zamknac — pozycja zamyka sie automatycznie
        na SL lub TP, tak jak w live systemie
      - SL = 1.5 * ATR, TP = SL * target_rr (domyslnie 2.5)
      - Agent uczy sie KIEDY WEJSC i W JAKIM KIERUNKU, nie kiedy wyjsc
      - Win = cena dotarla do TP, Loss = cena dotarla do SL
      - Trailing stop: po 1R → breakeven, po 1.5R → lock 1R

    Actions:
      0 = HOLD (czekaj / nie rob nic)
      1 = BUY  (otworz LONG z automatycznym SL/TP)
      2 = SELL (otworz SHORT z automatycznym SL/TP)

    Optimized: prices pre-cached as numpy array.
    """
    def __init__(self, data, initial_balance=10000, transaction_cost=0.001,
                 atr_period=14, sl_atr_mult=1.5, target_rr=2.5):
        self.data = data
        self._prices = np.ascontiguousarray(data['close'].values, dtype=np.float64)
        self._highs = np.ascontiguousarray(data['high'].values, dtype=np.float64) if 'high' in data.columns else self._prices
        self._lows = np.ascontiguousarray(data['low'].values, dtype=np.float64) if 'low' in data.columns else self._prices
        self._n = len(self._prices)
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost
        self.atr_period = atr_period
        self.sl_atr_mult = sl_atr_mult
        self.target_rr = target_rr
        self._state_buf = np.zeros(22, dtype=np.float64)
        # Pre-compute ATR for entire dataset
        self._atr = self._compute_atr()
        self.reset()

    def _compute_atr(self):
        """Pre-compute ATR array for the entire dataset."""
        n = len(self._prices)
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                self._highs[i] - self._lows[i],
                abs(self._highs[i] - self._prices[i - 1]),
                abs(self._lows[i] - self._prices[i - 1])
            )
        # Rolling mean ATR
        atr = np.zeros(n)
        for i in range(self.atr_period, n):
            atr[i] = np.mean(tr[i - self.atr_period + 1:i + 1])
        # Fill early values with first valid ATR
        first_valid = atr[self.atr_period] if self.atr_period < n else 1.0
        atr[:self.atr_period] = first_valid
        return atr

    def reset(self):
        self.balance = self.initial_balance
        self.position = 0       # 0=flat, 1=long, -1=short
        self.entry_price = 0
        self.sl_price = 0       # automatyczny stop loss
        self.tp_price = 0       # automatyczny take profit
        self.trailing_sl = 0    # trailing stop level
        self.index = 0
        self.done = False
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.breakevens = 0
        self.rewards_history = []
        self.hold_steps = 0
        self.consecutive_losses = 0
        return self._state()

    def _state(self):
        start = max(0, self.index - 19)
        end = self.index + 1
        window = self._prices[start:end]
        buf = self._state_buf
        buf[:] = 0.0

        if len(window) >= 2:
            returns = np.diff(window) / window[:-1]
            std = np.std(returns) if len(returns) > 1 else 1e-6
            if std < 1e-8:
                std = 1e-6
            normalized = returns / std
            buf[20 - len(normalized):20] = normalized
        else:
            buf[19] = 0.0

        buf[20] = self.balance / self.initial_balance
        buf[21] = self.position
        return buf.copy()

    def step(self, action):
        if self.index >= self._n - 1:
            self.done = True
            # Wymus zamkniecie otwartej pozycji na koncu danych
            if self.position != 0:
                reward = self._close_position(self._prices[self.index])
            else:
                reward = 0.0
            return self._state(), reward, self.done, self._info()

        price = self._prices[self.index]
        current_high = self._highs[self.index]
        current_low = self._lows[self.index]
        atr = self._atr[self.index]
        reward = 0.0

        # ═══════════════════════════════════════════════════
        # 1. SPRAWDZ SL/TP DLA OTWARTEJ POZYCJI (przed nowa akcja)
        # ═══════════════════════════════════════════════════
        if self.position != 0:
            self.hold_steps += 1
            active_sl = self.trailing_sl if self.trailing_sl != 0 else self.sl_price

            if self.position == 1:  # LONG
                # Trailing stop update
                sl_dist = self.entry_price - self.sl_price
                if sl_dist > 0:
                    r_mult = (current_high - self.entry_price) / sl_dist
                    if r_mult >= 1.5 and self.trailing_sl < self.entry_price + sl_dist:
                        self.trailing_sl = self.entry_price + sl_dist  # lock 1R
                        active_sl = self.trailing_sl
                    elif r_mult >= 1.0 and self.trailing_sl < self.entry_price:
                        self.trailing_sl = self.entry_price + 0.01  # breakeven
                        active_sl = self.trailing_sl

                # Check TP hit (high touched TP)
                if current_high >= self.tp_price:
                    reward = self._close_position(self.tp_price)
                # Check SL hit (low touched SL)
                elif current_low <= active_sl:
                    reward = self._close_position(active_sl)

            elif self.position == -1:  # SHORT
                sl_dist = self.sl_price - self.entry_price
                if sl_dist > 0:
                    r_mult = (self.entry_price - current_low) / sl_dist
                    if r_mult >= 1.5 and (self.trailing_sl == 0 or self.trailing_sl > self.entry_price - sl_dist):
                        self.trailing_sl = self.entry_price - sl_dist
                        active_sl = self.trailing_sl
                    elif r_mult >= 1.0 and (self.trailing_sl == 0 or self.trailing_sl > self.entry_price):
                        self.trailing_sl = self.entry_price - 0.01
                        active_sl = self.trailing_sl

                if current_low <= self.tp_price:
                    reward = self._close_position(self.tp_price)
                elif current_high >= active_sl:
                    reward = self._close_position(active_sl)

        # ═══════════════════════════════════════════════════
        # 2. NOWA AKCJA (tylko jesli flat)
        # ═══════════════════════════════════════════════════
        if self.position == 0 and action in (1, 2):
            sl_distance = max(atr * self.sl_atr_mult, price * 0.002)  # min 0.2%
            tp_distance = sl_distance * self.target_rr

            if action == 1:  # BUY → LONG
                self.position = 1
                self.entry_price = price
                self.sl_price = price - sl_distance
                self.tp_price = price + tp_distance
                self.trailing_sl = 0
                self.hold_steps = 0
                self.balance -= self.transaction_cost * price

            elif action == 2:  # SELL → SHORT
                self.position = -1
                self.entry_price = price
                self.sl_price = price + sl_distance
                self.tp_price = price - tp_distance
                self.trailing_sl = 0
                self.hold_steps = 0
                self.balance -= self.transaction_cost * price

        # Kara za hold bez pozycji (lekka — zacheta do szukania wejsc)
        elif self.position == 0 and action == 0:
            reward = 0.0  # neutralne

        self.rewards_history.append(reward)
        self.index += 1

        if self.index >= self._n - 1:
            self.done = True
            if self.position != 0:
                reward += self._close_position(self._prices[self.index])
            final_return = (self.balance - self.initial_balance) / self.initial_balance
            reward += final_return * 3

        return self._state(), reward, self.done, self._info()

    def _close_position(self, exit_price):
        """Zamknij pozycje i oblicz reward."""
        if self.position == 1:
            pnl = (exit_price - self.entry_price) / self.entry_price
        elif self.position == -1:
            pnl = (self.entry_price - exit_price) / self.entry_price
        else:
            return 0.0

        # Asymetryczny reward — wieksza kara za straty
        if pnl > 0:
            reward = pnl * 10
            self.wins += 1
            self.consecutive_losses = 0
        elif pnl < -0.0001:  # maly bufor na spread/breakeven
            reward = pnl * 15
            self.losses += 1
            self.consecutive_losses += 1
            # Dodatkowa kara za consecutive losses (uczy unikania serii strat)
            if self.consecutive_losses >= 3:
                reward *= 1.2
        else:
            # Breakeven (trailing stop na entry)
            reward = 0.1  # maly bonus za breakeven (lepsze niz strata)
            self.breakevens += 1
            self.consecutive_losses = 0

        self.balance += pnl * self.entry_price
        self.total_trades += 1
        self.position = 0
        self.entry_price = 0
        self.sl_price = 0
        self.tp_price = 0
        self.trailing_sl = 0
        self.hold_steps = 0

        return reward

    def _info(self):
        return {
            'balance': self.balance,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'breakevens': self.breakevens,
            'win_rate': self.wins / max(self.total_trades, 1),
            'consecutive_losses': self.consecutive_losses,
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
        # Warm up the model with a dummy prediction (builds computation graph)
        try:
            model(np.zeros((1, self.state_size), dtype=np.float32), training=False)
        except (RuntimeError, ValueError, TypeError):
            pass
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

        # Use larger batch on GPU for better utilization
        effective_batch = min(get_tf_batch_size(batch_size, batch_size * 2), len(self.memory))
        minibatch = random.sample(self.memory, effective_batch)

        # Pre-allocate arrays (avoids repeated allocation per replay call)
        states     = np.array([s  for s, a, r, ns, d in minibatch], dtype=np.float32)
        next_states= np.array([ns for s, a, r, ns, d in minibatch], dtype=np.float32)
        rewards    = np.array([r  for s, a, r, ns, d in minibatch], dtype=np.float32)
        actions    = np.array([a  for s, a, r, ns, d in minibatch], dtype=np.int32)
        dones      = np.array([d  for s, a, r, ns, d in minibatch], dtype=bool)

        # Double DQN: online model selects action, target model evaluates value
        # Direct tensor calls (faster than model.predict())
        q_values       = self.model(states,      training=False).numpy()
        q_next_online  = self.model(next_states, training=False).numpy()
        q_next_target  = self.target_model(next_states, training=False).numpy()

        # Vectorized Double-DQN target calculation (no Python loop)
        idx = np.arange(effective_batch)
        best_actions = np.argmax(q_next_online, axis=1)
        max_q_next   = q_next_target[idx, best_actions]
        targets      = rewards + self.gamma * max_q_next * (~dones)
        q_values[idx, actions] = targets

        self.model.fit(states, q_values, epochs=1, verbose=0, batch_size=effective_batch)

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
        # Atomic save: write to tmp, then rename
        tmp_path = path + '.tmp'
        self.model.save(tmp_path)
        os.replace(tmp_path, path)
        params_path = path + '.params'
        params_tmp = params_path + '.tmp'
        with open(params_tmp, 'wb') as f:
            pickle.dump({'epsilon': self.epsilon}, f)
        os.replace(params_tmp, params_path)
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
