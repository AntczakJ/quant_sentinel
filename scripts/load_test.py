"""
scripts/load_test.py — Load testing harness using locust.

Install:
    pip install locust

Run locally:
    locust -f scripts/load_test.py --host=http://localhost:8000

Run headless (CI / benchmark):
    locust -f scripts/load_test.py --host=http://localhost:8000 \
        --headless -u 50 -r 5 -t 2m --html reports/load_test.html

Metrics collected:
    - Request rate (RPS)
    - Response time p50/p95/p99
    - Failure rate
    - Per-endpoint breakdown
"""
from locust import HttpUser, task, between


class FrontendReader(HttpUser):
    """Simulates a logged-in user browsing the dashboard — mostly GETs."""

    wait_time = between(1, 3)  # think time between requests

    @task(10)
    def health(self):
        """Most frequent call — uptime monitor + frontend connection check."""
        self.client.get("/api/health", name="/api/health")

    @task(5)
    def health_detailed(self):
        self.client.get("/api/health/detailed", name="/api/health/detailed")

    @task(5)
    def scanner_health(self):
        self.client.get("/api/health/scanner", name="/api/health/scanner")

    @task(3)
    def models_health(self):
        self.client.get("/api/health/models", name="/api/health/models")

    @task(5)
    def metrics_json(self):
        self.client.get("/api/metrics", name="/api/metrics")

    @task(2)
    def prometheus_metrics(self):
        self.client.get("/metrics", name="/metrics")

    @task(4)
    def backtest_runs(self):
        self.client.get("/api/backtest/runs", name="/api/backtest/runs")

    @task(3)
    def training_history(self):
        self.client.get("/api/training/history", name="/api/training/history")

    @task(8)
    def market_ticker(self):
        self.client.get("/api/market/ticker", name="/api/market/ticker")

    @task(4)
    def market_candles(self):
        self.client.get("/api/market/candles", params={"interval": "15m", "limit": 100},
                        name="/api/market/candles")

    @task(2)
    def portfolio(self):
        self.client.get("/api/portfolio/balance", name="/api/portfolio/balance")


class ApiHammer(HttpUser):
    """Stress test — rapid-fire health/ticker (uptime monitor simulation)."""
    wait_time = between(0.1, 0.5)

    @task
    def ping_health(self):
        self.client.get("/api/health")


# Usage examples in comments:
#
# Baseline (50 users, 2 min, ramp 5/sec):
#   locust -f scripts/load_test.py --host=http://localhost:8000 \
#       --users 50 --spawn-rate 5 --run-time 2m --headless
#
# Soak test (100 users, 30 min):
#   locust -f scripts/load_test.py --host=http://localhost:8000 \
#       --users 100 --spawn-rate 10 --run-time 30m --headless \
#       --html reports/soak_test.html
#
# Stress test (target breaking point):
#   locust -f scripts/load_test.py --host=http://localhost:8000 \
#       --users 500 --spawn-rate 50 --run-time 5m --headless
#
# SLO targets:
#   - p95 latency < 500ms on /api/health, /api/metrics
#   - p95 latency < 2s on /api/market/candles
#   - Failure rate < 1% on 50-user baseline
#   - Failure rate < 5% on 200-user stress
