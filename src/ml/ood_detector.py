"""src/ml/ood_detector.py — Dissimilarity Index out-of-distribution detector.

2026-05-05: shipped per comparative research adoption (#3) — closes the
gap where PSI gives offline drift but per-prediction OOD rejection is
absent. Pattern from Freqtrade FreqAI: at inference, compute distance
from current feature vector to training-set centroid; refuse the trade
if distance exceeds a percentile threshold of training distances.

Why this beats PSI alone:
- PSI is a population-level metric (computed on rolling windows). OOD
  individual ticks can hide inside an in-distribution window.
- DI is per-tick: catches one-off feature outliers (e.g., NFP tick
  with unusual ATR + RSI combo) before the trade is opened.
- Pairs with our existing kill-switch — DI rejection is the *first*
  line, kill-switch the *last*. Refuse the OOD trade up-front instead
  of waiting 8 losses.

Distance metric: Mahalanobis (accounts for feature correlation +
variance — better than Euclidean which overweights high-variance
features). Threshold: 99th percentile of training distances.

Usage:
    from src.ml.ood_detector import OODDetector
    detector = OODDetector.load_or_fit()  # cached on disk
    ood, score = detector.is_ood(feature_vector)
    if ood:
        # log + reject the trade
        ...
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None  # only needed during fit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PKL = ROOT / "models" / "ood_detector.pkl"
DEFAULT_FEATURES_CSV = ROOT / "data" / "training_features.csv"


class OODDetector:
    """Mahalanobis-distance based out-of-distribution detector.

    fit_method='mahalanobis' (default) computes
        d²(x) = (x - μ)ᵀ Σ⁻¹ (x - μ)

    where μ, Σ are training-set mean + covariance. At threshold the 99th
    percentile of training distances is stored — anything beyond ⇒ OOD.
    """

    def __init__(self, mean: np.ndarray, inv_cov: np.ndarray,
                 threshold: float, feature_names: list[str]):
        self.mean = mean
        self.inv_cov = inv_cov
        self.threshold = threshold
        self.feature_names = feature_names

    def distance(self, x: np.ndarray) -> float:
        """Mahalanobis distance² (squared distance — convention for thresholding)."""
        diff = np.asarray(x, dtype=np.float64) - self.mean
        d2 = diff @ self.inv_cov @ diff
        return float(d2)

    def is_ood(self, x: np.ndarray) -> tuple[bool, float]:
        """Return (is_ood, distance_squared)."""
        d = self.distance(x)
        return (d > self.threshold), d

    # ── Persistence ─────────────────────────────────────────────────

    def save(self, path: Path = DEFAULT_PKL) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({
                "mean": self.mean,
                "inv_cov": self.inv_cov,
                "threshold": self.threshold,
                "feature_names": self.feature_names,
                "fit_method": "mahalanobis",
                "version": 1,
            }, f)

    @classmethod
    def load(cls, path: Path = DEFAULT_PKL) -> Optional["OODDetector"]:
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
            return cls(
                mean=data["mean"],
                inv_cov=data["inv_cov"],
                threshold=data["threshold"],
                feature_names=data["feature_names"],
            )
        except Exception:
            return None

    @classmethod
    def fit(cls, X: np.ndarray, feature_names: list[str],
            quantile: float = 0.99,
            ridge: float = 1e-4) -> "OODDetector":
        """Fit detector from training feature matrix.

        Args:
            X: (n_samples, n_features) training feature matrix
            feature_names: column names matching X columns
            quantile: 0.99 default — 99th percentile training distance
                becomes the OOD threshold
            ridge: numerical stabilizer added to cov diagonal before inverting
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim != 2:
            raise ValueError(f"X must be 2D, got {X.shape}")
        mean = X.mean(axis=0)
        cov = np.cov(X.T) + ridge * np.eye(X.shape[1])
        inv_cov = np.linalg.pinv(cov)

        # Compute training distances to set threshold
        diffs = X - mean
        d2 = np.einsum("ij,jk,ik->i", diffs, inv_cov, diffs)
        threshold = float(np.quantile(d2, quantile))

        return cls(mean=mean, inv_cov=inv_cov, threshold=threshold,
                   feature_names=feature_names)

    @classmethod
    def load_or_fit(cls, path: Path = DEFAULT_PKL,
                    features_csv: Path = DEFAULT_FEATURES_CSV) -> Optional["OODDetector"]:
        """Try to load cached detector; if absent and training CSV exists,
        fit + cache. If neither: return None (caller skips OOD check)."""
        det = cls.load(path)
        if det is not None:
            return det
        if not features_csv.exists() or pd is None:
            return None
        df = pd.read_csv(features_csv)
        from src.analysis.compute import FEATURE_COLS
        feat_cols = [c for c in FEATURE_COLS if c in df.columns]
        if not feat_cols:
            return None
        X = df[feat_cols].dropna().values
        if len(X) < 100:  # too few samples to fit reliably
            return None
        det = cls.fit(X, feat_cols)
        det.save(path)
        return det


# ── Module-level convenience for inference path ────────────────────

_cached_detector: Optional[OODDetector] = None


def get_detector() -> Optional[OODDetector]:
    """Lazily load and cache the OOD detector. Thread-safe enough for
    single-writer scanner; returns None if not yet fit."""
    global _cached_detector
    if _cached_detector is None:
        _cached_detector = OODDetector.load(DEFAULT_PKL)
    return _cached_detector


def reset_cache() -> None:
    """Forces reload on next get_detector() call (for tests)."""
    global _cached_detector
    _cached_detector = None


def cli_fit():
    """Operator entry point: fit detector from current training data."""
    if pd is None:
        print("ERROR: pandas required for CLI fit", flush=True)
        return 1
    if not DEFAULT_FEATURES_CSV.exists():
        print(f"ERROR: {DEFAULT_FEATURES_CSV} not found. Run training first.")
        return 1
    df = pd.read_csv(DEFAULT_FEATURES_CSV)
    from src.analysis.compute import FEATURE_COLS
    feat_cols = [c for c in FEATURE_COLS if c in df.columns]
    X = df[feat_cols].dropna().values
    print(f"[ood] fitting on {len(X)} rows × {len(feat_cols)} features")
    det = OODDetector.fit(X, feat_cols)
    det.save(DEFAULT_PKL)
    print(f"[ood] threshold (99th pct distance²): {det.threshold:.2f}")
    print(f"[ood] saved to {DEFAULT_PKL}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(cli_fit())
