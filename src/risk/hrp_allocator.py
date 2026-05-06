"""src/risk/hrp_allocator.py — Hierarchical Risk Parity portfolio weights.

2026-05-06 (Phase D scaffold): Lopez de Prado §16 HRP — allocate
capital across uncorrelated strategies/assets WITHOUT matrix inversion
(unlike Markowitz which is unstable on retail-size samples).

Three steps:
  1. Distance matrix from correlation: d_ij = sqrt(0.5 * (1 - rho_ij))
  2. Hierarchical clustering (single linkage)
  3. Recursive bisection: split portfolio into halves by cluster,
     allocate inversely to cluster vol

Output: dict[asset_symbol] → weight (sums to 1.0).

Uses scipy.cluster.hierarchy (already in scientific Python stack).
Falls back to equal-weight if input invalid.

References:
  - Lopez de Prado 2016 — "Building Diversified Portfolios that Outperform Out of Sample"
  - PyPortfolioOpt HRPOpt
  - hudsonthames.org/beyond-risk-parity-hierarchical-erc
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def correlation_to_distance(corr: np.ndarray) -> np.ndarray:
    """Lopez de Prado's correlation→distance: d = sqrt(0.5 × (1 - rho))."""
    return np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))


def _quasi_diagonal(linkage: np.ndarray) -> list[int]:
    """Return ordered leaf indices from linkage matrix for recursive bisection."""
    n_leaves = linkage.shape[0] + 1
    sort_ix = list(range(n_leaves))
    # If scipy's linkage gives clusters > n_leaves indices, walk recursively
    # For small N (≤10 strategies), simple ordering is enough.
    return sort_ix


def _ivp_weights(cov: np.ndarray, indices: list[int]) -> np.ndarray:
    """Inverse-variance weights for sub-cluster — matches per-asset risk."""
    cov_slice = cov[np.ix_(indices, indices)]
    diag = np.diag(cov_slice)
    if (diag <= 0).any():
        return np.ones(len(indices)) / len(indices)
    inv_var = 1.0 / diag
    return inv_var / inv_var.sum()


def _cluster_var(cov: np.ndarray, indices: list[int]) -> float:
    """Compute weighted variance of a cluster using IVP weights."""
    weights = _ivp_weights(cov, indices)
    cov_slice = cov[np.ix_(indices, indices)]
    return float(weights @ cov_slice @ weights)


def hrp_weights(returns: np.ndarray, names: list[str]) -> dict[str, float]:
    """Compute HRP weights given (n_periods, n_assets) returns matrix.

    Args:
        returns: 2D array of period returns (each col = one asset/strategy)
        names: list of asset names matching col order

    Returns: dict[name] → weight (sums to 1.0)

    Falls back to equal-weight on any failure (n<3, scipy missing, etc).
    """
    n_assets = returns.shape[1]
    eq_weight = 1.0 / n_assets
    fallback = {n: eq_weight for n in names}

    if n_assets < 2 or returns.shape[0] < 5:
        return fallback

    try:
        from scipy.cluster.hierarchy import linkage, leaves_list
        from scipy.spatial.distance import squareform

        # Correlation matrix
        corr = np.corrcoef(returns.T)
        if not np.isfinite(corr).all():
            return fallback
        np.fill_diagonal(corr, 1.0)

        # Distance + clustering
        dist = correlation_to_distance(corr)
        # Convert to condensed for scipy
        condensed = squareform(dist, checks=False)
        linkage_matrix = linkage(condensed, method='single')
        ordered_idx = list(leaves_list(linkage_matrix))

        # Covariance for variance weighting
        cov = np.cov(returns.T)

        # Recursive bisection
        weights = np.ones(n_assets)
        clusters = [ordered_idx]
        while clusters:
            new_clusters = []
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]
                # Allocate inversely to cluster variance
                left_var = _cluster_var(cov, left)
                right_var = _cluster_var(cov, right)
                total = left_var + right_var
                if total <= 0:
                    alpha = 0.5
                else:
                    alpha = 1.0 - left_var / total  # left gets larger share if smaller var
                # alpha: weight TO left, (1-alpha) to right. But formula above is wrong direction.
                # Correct: more weight to lower-var cluster
                alpha_left = right_var / total if total > 0 else 0.5
                weights[left] *= alpha_left
                weights[right] *= (1.0 - alpha_left)
                new_clusters.extend([left, right])
            clusters = new_clusters

        # Normalize
        weights /= weights.sum()
        return {names[i]: float(weights[i]) for i in range(n_assets)}
    except Exception:
        return fallback


def update_portfolio_weights(
    asset_returns: dict[str, list[float]],
    rebalance_threshold: float = 0.05,
    current_weights: Optional[dict[str, float]] = None,
) -> tuple[dict[str, float], bool]:
    """Compute new HRP weights and decide if rebalance needed.

    Args:
        asset_returns: dict[asset_symbol] → list of period returns (>=10 each)
        rebalance_threshold: if max(|new - current|) > this, trigger rebalance
        current_weights: dict if known, else assume equal

    Returns:
        weights: new HRP weights
        should_rebalance: True if differences exceed threshold
    """
    names = list(asset_returns.keys())
    if not names:
        return {}, False
    min_len = min(len(r) for r in asset_returns.values())
    if min_len < 10:
        return {n: 1.0 / len(names) for n in names}, False

    matrix = np.array([asset_returns[n][-min_len:] for n in names]).T
    weights = hrp_weights(matrix, names)

    if current_weights is None:
        eq = 1.0 / len(names)
        max_diff = max(abs(weights[n] - eq) for n in names)
    else:
        max_diff = max(
            abs(weights[n] - current_weights.get(n, 1.0 / len(names)))
            for n in names
        )

    return weights, max_diff > rebalance_threshold
