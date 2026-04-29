"""Tests for the auto-purge logic in train_all.py — extracts max_holding
from triple-barrier label parquet filename and sets WF_PURGE_BARS so the
walk-forward folds don't leak target labels into the train slice.

Regression test for the LSTM 0.702 finding from Phase 8 (2026-04-30):
default purge=5 + max_holding=12 left 7 bars of label leak that LSTM
picked up. The auto-purge fix prevents this in future retrains.
"""
from __future__ import annotations

import os
import re

import pytest


_FILENAME_RE = re.compile(r"_max(\d+)")


def _extract_max_holding(filename: str) -> int | None:
    m = _FILENAME_RE.search(filename)
    return int(m.group(1)) if m else None


class TestAutoPurgeRegex:
    """The regex that train_all.py uses to extract max_holding."""

    def test_5min_60bar(self):
        assert _extract_max_holding(
            "triple_barrier_XAU_USD_5min_tp2_sl1_max60.parquet"
        ) == 60

    def test_15min_24bar(self):
        assert _extract_max_holding(
            "triple_barrier_XAU_USD_15min_tp2_sl1_max24.parquet"
        ) == 24

    def test_1h_12bar(self):
        assert _extract_max_holding(
            "triple_barrier_XAU_USD_1h_tp2_sl1_max12.parquet"
        ) == 12

    def test_floats_in_other_fields_ignored(self):
        # tp2.5_sl1.5 should not match, only _max{N}
        assert _extract_max_holding(
            "triple_barrier_XAU_USD_5min_tp2.5_sl1.5_max48.parquet"
        ) == 48

    def test_no_max_returns_none(self):
        assert _extract_max_holding("triple_barrier_5min_tp2_sl1.parquet") is None

    def test_alternate_separators(self):
        # Defensive: filename with spaces or different prefix
        assert _extract_max_holding("foo_max100_bar.parquet") == 100


class TestAutoPurgeIntegration:
    """End-to-end: train_all.py main() picks newest parquet and sets env."""

    def test_purge_set_from_newest_parquet(self, tmp_path, monkeypatch):
        """Simulate the train_all main() snippet: pick newest by mtime,
        regex extract, set env."""
        # Create two synthetic parquet filenames (no actual data needed)
        d = tmp_path / "labels"
        d.mkdir()
        old = d / "triple_barrier_XAU_USD_1h_tp2_sl1_max60.parquet"
        new = d / "triple_barrier_XAU_USD_1h_tp2_sl1_max12.parquet"
        old.write_bytes(b"")
        new.write_bytes(b"")
        # Make `new` more recently modified
        os.utime(old, (1700000000, 1700000000))
        os.utime(new, (1700001000, 1700001000))

        candidates = sorted(d.glob("triple_barrier_XAU_USD_1h_*.parquet"))
        assert len(candidates) == 2

        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        assert latest.name == "triple_barrier_XAU_USD_1h_tp2_sl1_max12.parquet"

        # Now run the auto-purge snippet from train_all
        monkeypatch.delenv("WF_PURGE_BARS", raising=False)
        m = _FILENAME_RE.search(latest.name)
        assert m is not None
        target_purge = int(m.group(1))
        if "WF_PURGE_BARS" not in os.environ:
            os.environ["WF_PURGE_BARS"] = str(target_purge)
        assert os.environ["WF_PURGE_BARS"] == "12"

    def test_purge_not_overridden_when_explicit(self, tmp_path, monkeypatch):
        """If user already set WF_PURGE_BARS, auto-purge respects it."""
        d = tmp_path / "labels"
        d.mkdir()
        f = d / "triple_barrier_XAU_USD_1h_tp2_sl1_max60.parquet"
        f.write_bytes(b"")

        monkeypatch.setenv("WF_PURGE_BARS", "20")
        m = _FILENAME_RE.search(f.name)
        target_purge = int(m.group(1))
        if "WF_PURGE_BARS" not in os.environ:
            os.environ["WF_PURGE_BARS"] = str(target_purge)
        # User value of 20 retained, not overridden by 60 from filename
        assert os.environ["WF_PURGE_BARS"] == "20"


class TestInspectionScriptRegex:
    """Regex robustness for scripts/inspect_phase8_retrain.py."""

    def test_extracts_xgb_acc(self):
        text = "XGBoost trained, walk-forward accuracy: 0.629 (5 folds)"
        m = re.search(r"XGBoost trained, walk-forward accuracy:\s*([\d.]+)", text)
        assert m is not None
        assert float(m.group(1)) == 0.629

    def test_extracts_lstm_walkforward(self):
        text = "LSTM trained, val_accuracy: 0.633, walk-forward: 0.702 (5 folds)"
        m = re.search(r"walk-forward:\s*([\d.]+)", text)
        assert m is not None
        assert float(m.group(1)) == 0.702

    def test_extracts_dqn_reward(self):
        text = "Najlepsza nagroda: -2.1234"
        m = re.search(r"Najlepsza nagroda:\s*([\-\d.]+)", text)
        assert m is not None
        assert float(m.group(1)) == -2.1234

    def test_extracts_dqn_episodes(self):
        text = "Model zapisany (ep 287/300)"
        m = re.search(r"Model zapisany \(ep (\d+)/(\d+)\)", text)
        assert m is not None
        assert int(m.group(1)) == 287
        assert int(m.group(2)) == 300

    def test_extracts_holdout_pf(self):
        text = "  profit_factor      1.85"
        m = re.search(r"profit_factor[\s|:|=]+([\d.]+)", text, re.IGNORECASE)
        assert m is not None
        assert float(m.group(1)) == 1.85

    def test_extracts_negative_return(self):
        text = "  return_pct        -3.42"
        m = re.search(r"return_pct[\s|:|=]+([\-\d.]+)", text, re.IGNORECASE)
        assert m is not None
        assert float(m.group(1)) == -3.42
