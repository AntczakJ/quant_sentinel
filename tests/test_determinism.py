"""Smoke tests verifying determinism setup is in place for backtest."""
import importlib
import os
import sys
from pathlib import Path


def test_pythonhashseed_set_in_backtest_module():
    """run_production_backtest.py must set PYTHONHASHSEED before any model load."""
    src = Path(__file__).parent.parent / "run_production_backtest.py"
    text = src.read_text(encoding="utf-8")
    assert 'PYTHONHASHSEED' in text, \
        "PYTHONHASHSEED must be set in run_production_backtest.py"
    assert 'TF_DETERMINISTIC_OPS' in text, \
        "TF_DETERMINISTIC_OPS must be set in run_production_backtest.py"
    assert 'TF_CUDNN_DETERMINISTIC' in text, \
        "TF_CUDNN_DETERMINISTIC must be set in run_production_backtest.py"


def test_seed_calls_present():
    """random/numpy/tensorflow seeds must be called."""
    src = Path(__file__).parent.parent / "run_production_backtest.py"
    text = src.read_text(encoding="utf-8")
    assert 'random' in text and 'seed(42)' in text, "random.seed(42) missing"
    assert 'np.random.seed' in text or 'np_seed_mod.random.seed' in text, \
        "np.random.seed missing"


def test_seeds_set_before_imports():
    """Seeds must be set BEFORE any model code is imported.

    Easy check: the seed setup must come before STEP 2 imports.
    """
    src = Path(__file__).parent.parent / "run_production_backtest.py"
    text = src.read_text(encoding="utf-8")
    seed_idx = text.find("PYTHONHASHSEED")
    step2_idx = text.find("STEP 2:")
    assert seed_idx > 0 and step2_idx > 0
    assert seed_idx < step2_idx, \
        "Seeds must be set BEFORE 'STEP 2: imports' to take effect on TF/etc"
