"""
bayesian_opt.py — optymalizacja bayesowska parametrów.
"""

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C
import warnings
import pickle
import os
from src.core.logger import logger

class BayesianOptimizer:
    def __init__(self, bounds, objective, n_init=5, n_iter=20):
        self.bounds = bounds
        self.objective = objective
        self.n_init = n_init
        self.n_iter = n_iter
        self.X = []
        self.y = []
        self.gp = None
    def _sample_random(self):
        return {name: np.random.uniform(low, high) for name, (low, high) in self.bounds.items()}
    def _dict_to_array(self, d):
        return np.array([d[name] for name in self.bounds.keys()])
    def optimize(self):
        for _ in range(self.n_init):
            params = self._sample_random()
            score = self.objective(params)
            self.X.append(self._dict_to_array(params))
            self.y.append(score)
            logger.info(f"Bayes init: {params} -> {score:.4f}")
        kernel = C(1.0, (1e-3, 1e3)) * RBF(1.0, (1e-3, 1e3))
        for i in range(self.n_iter):
            X = np.array(self.X)
            y = np.array(self.y)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.gp = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=10, alpha=1e-6)
                self.gp.fit(X, y)
            best = self._propose_next()
            score = self.objective(best)
            self.X.append(self._dict_to_array(best))
            self.y.append(score)
            logger.info(f"Bayes iter {i+1}: {best} -> {score:.4f}")
        best_idx = np.argmax(self.y)
        best_params = {name: self.X[best_idx][i] for i, name in enumerate(self.bounds.keys())}
        return best_params, self.y[best_idx]
    def _propose_next(self):
        n_candidates = 1000
        candidates = [self._sample_random() for _ in range(n_candidates)]
        X_candidates = np.array([self._dict_to_array(c) for c in candidates])
        mu, sigma = self.gp.predict(X_candidates, return_std=True)
        ucb = mu + 1.96 * sigma
        return candidates[np.argmax(ucb)]