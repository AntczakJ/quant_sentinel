"""Tests for src/backtest/cpcv.py."""
import pytest

from src.backtest.cpcv import (
    generate_cpcv_splits, n_paths, aggregate_metrics,
)


def test_n_paths_basic():
    """C(6, 2) = 15."""
    assert n_paths(6, 2) == 15
    assert n_paths(4, 1) == 4
    assert n_paths(10, 3) == 120


def test_splits_count_matches_combinations():
    splits = list(generate_cpcv_splits(n_samples=600, n_groups=6, k_test=2))
    assert len(splits) == 15  # C(6, 2)


def test_train_test_disjoint():
    """No bar should appear in both train and test."""
    for train, test in generate_cpcv_splits(n_samples=600, n_groups=6, k_test=2):
        intersection = set(train) & set(test)
        assert len(intersection) == 0, f"Bars in both: {sorted(intersection)[:5]}"


def test_test_size_is_k_groups():
    """Test set should be ~k_test/n_groups of total."""
    n = 600
    for train, test in generate_cpcv_splits(n_samples=n, n_groups=6, k_test=2):
        assert len(test) == n // 6 * 2


def test_purge_excludes_pre_test_bars_from_train():
    """With purge=10, bars [test_lo - 10, test_lo) excluded from train."""
    splits = list(generate_cpcv_splits(n_samples=600, n_groups=6, k_test=1, purge=10))
    # First fold: test = group 0 = [0, 100). Purge has nothing to remove (already at 0).
    # Second fold: test = group 1 = [100, 200). Purge removes [90, 100) from train.
    train1, test1 = splits[1]
    assert 89 in train1   # outside purge zone
    assert 90 not in train1  # in purge zone
    assert 100 not in train1  # in test (definitely not train)


def test_embargo_excludes_post_test_bars_from_train():
    splits = list(generate_cpcv_splits(n_samples=600, n_groups=6, k_test=1,
                                       purge=0, embargo=10))
    # Test group 0 = [0, 100). Embargo: [100, 110) excluded from train.
    train0, test0 = splits[0]
    assert 109 not in train0  # in embargo zone
    assert 110 in train0      # outside embargo


def test_no_overlap_with_other_test_groups():
    """A test group from one fold should still be in train of another fold."""
    splits = list(generate_cpcv_splits(n_samples=600, n_groups=6, k_test=2))
    # Fold 0: test = groups (0, 1) = [0, 200). Group 5 is fully in train.
    train0, test0 = splits[0]
    assert all(b in train0 for b in range(500, 600))


def test_invalid_k_raises():
    with pytest.raises(ValueError):
        list(generate_cpcv_splits(n_samples=100, n_groups=6, k_test=0))
    with pytest.raises(ValueError):
        list(generate_cpcv_splits(n_samples=100, n_groups=6, k_test=6))


def test_aggregate_metrics_basic():
    folds = [
        {"sharpe": 1.0, "pf": 1.5},
        {"sharpe": 2.0, "pf": 2.0},
        {"sharpe": 3.0, "pf": 1.0},
    ]
    out = aggregate_metrics(folds)
    assert out["sharpe"]["mean"] == 2.0
    assert out["sharpe"]["min"] == 1.0
    assert out["sharpe"]["max"] == 3.0
    assert out["sharpe"]["n"] == 3
    assert out["pf"]["mean"] == 1.5


def test_aggregate_metrics_empty():
    assert aggregate_metrics([]) == {}
