"""src/analysis/fracdiff.py — fractional differentiation features.

2026-05-05: shipped per comparative research adoption (#5). Standard
returns (d=1) destroy long-memory autocorrelation in price series.
Fractional differentiation at d ∈ (0, 1) preserves memory while
achieving stationarity — Lopez de Prado *Advances in Financial ML*
chapter 5.

Algorithm (binomial weights, fixed-window):

    weight_k = (-1)^k × C(d, k)
    fracdiff_t = Σ_{k=0..K-1} weight_k × x_{t-k}

where K is the truncation window (default 20). Weights are bounded so
distant lags get exponentially smaller contributions — keeps long-memory
without leaking information from very far past.

NOT yet wired into FEATURE_COLS — that requires retraining all voters
on the expanded feature set. This module exposes the computation; when
operator retrains, opt-in via train_all.py --use-fracdiff.

Reference:
- Lopez de Prado *Advances in Financial Machine Learning* §5.4-5.5
- mlfinlab `frac_diff_ffd` (https://www.mlfinlab.com/en/latest/feature_engineering/frac_diff.html)
"""
from __future__ import annotations

import numpy as np


def fracdiff_weights(d: float, K: int = 20) -> np.ndarray:
    """Binomial weights for fractional differentiation order d.

    Returns array of length K with w[0]=1.0, w[k] = w[k-1] × (k-1-d)/k.
    """
    if K <= 0:
        return np.array([])
    weights = np.zeros(K, dtype=np.float64)
    weights[0] = 1.0
    for k in range(1, K):
        weights[k] = weights[k-1] * (k - 1 - d) / k
    return weights


def fracdiff_series(x: np.ndarray, d: float = 0.4, K: int = 20) -> np.ndarray:
    """Apply fractional differentiation to a 1D series.

    Args:
        x: input series (numpy 1D)
        d: differentiation order, typically 0.3-0.5 for financial returns
        K: truncation window — first K-1 outputs are NaN

    Returns:
        Same length as x, first K-1 values NaN.
    """
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n == 0:
        return x
    weights = fracdiff_weights(d, K)
    out = np.full(n, np.nan)
    for t in range(K - 1, n):
        # Sum of weighted lags x_{t}, x_{t-1}, ..., x_{t-K+1}
        lags = x[t - K + 1: t + 1][::-1]  # reversed so weights[0]·x_t, weights[1]·x_{t-1}, ...
        out[t] = float(np.dot(weights, lags))
    return out


def find_min_d(x: np.ndarray, K: int = 20,
               adf_pvalue_threshold: float = 0.05,
               candidates: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7)) -> float:
    """Find the minimum d such that fracdiff(x, d) passes ADF stationarity.

    Lopez de Prado's recipe — pick the smallest d that achieves stationarity
    so we preserve as much long-memory as possible.

    Returns the d, or 1.0 if none of the candidates pass.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        # statsmodels not available — fall back to a sensible default
        return 0.4

    for d in candidates:
        diff = fracdiff_series(x, d=d, K=K)
        diff_clean = diff[~np.isnan(diff)]
        if len(diff_clean) < 30:
            continue
        try:
            p = adfuller(diff_clean, autolag="AIC")[1]
            if p < adf_pvalue_threshold:
                return d
        except Exception:
            continue
    return 1.0


def add_fracdiff_features(df, columns: tuple[str, ...] = ("close", "usdjpy_close"),
                          d: float = 0.4, K: int = 20):
    """Add fracdiff_<col> column for each column in `columns`.

    Mutates df in-place AND returns it (pandas convention). Skips columns
    not present.
    """
    for col in columns:
        if col not in df.columns:
            continue
        df[f"fracdiff_{col}"] = fracdiff_series(df[col].values, d=d, K=K)
    return df
