"""Tests for src/learning/meta_labeling.py."""
import numpy as np
import pytest

from src.learning.meta_labeling import (
    kelly_fraction, MetaLabeler, fit_meta_labeler,
    DEFAULT_KELLY_CAP, MIN_PROB_THRESHOLD,
)


# ── Kelly fraction ─────────────────────────────────────────────────────

def test_kelly_zero_edge_returns_zero():
    """p=0.5 with payoff 1.0 = no edge → f*=0."""
    assert kelly_fraction(0.5, payoff_ratio=1.0) == 0.0


def test_kelly_negative_edge_returns_zero():
    """p<0.5 with even payoff = negative edge."""
    assert kelly_fraction(0.4, payoff_ratio=1.0) == 0.0


def test_kelly_positive_edge_capped_at_half():
    """High p+payoff would give f*>1 but cap=0.5 (half-Kelly)."""
    f = kelly_fraction(0.9, payoff_ratio=3.0)
    assert f == DEFAULT_KELLY_CAP, f"Expected cap {DEFAULT_KELLY_CAP}, got {f}"


def test_kelly_realistic_edge():
    """p=0.55, payoff 2.0 → f*=(0.55*2-0.45)/2=0.325. Under cap → return as-is."""
    f = kelly_fraction(0.55, payoff_ratio=2.0)
    assert f == pytest.approx(0.325, rel=0.01)


def test_kelly_invalid_inputs():
    assert kelly_fraction(-0.1, 2.0) == 0.0
    assert kelly_fraction(1.5, 2.0) == 0.0
    assert kelly_fraction(0.6, 0) == 0.0


# ── MetaLabeler ────────────────────────────────────────────────────────

def test_meta_labeler_skip_below_threshold():
    """When predicted prob < min_threshold → skip=True."""
    class _Model:
        def predict_proba(self, x):
            return np.array([[0.7, 0.3]])  # P(profitable) = 0.3

    ml = MetaLabeler(model=_Model(), feature_names=["a", "b"])
    out = ml.size_trade(np.array([0.0, 0.0]))
    assert out["skip"] is True
    assert out["lot"] == 0.0


def test_meta_labeler_size_above_threshold():
    """When prob > threshold → calculates Kelly-based lot."""
    class _Model:
        def predict_proba(self, x):
            return np.array([[0.3, 0.7]])  # P(profitable) = 0.7

    ml = MetaLabeler(model=_Model(), feature_names=["a"], base_lot=0.01)
    out = ml.size_trade(np.array([0.0]), payoff_ratio=2.0)
    assert out["skip"] is False
    assert 0 < out["lot"] <= 0.01  # at most base_lot
    assert out["prob"] == pytest.approx(0.7, rel=0.01)


def test_meta_labeler_save_load_roundtrip(tmp_path):
    """Trained labeler survives pickle roundtrip."""
    rng = np.random.default_rng(0)
    X = rng.normal(0, 1, size=(200, 4))
    # Synthetic edge: positive class when sum(features) > 0
    y = (X.sum(axis=1) > 0).astype(int)
    ml = fit_meta_labeler(X, y, ["a", "b", "c", "d"])
    path = tmp_path / "ml.pkl"
    ml.save(path)
    loaded = MetaLabeler.load(path)
    assert loaded is not None
    # Same prediction on same input
    test_x = np.array([0.5, -0.5, 0.5, 0.0])
    assert ml.predict_proba(test_x) == pytest.approx(
        loaded.predict_proba(test_x), rel=0.001
    )


def test_meta_labeler_load_missing_returns_none(tmp_path):
    assert MetaLabeler.load(tmp_path / "no_such.pkl") is None


def test_fit_meta_labeler_calibrated():
    """Fitted classifier produces well-calibrated probabilities."""
    rng = np.random.default_rng(7)
    n = 500
    X = rng.normal(0, 1, size=(n, 3))
    # Easy task: y=1 iff first feature > 0
    y = (X[:, 0] > 0).astype(int)
    ml = fit_meta_labeler(X, y, ["x0", "x1", "x2"])
    # On clearly-positive sample, prob > 0.5
    pos_pred = ml.predict_proba(np.array([2.0, 0.0, 0.0]))
    neg_pred = ml.predict_proba(np.array([-2.0, 0.0, 0.0]))
    assert pos_pred > 0.6, f"Strong positive should predict >0.6, got {pos_pred}"
    assert neg_pred < 0.4, f"Strong negative should predict <0.4, got {neg_pred}"


def test_size_trade_lot_scales_with_prob():
    """Higher prob → larger lot (within cap)."""
    rng = np.random.default_rng(13)
    X = rng.normal(0, 1, size=(500, 3))
    y = (X[:, 0] > 0).astype(int)
    ml = fit_meta_labeler(X, y, ["x0", "x1", "x2"], base_lot=0.01,
                          min_prob_threshold=0.51)
    low = ml.size_trade(np.array([0.5, 0.0, 0.0]), payoff_ratio=2.0)
    high = ml.size_trade(np.array([3.0, 0.0, 0.0]), payoff_ratio=2.0)
    if not low["skip"] and not high["skip"]:
        assert high["lot"] >= low["lot"], (
            f"Higher confidence trade {high['prob']:.2f} should size >= "
            f"lower {low['prob']:.2f}, got lots {high['lot']} vs {low['lot']}"
        )
