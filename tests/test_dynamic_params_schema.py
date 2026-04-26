"""
Test the dynamic_params schema layer:
  - validate_param_write returns the mirror target for `target_rr`
  - track_read bumps the read counter
  - find_drifts identifies write-only and read-only keys
  - NewsDB.set_param actually mirrors target_rr → tp_to_sl_ratio in DB

Runs in-process with the in-memory SQLite path. No network.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from src.core import dynamic_params_schema as schema


def _reset_usage_for_test():
    """Clear the in-process usage map between tests."""
    with schema._usage_lock:
        schema._usage.clear()


def test_target_rr_returns_tp_to_sl_ratio_as_mirror():
    _reset_usage_for_test()
    target = schema.validate_param_write("target_rr", 2.5)
    assert target == "tp_to_sl_ratio"


def test_unrelated_key_has_no_mirror():
    _reset_usage_for_test()
    target = schema.validate_param_write("portfolio_balance", 10000.0)
    assert target is None


def test_unknown_key_falls_through_silently():
    _reset_usage_for_test()
    # Should not raise even for unknown keys
    target = schema.validate_param_write("totally_made_up_key", "whatever")
    assert target is None
    snap = schema.get_usage_snapshot()
    assert snap["totally_made_up_key"]["n_writes"] == 1


def test_track_read_increments_counter():
    _reset_usage_for_test()
    schema.track_read("portfolio_balance")
    schema.track_read("portfolio_balance")
    snap = schema.get_usage_snapshot()
    assert snap["portfolio_balance"]["n_reads"] == 2
    assert snap["portfolio_balance"]["n_writes"] == 0


def test_find_drifts_identifies_write_only():
    _reset_usage_for_test()
    schema.validate_param_write("xgb_feature_count", 31)  # only writer
    schema.track_read("portfolio_balance")  # only reader
    drifts = schema.find_drifts()
    by_kind = {d["kind"]: d for d in drifts}
    assert "xgb_feature_count" in [d["name"] for d in drifts if d["kind"] == "write_only"]
    assert "portfolio_balance" in [d["name"] for d in drifts if d["kind"] == "read_only"]


def test_known_keys_includes_critical_pair():
    keys = set(schema.known_keys())
    assert "target_rr" in keys
    assert "tp_to_sl_ratio" in keys


def test_mirror_targets_contains_target_rr():
    mirrors = schema.mirror_targets()
    assert mirrors.get("target_rr") == "tp_to_sl_ratio"


def test_prefix_lookup_for_ensemble_weight():
    _reset_usage_for_test()
    target = schema.validate_param_write("ensemble_weight_xgb", 0.25)
    assert target is None  # no mirror for prefix keys
    snap = schema.get_usage_snapshot()
    assert snap["ensemble_weight_xgb"]["n_writes"] == 1


def test_db_set_param_auto_mirrors_target_rr(monkeypatch, tmp_path):
    """End-to-end: writing target_rr through NewsDB also writes tp_to_sl_ratio."""
    # Point the DB at a temp file so we don't touch sentinel.db
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))

    # Re-import to pick up DATABASE_URL
    import importlib
    from src.core import database as db_mod
    importlib.reload(db_mod)

    db = db_mod.NewsDB()
    db.set_param("target_rr", 2.7)

    # Both keys should now exist with the same value
    assert float(db.get_param("target_rr") or 0) == pytest.approx(2.7)
    assert float(db.get_param("tp_to_sl_ratio") or 0) == pytest.approx(2.7)


def test_db_set_param_no_mirror_for_independent_key(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import importlib
    from src.core import database as db_mod
    importlib.reload(db_mod)

    db = db_mod.NewsDB()
    db.set_param("portfolio_balance", 12345.6)

    # tp_to_sl_ratio shouldn't be touched
    assert db.get_param("tp_to_sl_ratio") is None
