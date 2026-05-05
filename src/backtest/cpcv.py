"""src/backtest/cpcv.py — Combinatorial Purged Cross-Validation.

2026-05-05: shipped per comparative research adoption (#7). Replaces
single-path walk-forward with N-choose-k splits + purging + embargo,
giving a *distribution* of backtest paths instead of one. Lower
Probability of Backtest Overfitting (PBO), better Sharpe confidence
intervals.

Reference: Lopez de Prado *Advances in Financial ML* §12.

Algorithm:
  1. Partition timeline into N equal groups (default 6)
  2. Form all C(N, k) combinations of k test groups (default k=2)
  3. For each combination:
     a. Test = those k groups
     b. Train = the remaining N-k groups MINUS purged windows around
        each test group (purge = label-horizon overlap protection)
        MINUS embargo bars (after each test group, prevent label leakage)
     c. Run backtest, record per-fold metrics
  4. Aggregate: mean, stdev, percentiles of Sharpe / PF / Return / DD
     across all C(N, k) paths.

For our 178-trade 1yr cohort, N=6/k=2 = 15 paths. Each path uses ~67%
data (4 of 6 groups) for train, 33% (2 groups) for test. Purge window
= label_horizon_bars (e.g., 24 for triple-barrier 24h horizon).

Usage:
    from src.backtest.cpcv import generate_cpcv_splits
    for fold_idx, (train_idx, test_idx) in enumerate(
        generate_cpcv_splits(n_samples=N, n_groups=6, k_test=2, purge=24, embargo=12)
    ):
        # Train on train_idx, test on test_idx
        ...
"""
from __future__ import annotations

import itertools
from typing import Iterator


def generate_cpcv_splits(
    n_samples: int,
    n_groups: int = 6,
    k_test: int = 2,
    purge: int = 0,
    embargo: int = 0,
) -> Iterator[tuple[list[int], list[int]]]:
    """Yield (train_indices, test_indices) for each CPCV combination.

    Args:
        n_samples: total bar count
        n_groups: partition timeline into N groups (default 6)
        k_test: how many groups form the test set per fold (default 2)
        purge: bars to exclude from train AROUND each test group
            (label-horizon protection — prevents label leakage when train
            label-horizon overlaps test data)
        embargo: bars to exclude from train AFTER each test group
            (Lopez de Prado convention; further reduces leakage)

    Yields C(n_groups, k_test) folds in deterministic order.
    """
    if n_samples < n_groups:
        return
    if k_test < 1 or k_test >= n_groups:
        raise ValueError(f"k_test must be in [1, n_groups-1], got {k_test}")

    # Partition into n_groups groups of equal size (last group may be larger)
    group_size = n_samples // n_groups
    group_bounds: list[tuple[int, int]] = []
    for g in range(n_groups):
        lo = g * group_size
        hi = (g + 1) * group_size if g < n_groups - 1 else n_samples
        group_bounds.append((lo, hi))

    all_indices = set(range(n_samples))

    for test_groups in itertools.combinations(range(n_groups), k_test):
        # Build test indices
        test_idx = []
        for g in test_groups:
            lo, hi = group_bounds[g]
            test_idx.extend(range(lo, hi))

        # Build train = all - test - purge - embargo
        excluded = set(test_idx)
        for g in test_groups:
            lo, hi = group_bounds[g]
            # Purge: bars BEFORE test group (where train label-horizon could overlap)
            purge_lo = max(0, lo - purge)
            excluded.update(range(purge_lo, lo))
            # Embargo: bars AFTER test group
            embargo_hi = min(n_samples, hi + embargo)
            excluded.update(range(hi, embargo_hi))

        train_idx = sorted(all_indices - excluded)
        yield train_idx, sorted(test_idx)


def n_paths(n_groups: int, k_test: int) -> int:
    """C(n_groups, k_test) — number of CPCV paths."""
    from math import comb
    return comb(n_groups, k_test)


def aggregate_metrics(per_fold: list[dict]) -> dict:
    """Aggregate per-fold metric dicts into mean/stdev/min/max."""
    if not per_fold:
        return {}
    keys = set()
    for f in per_fold:
        keys.update(f.keys())
    out: dict = {}
    for k in keys:
        vals = [f.get(k) for f in per_fold if isinstance(f.get(k), (int, float))]
        if not vals:
            continue
        n = len(vals)
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n if n > 1 else 0.0
        std = var ** 0.5
        out[k] = {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "n": n,
        }
    return out
