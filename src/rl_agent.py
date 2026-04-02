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
    def __init__(self, data, initial_balance=10000, transaction_cost=0.001):
        self.data = data
        self.initial_balance = initial_balance
        self.transaction_cost = transaction_cost
        self.reset()
    def reset(self):
        self.balance = self.initial_balance
        self.position = 0
        self.index = 0
        self.done = False
        return self._state()
    def _state(self):
        window = self.data['close'].iloc[max(0, self.index - 19):self.index + 1].values
        if len(window) < 20:
            window = np.pad(window, (20-len(window),0), 'constant')
        return np.concatenate([window, [self.balance/self.initial_balance, self.position]])
    def step(self, action):
        if self.index >= len(self.data)-1:
            self.done = True
            return self._state(), 0, self.done, {}
        price = self.data['close'].iloc[self.index]
        next_price = self.data['close'].iloc[self.index+1]
        change = (next_price - price) / price
        if action == 1 and self.position == 0:  # buy
            self.position = 1
            self.balance -= self.transaction_cost * price
        elif action == 2 and self.position == 0:  # short
            self.position = -1
            self.balance -= self.transaction_cost * price
        reward = change if self.position == 1 else (-change if self.position == -1 else 0)
        self.balance += reward * price
        self.index += 1
        if self.index >= len(self.data)-1:
            self.done = True
        return self._state(), reward, self.done, {}

class DQNAgent:
    def __init__(self, state_size, action_size=3, lr=0.001, gamma=0.95, epsilon=1.0, epsilon_min=0.01, epsilon_decay=0.995):
        self.state_size = state_size
        self.action_size = action_size
        self.memory = deque(maxlen=2000)
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.model = self._build(lr)
    def _build(self, lr):
        model = Sequential([
            Dense(24, input_dim=self.state_size, activation='relu'),
            Dense(24, activation='relu'),
            Dense(self.action_size, activation='linear')
        ])
        model.compile(loss='mse', optimizer=Adam(learning_rate=lr))
        return model
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
        for state, action, reward, next_state, done in minibatch:
            target = reward
            if not done:
                target += self.gamma * np.amax(self.model.predict(next_state.reshape(1,-1), verbose=0)[0])
            target_f = self.model.predict(state.reshape(1,-1), verbose=0)
            target_f[0][action] = target
            self.model.fit(state.reshape(1,-1), target_f, epochs=1, verbose=0)
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