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


# ═══════════════════════════════════════════════════════════
# Prioritized Experience Replay (PER)
# ═══════════════════════════════════════════════════════════

class SumTree:
    """Binary sum-tree for O(log n) proportional sampling.

    Leaf nodes store priorities, internal nodes store sums of children.
    Total priority = tree[0]. Sampling: draw uniform(0, total), walk tree.
    """
    def __init__(self, capacity):
        self.capacity = capacity
        self.tree = np.zeros(2 * capacity - 1, dtype=np.float64)
        self.data = [None] * capacity
        self.size = 0
        self.write_idx = 0

    def _propagate(self, idx, change):
        parent = (idx - 1) // 2
        self.tree[parent] += change
        if parent != 0:
            self._propagate(parent, change)

    def update(self, idx, priority):
        change = priority - self.tree[idx]
        self.tree[idx] = priority
        self._propagate(idx, change)

    def add(self, priority, data):
        tree_idx = self.write_idx + self.capacity - 1
        self.data[self.write_idx] = data
        self.update(tree_idx, priority)
        self.write_idx = (self.write_idx + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def get(self, value):
        """Walk tree to find leaf for given cumulative value."""
        idx = 0
        while True:
            left = 2 * idx + 1
            right = left + 1
            if left >= len(self.tree):
                break
            if value <= self.tree[left] or right >= len(self.tree):
                idx = left
            else:
                value -= self.tree[left]
                idx = right
        data_idx = idx - self.capacity + 1
        return idx, self.tree[idx], self.data[data_idx]

    @property
    def total(self):
        return self.tree[0]

    @property
    def max_priority(self):
        leaf_start = self.capacity - 1
        return max(self.tree[leaf_start:leaf_start + self.size]) if self.size > 0 else 1.0


class PrioritizedReplayBuffer:
    """PER buffer with proportional prioritization.

    alpha: priority exponent (0=uniform, 1=full priority)
    beta: importance-sampling correction (anneals 0.4 → 1.0)
    """
    def __init__(self, capacity=20000, alpha=0.6, beta_start=0.4, epsilon_per=1e-5):
        self.tree = SumTree(capacity)
        self.alpha = alpha
        self.beta = beta_start
        self.beta_start = beta_start
        self.epsilon_per = epsilon_per
        self.maxlen = capacity

    def __len__(self):
        return self.tree.size

    def add(self, experience, td_error=None):
        priority = (abs(td_error) + self.epsilon_per) ** self.alpha if td_error is not None \
            else self.tree.max_priority if self.tree.size > 0 else 1.0
        self.tree.add(priority, experience)

    def sample(self, batch_size):
        """Sample batch proportional to priority. Returns (indices, experiences, IS_weights)."""
        indices = []
        experiences = []
        priorities = []
        segment = self.tree.total / batch_size

        for i in range(batch_size):
            low = segment * i
            high = segment * (i + 1)
            value = np.random.uniform(low, high)
            idx, priority, data = self.tree.get(value)
            if data is None:
                # Fallback: retry with random value
                value = np.random.uniform(0, self.tree.total)
                idx, priority, data = self.tree.get(value)
            if data is None:
                continue
            indices.append(idx)
            experiences.append(data)
            priorities.append(priority)

        if len(experiences) == 0:
            return [], [], np.array([])

        # Importance sampling weights
        priorities = np.array(priorities, dtype=np.float64)
        probs = priorities / (self.tree.total + 1e-10)
        is_weights = (self.tree.size * probs) ** (-self.beta)
        is_weights /= is_weights.max()  # normalize to [0, 1]

        return indices, experiences, is_weights.astype(np.float32)

    def update_priorities(self, indices, td_errors):
        for idx, td_error in zip(indices, td_errors):
            priority = (abs(td_error) + self.epsilon_per) ** self.alpha
            self.tree.update(idx, priority)

    def anneal_beta(self, step, total_steps):
        """Anneal beta from beta_start to 1.0 over training."""
        self.beta = min(1.0, self.beta_start + (1.0 - self.beta_start) * step / max(total_steps, 1))

    def to_list(self):
        """Serialize for save — returns list of (priority, experience) tuples."""
        result = []
        leaf_start = self.tree.capacity - 1
        for i in range(self.tree.size):
            data_idx = (self.tree.write_idx - self.tree.size + i) % self.tree.capacity
            tree_idx = data_idx + leaf_start
            result.append((self.tree.tree[tree_idx], self.tree.data[data_idx]))
        return result

    @classmethod
    def from_list(cls, saved, capacity=20000, alpha=0.6, beta_start=0.4):
        """Deserialize from save."""
        buf = cls(capacity=capacity, alpha=alpha, beta_start=beta_start)
        for priority, experience in saved:
            buf.tree.add(priority, experience)
        return buf

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
                 atr_period=14, sl_atr_mult=1.5, target_rr=2.5, noise_std=0.0):
        self.data = data
        self._base_prices = np.ascontiguousarray(data['close'].values, dtype=np.float64)
        self._base_highs = np.ascontiguousarray(data['high'].values, dtype=np.float64) if 'high' in data.columns else self._base_prices.copy()
        self._base_lows = np.ascontiguousarray(data['low'].values, dtype=np.float64) if 'low' in data.columns else self._base_prices.copy()
        self._prices = self._base_prices.copy()
        self._highs = self._base_highs.copy()
        self._lows = self._base_lows.copy()
        self._n = len(self._prices)
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost
        self.atr_period = atr_period
        self.sl_atr_mult = sl_atr_mult
        self.target_rr = target_rr
        self.noise_std = noise_std  # augmentacja: szum na cenach per reset
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
        # Augmentacja: dodaj drobny szum do cen per episode
        if self.noise_std > 0:
            noise = np.random.normal(1.0, self.noise_std, self._n)
            self._prices = self._base_prices * noise
            self._highs = self._base_highs * noise
            self._lows = self._base_lows * noise
            # Zachowaj relację high >= close >= low
            self._highs = np.maximum(self._highs, self._prices)
            self._lows = np.minimum(self._lows, self._prices)
            self._atr = self._compute_atr()

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
                 target_update_freq=200, tau=0.005, memory_size=20000,
                 n_step=3):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = PrioritizedReplayBuffer(capacity=memory_size)
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.target_update_freq = target_update_freq
        self.tau = tau              # Polyak averaging coefficient
        self.lr_start = lr
        self.lr_min = lr * 0.1     # decay to 10% of initial LR
        self.train_step = 0
        # N-step returns: bufor ostatnich n transitions
        self.n_step = n_step
        self.n_step_buffer = deque(maxlen=n_step)
        self.model = self._build(lr)
        self.target_model = self._build(lr)
        self._sync_target_hard()

    def _build(self, lr):
        import tensorflow as tf
        model = Sequential([
            Dense(64, input_dim=self.state_size, activation='relu'),
            Dense(64, activation='relu'),
            Dense(32, activation='relu'),
            Dense(self.action_size, activation='linear', dtype='float32')
        ])
        model.compile(loss='huber', optimizer=Adam(learning_rate=lr))
        # Warm up: build computation graph once
        try:
            model(np.zeros((1, self.state_size), dtype=np.float32), training=False)
        except (RuntimeError, ValueError, TypeError):
            pass

        # Compile a fast train_step with @tf.function (avoids Python overhead per fit call)
        self._loss_fn = tf.keras.losses.Huber()
        return model

    def _sync_target_hard(self):
        """Full weight copy (used at initialization)."""
        self.target_model.set_weights(self.model.get_weights())

    def _sync_target_soft(self):
        """Polyak averaging — vectorized with numpy for speed."""
        online_w = self.model.get_weights()
        target_w = self.target_model.get_weights()
        self.target_model.set_weights([
            self.tau * ow + (1.0 - self.tau) * tw
            for ow, tw in zip(online_w, target_w)
        ])

    def _make_n_step_transition(self, n):
        """Buduje n-step transition z pierwszych n elementów bufora.
        Zwraca (s_0, a_0, R_n, s_n, done_n, gamma_n_eff).
        Jeśli któryś krok jest done, truncate.
        """
        R = 0.0
        discount = 1.0
        next_state = None
        actual_done = False
        actual_n = n
        for k in range(n):
            _, _, r, ns, d = self.n_step_buffer[k]
            R += discount * r
            discount *= self.gamma
            next_state = ns
            if d:
                actual_done = True
                actual_n = k + 1
                break
        s0, a0, _, _, _ = self.n_step_buffer[0]
        gamma_n_eff = self.gamma ** actual_n
        return (s0, a0, R, next_state, actual_done, gamma_n_eff)

    def remember(self, state, action, reward, next_state, done):
        self.n_step_buffer.append((state, action, reward, next_state, done))

        if done:
            # Flush wszystkie pozostałe — każda pozycja generuje truncated n-step transition
            while len(self.n_step_buffer) > 0:
                n = len(self.n_step_buffer)
                self.memory.add(self._make_n_step_transition(n))
                self.n_step_buffer.popleft()
        elif len(self.n_step_buffer) >= self.n_step:
            # Bufor pełny — emituj transition dla najstarszego, popnij go
            self.memory.add(self._make_n_step_transition(self.n_step))
            self.n_step_buffer.popleft()

    def act(self, state):
        if np.random.rand() <= self.epsilon:
            return random.randrange(self.action_size)
        q = self.model(state.reshape(1, -1), training=False).numpy()[0]
        return np.argmax(q)

    def _train_on_batch(self, states, targets):
        """Single gradient step — compiled by TF, much faster than model.fit()."""
        import tensorflow as tf
        with tf.GradientTape() as tape:
            predictions = self.model(states, training=True)
            loss = self._loss_fn(targets, predictions)
        gradients = tape.gradient(loss, self.model.trainable_variables)
        self.model.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

    def _train_on_batch_weighted(self, states, targets, is_weights):
        """Gradient step weighted by importance-sampling weights (PER).
        Używa Huber loss per-sample — odporne na outliery (kluczowe dla PER,
        bo samplinguje doświadczenia z dużym TD-error)."""
        import tensorflow as tf
        weights = tf.constant(is_weights, dtype=tf.float32)
        with tf.GradientTape() as tape:
            predictions = self.model(states, training=True)
            # Per-sample Huber loss (delta=1.0): kwadratowy dla |x|<1, liniowy poza
            diff = targets - predictions
            abs_diff = tf.abs(diff)
            huber = tf.where(abs_diff < 1.0, 0.5 * tf.square(diff), abs_diff - 0.5)
            per_sample_loss = tf.reduce_mean(huber, axis=1)
            loss = tf.reduce_mean(weights * per_sample_loss)
        gradients = tape.gradient(loss, self.model.trainable_variables)
        self.model.optimizer.apply_gradients(zip(gradients, self.model.trainable_variables))

    def replay(self, batch_size=32):
        if len(self.memory) < batch_size:
            return

        effective_batch = min(get_tf_batch_size(batch_size, batch_size * 2), len(self.memory))

        # PER: sample by priority
        indices, minibatch, is_weights = self.memory.sample(effective_batch)
        if len(minibatch) == 0:
            return

        actual_batch = len(minibatch)
        # Backward compat: stare 5-tuples → traktuj jako 1-step (gamma_n_eff = self.gamma)
        normalized = []
        for exp in minibatch:
            if len(exp) == 5:
                s, a, r, ns, d = exp
                normalized.append((s, a, r, ns, d, self.gamma))
            else:
                normalized.append(exp)

        states     = np.array([s  for s, a, r, ns, d, gn in normalized], dtype=np.float32)
        next_states= np.array([ns for s, a, r, ns, d, gn in normalized], dtype=np.float32)
        rewards    = np.array([r  for s, a, r, ns, d, gn in normalized], dtype=np.float32)
        actions    = np.array([a  for s, a, r, ns, d, gn in normalized], dtype=np.int32)
        dones      = np.array([d  for s, a, r, ns, d, gn in normalized], dtype=bool)
        gamma_ns   = np.array([gn for s, a, r, ns, d, gn in normalized], dtype=np.float32)

        # Single batch forward for both models
        q_values      = self.model(states, training=False).numpy()
        q_next_online = self.model(next_states, training=False).numpy()
        q_next_target = self.target_model(next_states, training=False).numpy()

        # Vectorized Double-DQN target calculation z n-step gamma
        idx = np.arange(actual_batch)
        best_actions = np.argmax(q_next_online, axis=1)
        max_q_next   = q_next_target[idx, best_actions]
        targets      = rewards + gamma_ns * max_q_next * (~dones)

        # TD-errors for priority update
        td_errors = np.abs(targets - q_values[idx, actions])
        q_values[idx, actions] = targets

        # Weighted gradient step (IS-weights correct for sampling bias)
        self._train_on_batch_weighted(states, q_values, is_weights)

        # Update priorities in replay buffer
        self.memory.update_priorities(indices, td_errors)

        # Anneal beta toward 1.0
        self.memory.anneal_beta(self.train_step, 10000)

        self.train_step += 1

        # Soft target update every 4th replay
        if self.train_step % 4 == 0:
            self._sync_target_soft()

        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def update_lr(self, episode: int, total_episodes: int):
        """Cosine annealing LR schedule — decays LR smoothly over training."""
        import math
        progress = episode / max(total_episodes, 1)
        new_lr = self.lr_min + 0.5 * (self.lr_start - self.lr_min) * (1 + math.cos(math.pi * progress))
        self.model.optimizer.learning_rate.assign(new_lr)
    def save(self, path, data_hash=None):
        # Atomic save: write to tmp, then rename
        import time as _time
        base, ext = os.path.splitext(path)
        tmp_path = base + '.tmp' + ext
        self.model.save(tmp_path)
        os.replace(tmp_path, path)
        params_path = path + '.params'
        params_tmp = params_path + '.tmp'
        with open(params_tmp, 'wb') as f:
            pickle.dump({
                'epsilon': self.epsilon,
                'train_step': self.train_step,
                'memory': self.memory.to_list(),
                'memory_beta': self.memory.beta,
                'last_train_ts': _time.time(),
                'data_hash': data_hash,
            }, f)
        os.replace(params_tmp, params_path)

    def load(self, path):
        from tensorflow.keras.models import load_model
        self.model = load_model(path)
        self.target_model = load_model(path)
        self._sync_target_hard()
        with open(path+'.params', 'rb') as f:
            p = pickle.load(f)
            self.epsilon = p['epsilon']
            self.train_step = p.get('train_step', 0)
            self._last_train_ts = p.get('last_train_ts', 0)
            self._data_hash = p.get('data_hash', None)
            saved_memory = p.get('memory', [])
            if saved_memory:
                # Backward compat: old format was list of tuples (experiences)
                if isinstance(saved_memory[0], tuple) and len(saved_memory[0]) == 5:
                    # Old deque format — import as uniform priority
                    capacity = self.memory.maxlen
                    self.memory = PrioritizedReplayBuffer(capacity=capacity)
                    for exp in saved_memory:
                        self.memory.add(exp)
                else:
                    # New PER format — list of (priority, experience)
                    capacity = self.memory.maxlen
                    self.memory = PrioritizedReplayBuffer.from_list(
                        saved_memory, capacity=capacity)
                    self.memory.beta = p.get('memory_beta', 0.4)
                print(f"  📦 Wczytano replay buffer: {len(self.memory)} doświadczeń (PER)")

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
