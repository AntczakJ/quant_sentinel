"""Tests for src/ml/ood_detector.py."""
import numpy as np
import pytest

from src.ml.ood_detector import OODDetector


def test_fit_in_distribution_below_threshold():
    """Sample from training distribution → not OOD."""
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, size=(1000, 5))
    det = OODDetector.fit(X, [f"f{i}" for i in range(5)])
    # Sample from same dist → should NOT trigger OOD
    in_sample = X[0]
    ood, d = det.is_ood(in_sample)
    assert not ood, f"In-sample point flagged OOD (d²={d:.2f}, thr={det.threshold:.2f})"


def test_fit_extreme_outlier_above_threshold():
    """Extreme outlier far from mean → OOD."""
    rng = np.random.default_rng(42)
    X = rng.normal(0, 1, size=(1000, 5))
    det = OODDetector.fit(X, [f"f{i}" for i in range(5)])
    # 10σ outlier
    outlier = np.full(5, 10.0)
    ood, d = det.is_ood(outlier)
    assert ood, f"10σ outlier NOT flagged OOD (d²={d:.2f}, thr={det.threshold:.2f})"


def test_threshold_is_quantile():
    """Threshold = 99th pct of training distances."""
    rng = np.random.default_rng(7)
    X = rng.normal(0, 1, size=(2000, 8))
    det = OODDetector.fit(X, [f"f{i}" for i in range(8)], quantile=0.99)

    distances = []
    for x in X:
        distances.append(det.distance(x))
    train_99 = np.quantile(distances, 0.99)
    # Threshold matches the quantile within numeric noise
    assert abs(det.threshold - train_99) < 1.0


def test_save_load_roundtrip(tmp_path):
    rng = np.random.default_rng(13)
    X = rng.normal(0, 1, size=(500, 4))
    det = OODDetector.fit(X, ["a", "b", "c", "d"])
    path = tmp_path / "det.pkl"
    det.save(path)

    loaded = OODDetector.load(path)
    assert loaded is not None
    np.testing.assert_array_almost_equal(loaded.mean, det.mean)
    np.testing.assert_array_almost_equal(loaded.inv_cov, det.inv_cov)
    assert loaded.threshold == det.threshold
    assert loaded.feature_names == det.feature_names

    # Same prediction on same input
    test_x = np.array([0.5, -1.0, 0.2, 0.0])
    assert det.distance(test_x) == loaded.distance(test_x)


def test_load_missing_returns_none(tmp_path):
    """Load on non-existent path returns None (not raise)."""
    assert OODDetector.load(tmp_path / "does_not_exist.pkl") is None


def test_handles_correlated_features():
    """Mahalanobis should down-weight correlated features."""
    rng = np.random.default_rng(99)
    # Two strongly correlated features + one independent
    base = rng.normal(0, 1, 1000)
    X = np.column_stack([base, base + 0.01 * rng.normal(0, 1, 1000),
                         rng.normal(0, 1, 1000)])
    det = OODDetector.fit(X, ["a", "b", "c"])
    # Point (1, 1, 0) — consistent with the correlation. Should be IN.
    in_consistent = np.array([1.0, 1.0, 0.0])
    ood_a, d_a = det.is_ood(in_consistent)
    # Point (1, -1, 0) — INCONSISTENT with correlation. Should be OOD.
    in_inconsistent = np.array([1.0, -1.0, 0.0])
    ood_b, d_b = det.is_ood(in_inconsistent)
    # Inconsistent should have higher distance than consistent
    assert d_b > d_a, f"Inconsistent (d={d_b:.2f}) should be > consistent (d={d_a:.2f})"
