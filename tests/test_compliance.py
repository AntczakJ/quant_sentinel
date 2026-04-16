"""
tests/test_compliance.py — Tests for compliance, audit, backup, monitoring, metrics
"""

import pytest
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestHashChainAudit:
    def test_compute_hash_deterministic(self):
        from src.ops.compliance import _compute_hash
        h1 = _compute_hash(1, "OPEN", "WIN", "status", "OPEN", "WIN", "test", "2026-01-01", "GENESIS")
        h2 = _compute_hash(1, "OPEN", "WIN", "status", "OPEN", "WIN", "test", "2026-01-01", "GENESIS")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256

    def test_different_inputs_different_hash(self):
        from src.ops.compliance import _compute_hash
        h1 = _compute_hash(1, "OPEN", "WIN", "status", "", "", "", "2026-01-01", "GENESIS")
        h2 = _compute_hash(2, "OPEN", "WIN", "status", "", "", "", "2026-01-01", "GENESIS")
        assert h1 != h2

    def test_verify_chain_on_empty(self):
        from src.ops.compliance import verify_audit_chain
        # Reset audit log so this test is deterministic regardless of test
        # order. Other tests (or a carried-over test_sentinel.db) can leave
        # audit entries whose chain is broken mid-way, failing verify.
        from src.core.database import NewsDB
        NewsDB()._execute("DELETE FROM trades_audit")
        result = verify_audit_chain()
        assert result["valid"] is True

    def test_log_audit_with_chain(self):
        from src.ops.compliance import log_audit_with_chain
        # Should not raise
        log_audit_with_chain(9999, "TEST", "TEST_DONE", "status", "TEST", "TEST_DONE", "unit test")


class TestExecutionQuality:
    def test_returns_dict(self):
        from src.ops.compliance import get_execution_quality_report
        result = get_execution_quality_report(days=365)
        assert isinstance(result, dict)


class TestDailyReport:
    def test_generate_report(self):
        from src.ops.compliance import generate_daily_report
        result = generate_daily_report("2026-01-01")
        assert isinstance(result, dict)
        assert "date" in result

    def test_get_nonexistent_report(self):
        from src.ops.compliance import get_daily_report
        result = get_daily_report("1999-01-01")
        assert result is None or isinstance(result, dict)


class TestDataRetention:
    def test_archive_returns_dict(self):
        from src.ops.compliance import archive_old_data
        result = archive_old_data(retention_days=365)
        assert isinstance(result, dict)
        assert "protected_tables" in result


class TestDatabaseBackup:
    def test_create_and_list(self):
        from src.ops.db_backup import create_backup, get_backup_list
        path = create_backup(reason="unit_test")
        if path:
            assert os.path.exists(path)
            os.remove(path)
        backups = get_backup_list()
        assert isinstance(backups, list)

    def test_wal_mode(self):
        from src.ops.db_backup import enable_wal_mode
        enable_wal_mode()  # should not raise


class TestMonitoring:
    def test_system_health(self):
        from src.ops.monitoring import get_system_health
        health = get_system_health()
        assert "status" in health
        assert "checks" in health
        assert "database" in health["checks"]


class TestMetricsCollection:
    def test_counter(self):
        from src.ops.metrics import _Counter
        c = _Counter()
        c.inc()
        c.inc(3)
        assert c.value == 4

    def test_gauge(self):
        from src.ops.metrics import _Gauge
        g = _Gauge()
        g.set(10.0)
        g.inc(-3.0)
        assert g.value == 7.0

    def test_histogram(self):
        from src.ops.metrics import _Histogram
        h = _Histogram()
        for v in [1.0, 2.0, 3.0]:
            h.observe(v)
        assert h.count == 3
        assert h.avg == 2.0
        assert h.p95 >= 2.0

    def test_get_all_metrics(self):
        from src.ops.metrics import get_all_metrics
        m = get_all_metrics()
        assert "trading" in m
        assert "api" in m
        assert "latency" in m
        assert "portfolio" in m
