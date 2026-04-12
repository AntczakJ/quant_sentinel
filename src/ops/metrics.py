"""
src/metrics.py — Lightweight in-process metrics collection

No external dependencies (no prometheus_client needed).
Collects counters, gauges, and histograms for monitoring.

Access via GET /api/metrics endpoint.
"""

import time
import threading
from collections import defaultdict
from typing import Dict


_lock = threading.Lock()


class _Counter:
    """Thread-safe monotonic counter."""
    def __init__(self):
        self.value = 0

    def inc(self, amount: int = 1):
        with _lock:
            self.value += amount


class _Gauge:
    """Thread-safe gauge (can go up or down)."""
    def __init__(self):
        self.value = 0.0

    def set(self, val: float):
        with _lock:
            self.value = val

    def inc(self, amount: float = 1.0):
        with _lock:
            self.value += amount


class _Histogram:
    """Simple histogram — tracks count, sum, min, max, recent values."""
    def __init__(self, max_samples: int = 100):
        self.count = 0
        self.total = 0.0
        self.min_val = float('inf')
        self.max_val = float('-inf')
        self._recent: list[float] = []
        self._max_samples = max_samples

    def observe(self, value: float):
        with _lock:
            self.count += 1
            self.total += value
            self.min_val = min(self.min_val, value)
            self.max_val = max(self.max_val, value)
            self._recent.append(value)
            if len(self._recent) > self._max_samples:
                self._recent.pop(0)

    @property
    def avg(self) -> float:
        return self.total / self.count if self.count > 0 else 0.0

    @property
    def p95(self) -> float:
        if not self._recent:
            return 0.0
        sorted_vals = sorted(self._recent)
        idx = int(len(sorted_vals) * 0.95)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]


# ═══════════════════════════════════════════════════════════════════════════
#  GLOBAL METRICS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

# Trading metrics
trades_opened = _Counter()
trades_won = _Counter()
trades_lost = _Counter()
trades_rejected = _Counter()
trades_blocked_by_risk = _Counter()

# API metrics
api_requests_total = _Counter()
api_errors_total = _Counter()

# Scanner health
scan_errors_total = _Counter()
scan_last_ts = _Gauge()
data_fetch_failures = _Counter()  # yfinance/twelve rate limits etc.

# Latency
scan_duration = _Histogram()
api_latency = _Histogram()
ensemble_prediction_time = _Histogram()

# Gauges
portfolio_balance = _Gauge()
portfolio_pnl = _Gauge()
daily_loss_pct = _Gauge()
open_positions_count = _Gauge()
model_agreement_ratio = _Gauge()


def get_all_metrics() -> Dict:
    """Return all metrics as a dict for the /api/metrics endpoint."""
    return {
        "trading": {
            "trades_opened": trades_opened.value,
            "trades_won": trades_won.value,
            "trades_lost": trades_lost.value,
            "trades_rejected": trades_rejected.value,
            "trades_blocked_by_risk": trades_blocked_by_risk.value,
            "win_rate": round(trades_won.value / max(trades_won.value + trades_lost.value, 1), 3),
        },
        "api": {
            "requests_total": api_requests_total.value,
            "errors_total": api_errors_total.value,
        },
        "latency": {
            "scan_avg_ms": round(scan_duration.avg * 1000, 1),
            "scan_p95_ms": round(scan_duration.p95 * 1000, 1),
            "scan_count": scan_duration.count,
            "api_avg_ms": round(api_latency.avg * 1000, 1),
            "api_p95_ms": round(api_latency.p95 * 1000, 1),
            "ensemble_avg_ms": round(ensemble_prediction_time.avg * 1000, 1),
        },
        "scanner_health": {
            "scan_count": scan_duration.count,
            "scan_errors_total": scan_errors_total.value,
            "scan_error_rate": round(scan_errors_total.value / max(scan_duration.count, 1), 3),
            "scan_last_ts": scan_last_ts.value,
            "data_fetch_failures": data_fetch_failures.value,
        },
        "portfolio": {
            "balance": portfolio_balance.value,
            "pnl": portfolio_pnl.value,
            "daily_loss_pct": daily_loss_pct.value,
            "open_positions": open_positions_count.value,
        },
        "models": {
            "agreement_ratio": model_agreement_ratio.value,
        },
    }


class TimerContext:
    """Context manager for timing operations."""
    def __init__(self, histogram: _Histogram):
        self._histogram = histogram
        self._start = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *args):
        elapsed = time.monotonic() - self._start
        self._histogram.observe(elapsed)
