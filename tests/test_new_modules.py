"""
tests/test_new_modules.py — Tests for modules created in Phases 2-7

Tests:
  - ModelCalibrator (Platt Scaling)
  - ABTestManager (A/B Testing)
  - Metrics collection
  - Database backup
  - Model monitoring
"""

import pytest
import sys
import os
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ═══════════════════════════════════════════════════════════════════════════
#  MODEL CALIBRATION (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════

class TestPlattScaler:
    """Test Platt Scaling sigmoid calibration."""

    def test_uncalibrated_returns_input(self):
        from src.ml.model_calibration import PlattScaler
        s = PlattScaler()
        assert s.transform(0.7) == 0.7  # no-op when not fitted

    def test_fit_and_transform(self):
        from src.ml.model_calibration import PlattScaler
        s = PlattScaler()
        preds = np.array([0.1, 0.2, 0.3, 0.7, 0.8, 0.9] * 10)
        labels = np.array([0, 0, 0, 1, 1, 1] * 10)
        s.fit(preds, labels)
        assert s.fitted is True
        # Calibrated output should be between 0 and 1
        result = s.transform(0.8)
        assert 0.0 < result < 1.0

    def test_serialization(self):
        from src.ml.model_calibration import PlattScaler
        s = PlattScaler()
        s.a = 2.5
        s.b = -1.0
        s.fitted = True
        d = s.to_dict()
        s2 = PlattScaler.from_dict(d)
        assert s2.a == 2.5
        assert s2.b == -1.0
        assert s2.fitted is True


class TestModelCalibrator:
    """Test calibrator singleton."""

    def test_calibrate_unknown_model_applies_shrinkage(self, monkeypatch):
        """Uncalibrated models get shrunk 20% toward 0.5 (Platt-scaling
        penalty). Uncalibrated raw LSTM was routinely overconfident
        (outputs 0.97 when live accuracy ~0.55), so the penalty damps
        voting power until the model earns calibration with enough
        history. 0.75 -> 0.5 + (0.75-0.5)*0.8 = 0.70.

        2026-04-29: must explicitly clear DISABLE_CALIBRATION (kill-switch
        added in same audit) to test the shrinkage path itself."""
        monkeypatch.delenv("DISABLE_CALIBRATION", raising=False)
        from src.ml.model_calibration import get_calibrator
        cal = get_calibrator()
        result = cal.calibrate("nonexistent", 0.75)
        assert abs(result - 0.70) < 1e-6, f"Expected 0.70, got {result}"

    def test_calibrate_disabled_returns_raw(self, monkeypatch):
        """With DISABLE_CALIBRATION=1 BOTH paths (fitted Platt + 20%
        uncalibrated shrinkage) are bypassed and raw passes through
        unchanged. Audit kill-switch — see
        docs/strategy/2026-04-29_pretraining_master.md P0.1."""
        monkeypatch.setenv("DISABLE_CALIBRATION", "1")
        from src.ml.model_calibration import get_calibrator
        cal = get_calibrator()
        for raw in (0.10, 0.30, 0.50, 0.75, 0.90):
            assert abs(cal.calibrate("lstm", raw) - raw) < 1e-9
            assert abs(cal.calibrate("nonexistent", raw) - raw) < 1e-9

    def test_get_status(self):
        from src.ml.model_calibration import get_calibrator
        cal = get_calibrator()
        status = cal.get_status()
        assert isinstance(status, dict)


# ═══════════════════════════════════════════════════════════════════════════
#  A/B TESTING (Phase 6)
# ═══════════════════════════════════════════════════════════════════════════

class TestABTesting:
    """Test A/B parameter testing framework."""

    def test_initial_state_inactive(self):
        from src.learning.ab_testing import ABTestManager
        ab = ABTestManager()
        assert ab.is_active is False

    def test_propose_and_discard(self):
        from src.learning.ab_testing import ABTestManager
        ab = ABTestManager()
        ab.propose_params({"risk_percent": 1.5}, reason="unit test")
        assert ab.is_active is True
        ab.discard()
        assert ab.is_active is False

    def test_evaluate_needs_more_trades(self):
        from src.learning.ab_testing import ABTestManager
        ab = ABTestManager()
        ab.propose_params({"risk_percent": 1.5}, reason="unit test")
        result = ab.evaluate()
        assert result["action"] == "continue"
        ab.discard()  # cleanup

    def test_record_outcome(self):
        from src.learning.ab_testing import ABTestManager
        ab = ABTestManager()
        ab.propose_params({"risk_percent": 1.5})
        ab.record_outcome("WIN")
        ab.record_outcome("LOSS")
        assert ab._state["control_wins"] == 1
        assert ab._state["control_losses"] == 1
        ab.discard()

    def test_z_score_calculation(self):
        from src.learning.ab_testing import ABTestManager
        z = ABTestManager._two_proportion_z(50, 100, 60, 100)
        assert isinstance(z, float)
        assert z > 0  # 60% vs 50% should give positive z


# ═══════════════════════════════════════════════════════════════════════════
#  METRICS (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════

class TestMetrics:
    """Test in-process metrics collection."""

    def test_counter_increment(self):
        from src.ops.metrics import _Counter
        c = _Counter()
        c.inc()
        c.inc(5)
        assert c.value == 6

    def test_gauge_set(self):
        from src.ops.metrics import _Gauge
        g = _Gauge()
        g.set(42.5)
        assert g.value == 42.5
        g.inc(-2.5)
        assert g.value == 40.0

    def test_histogram_observe(self):
        from src.ops.metrics import _Histogram
        h = _Histogram()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            h.observe(v)
        assert h.count == 5
        assert h.avg == 3.0
        assert h.min_val == 1.0
        assert h.max_val == 5.0

    def test_timer_context(self):
        import time
        from src.ops.metrics import TimerContext, _Histogram
        h = _Histogram()
        with TimerContext(h):
            time.sleep(0.01)
        assert h.count == 1
        assert h.avg > 0

    def test_get_all_metrics(self):
        from src.ops.metrics import get_all_metrics
        m = get_all_metrics()
        assert "trading" in m
        assert "api" in m
        assert "latency" in m
        assert "portfolio" in m


# ═══════════════════════════════════════════════════════════════════════════
#  DATABASE BACKUP (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabaseBackup:
    """Test SQLite backup automation."""

    def test_create_backup(self):
        from src.ops.db_backup import create_backup
        path = create_backup(reason="test")
        if path:  # may be empty if using Turso
            assert os.path.exists(path)
            assert path.endswith(".db")
            # Cleanup
            os.remove(path)

    def test_backup_list(self):
        from src.ops.db_backup import get_backup_list
        backups = get_backup_list()
        assert isinstance(backups, list)

    def test_wal_mode(self):
        from src.ops.db_backup import enable_wal_mode
        # Should not raise
        enable_wal_mode()


# ═══════════════════════════════════════════════════════════════════════════
#  MODEL MONITORING (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════

class TestModelMonitoring:
    """Test drift detection and accuracy tracking."""

    def test_psi_identical_distributions(self):
        from src.ml.model_monitor import compute_psi
        ref = np.random.uniform(0, 1, 100)
        psi = compute_psi(ref, ref)
        assert psi < 0.01  # identical distributions = near-zero PSI

    def test_psi_different_distributions(self):
        from src.ml.model_monitor import compute_psi
        ref = np.random.uniform(0, 0.5, 100)
        cur = np.random.uniform(0.5, 1.0, 100)
        psi = compute_psi(ref, cur)
        assert psi > 0.1  # very different = high PSI

    def test_rolling_accuracy_returns_dict(self):
        from src.ml.model_monitor import compute_rolling_accuracy
        result = compute_rolling_accuracy()
        assert isinstance(result, dict)
        assert "lstm" in result
        assert "xgb" in result
        assert "n" in result

    def test_run_drift_check(self):
        from src.ml.model_monitor import run_drift_check
        alerts = run_drift_check()
        assert isinstance(alerts, list)
