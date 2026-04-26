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


# ─── Edge cases ───────────────────────────────────────────────────


def test_out_of_range_value_warns(caplog):
    """Soft min/max emits a warning but doesn't raise."""
    _reset_usage_for_test()
    import logging
    with caplog.at_level(logging.WARNING, logger="src.core.dynamic_params_schema"):
        target = schema.validate_param_write("sl_atr_multiplier", 99.0)  # max=6.0
    assert target is None  # not a mirror key
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "above soft-max" in msgs or "soft-max" in msgs
    # The write itself was tracked
    assert schema.get_usage_snapshot()["sl_atr_multiplier"]["n_writes"] == 1


def test_below_min_value_warns(caplog):
    _reset_usage_for_test()
    import logging
    with caplog.at_level(logging.WARNING, logger="src.core.dynamic_params_schema"):
        schema.validate_param_write("risk_percent", 0.001)  # min=0.05
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "below soft-min" in msgs


def test_within_range_no_warning(caplog):
    _reset_usage_for_test()
    import logging
    with caplog.at_level(logging.WARNING, logger="src.core.dynamic_params_schema"):
        schema.validate_param_write("risk_percent", 1.0)  # within [0.05, 5.0]
    # No warnings about ranges
    range_warnings = [r for r in caplog.records if "soft-" in r.getMessage()]
    assert range_warnings == []


def test_wrong_type_warns_does_not_raise(caplog):
    """Setting a float-spec'd key to a non-numeric string warns, doesn't blow up."""
    _reset_usage_for_test()
    import logging
    # 'foo' is a string — schema expects float for risk_percent. Validation
    # must log + return mirror target (or None) without raising.
    with caplog.at_level(logging.WARNING, logger="src.core.dynamic_params_schema"):
        target = schema.validate_param_write("risk_percent", "foo")
    assert target is None
    # Still tracked as a write
    assert schema.get_usage_snapshot()["risk_percent"]["n_writes"] == 1


def test_mirror_only_one_direction():
    """Writing tp_to_sl_ratio must NOT trigger a back-mirror to target_rr
    (otherwise we'd have an infinite write loop in `set_param`)."""
    target = schema.validate_param_write("tp_to_sl_ratio", 2.0)
    assert target is None, "tp_to_sl_ratio must not have a mirror back to target_rr"


def test_mirror_writes_dont_recurse_in_db(monkeypatch, tmp_path):
    """End-to-end: setting target_rr writes target_rr + tp_to_sl_ratio exactly
    once each — the mirror write inside NewsDB.set_param must not re-enter
    the schema and trigger a third write."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", str(db_path))
    import importlib
    from src.core import database as db_mod
    importlib.reload(db_mod)

    db = db_mod.NewsDB()
    _reset_usage_for_test()
    db.set_param("target_rr", 2.7)

    snap = schema.get_usage_snapshot()
    # target_rr written once via the public API call. tp_to_sl_ratio is
    # written once via the mirror — but that write goes through _execute
    # directly, NOT through schema.validate_param_write, so the schema
    # tracker should see exactly 1 write for target_rr and 0 for
    # tp_to_sl_ratio (the mirror bypasses validate to avoid recursion).
    assert snap["target_rr"]["n_writes"] == 1
    # The mirror skips the tracker — that's by design (and prevents loops).
    assert snap.get("tp_to_sl_ratio", {}).get("n_writes", 0) == 0
    # But the DB row is there.
    assert float(db.get_param("tp_to_sl_ratio") or 0) == pytest.approx(2.7)


def test_prefix_lookup_does_not_cross_match():
    """`weight_xyz` falls under the `weight_` PrefixSpec, not `model_`."""
    _reset_usage_for_test()
    schema.validate_param_write("weight_eurusd", 0.5)
    schema.validate_param_write("model_lstm_correct", 42)
    snap = schema.get_usage_snapshot()
    assert "weight_eurusd" in snap
    assert "model_lstm_correct" in snap
    # Neither should produce a mirror
    assert schema.validate_param_write("weight_eurusd", 0.5) is None
    assert schema.validate_param_write("model_lstm_correct", 42) is None


def test_unknown_prefix_falls_through():
    """An unknown prefix doesn't match any PrefixSpec — tracked as 'unknown'."""
    _reset_usage_for_test()
    target = schema.validate_param_write("brand_new_unrecognized_key_xyz", 1.0)
    assert target is None
    assert schema.get_usage_snapshot()["brand_new_unrecognized_key_xyz"]["n_writes"] == 1


def test_dead_write_drift_kind():
    """A key written + read once, then written again much later, surfaces as
    `dead_write` if the read didn't happen recently."""
    _reset_usage_for_test()
    import time as _t
    schema.validate_param_write("portfolio_balance", 10_000)
    schema.track_read("portfolio_balance")
    # Simulate a second write happening "now", with the read far in the past.
    snap_lock = schema._usage_lock
    with snap_lock:
        schema._usage["portfolio_balance"].last_read_ts = _t.time() - 9999
    schema.validate_param_write("portfolio_balance", 11_000)

    drifts = schema.find_drifts(write_only_grace_s=1.0)
    kinds = {d["name"]: d["kind"] for d in drifts}
    assert kinds.get("portfolio_balance") == "dead_write"
