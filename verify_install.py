#!/usr/bin/env python3
"""
verify_install.py - Post-deploy verification checklist.

Run after `git pull` and API restart. Checks that all new infrastructure
(RL model, observability, event guard, ensemble, registry) is live and
working. Exits 0 on success, 1 if any check fails.

Usage:
    python verify_install.py
    python verify_install.py --api http://localhost:8000    # custom API URL
"""
from __future__ import annotations

import argparse
import os
import sys

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'


# ANSI colors (degrade gracefully on Windows cmd)
def _c(code: str, s: str) -> str:
    if sys.stdout.isatty() and os.name != 'nt':
        return f"\033[{code}m{s}\033[0m"
    return s


GREEN = lambda s: _c("32", s)
RED = lambda s: _c("31", s)
YELLOW = lambda s: _c("33", s)
BOLD = lambda s: _c("1", s)


class Checks:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = ""):
        self.results.append((name, ok, detail))

    def summary(self) -> bool:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print()
        print("=" * 62)
        for name, ok, detail in self.results:
            icon = GREEN("[OK]") if ok else RED("[FAIL]")
            suffix = f" -- {detail}" if detail else ""
            print(f"  {icon} {name}{suffix}")
        print("=" * 62)
        status = f"{passed}/{total} checks passed"
        print(BOLD(GREEN(status) if passed == total else RED(status)))
        return passed == total


def check_model_artifact(c: Checks):
    try:
        import pickle
        path = "models/rl_agent.keras"
        params = path + ".params"
        assert os.path.exists(path), "model file missing"
        assert os.path.exists(params), "params file missing"
        with open(params, "rb") as f:
            p = pickle.load(f)
        detail = f"eps={p.get('epsilon'):.3f} train_step={p.get('train_step','?')} hash={p.get('data_hash')}"
        c.add("RL model artifact present + loadable", True, detail)
    except Exception as e:
        c.add("RL model artifact present + loadable", False, str(e)[:60])


def check_onnx_artifact(c: Checks):
    try:
        import os as _os
        path = "models/rl_agent.onnx"
        assert _os.path.exists(path), "missing"
        size_kb = _os.path.getsize(path) / 1024
        # Is ONNX newer than Keras model?
        keras_mtime = _os.path.getmtime("models/rl_agent.keras")
        onnx_mtime = _os.path.getmtime(path)
        stale = onnx_mtime < keras_mtime
        detail = f"{size_kb:.1f} KB" + (" (STALE — rerun regenerate_rl_onnx.py)" if stale else " (fresh)")
        c.add("RL ONNX artifact present + fresh", not stale, detail)
    except Exception as e:
        c.add("RL ONNX artifact present + fresh", False, str(e)[:60])


def check_db_indexes(c: Checks):
    try:
        import sqlite3
        conn = sqlite3.connect("data/sentinel.db")
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND "
            "name IN ('idx_ml_pred_timestamp', 'idx_ml_pred_trade_id', 'idx_rejected_filter')"
        ).fetchall()
        conn.close()
        found = {r[0] for r in rows}
        missing = {'idx_ml_pred_timestamp', 'idx_ml_pred_trade_id', 'idx_rejected_filter'} - found
        if not missing:
            c.add("DB Phase 1 indexes present", True, f"{len(found)}/3")
        else:
            c.add("DB Phase 1 indexes present", False, f"missing: {missing}")
    except Exception as e:
        c.add("DB Phase 1 indexes present", False, str(e)[:60])


def check_ensemble_weights(c: Checks):
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        models = ["smc", "attention", "dpformer", "lstm", "xgb", "dqn"]
        weights = {m: db.get_param(f"ensemble_weight_{m}") for m in models}
        missing = [m for m, v in weights.items() if v is None]
        if missing:
            c.add("ensemble weights in DB", False, f"missing: {missing}")
        else:
            dqn_w = float(weights["dqn"])
            detail = f"all 6 present, dqn={dqn_w:.3f}" + (" (elevated)" if dqn_w > 0.15 else "")
            c.add("ensemble weights in DB", True, detail)
    except Exception as e:
        c.add("ensemble weights in DB", False, str(e)[:60])


def check_track_record_columns(c: Checks):
    """New counters may be zero if no trades resolved yet — we only verify schema."""
    try:
        from src.ml.ensemble_models import get_model_track_record
        tr = get_model_track_record()
        expected = {"smc", "attention", "dpformer", "lstm", "xgb", "dqn"}
        if set(tr.keys()) == expected:
            total_trades = sum(s["n"] for s in tr.values())
            detail = f"schema OK, {total_trades} tracked events so far"
            c.add("per-model track record schema", True, detail)
        else:
            c.add("per-model track record schema", False, f"keys={set(tr.keys())}")
    except Exception as e:
        c.add("per-model track record schema", False, str(e)[:60])


def check_api_health(c: Checks):
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(f"{c.api_url}/api/health", timeout=3) as r:
            data = json.load(r)
        ok = data.get("status") == "healthy"
        detail = f"uptime={data.get('uptime', '?')}"
        c.add("API /api/health reachable", ok, detail)
        return True
    except Exception as e:
        c.add("API /api/health reachable", False, str(e)[:60] + " (is API running?)")
        return False


def check_api_scanner_health(c: Checks):
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(f"{c.api_url}/api/health/scanner", timeout=3) as r:
            data = json.load(r)
        status = data.get("status", "?")
        scans = data.get("scans_total", 0)
        p95 = data.get("p95_duration_ms", 0)
        detail = f"status={status}, scans={scans}, p95={p95}ms"
        # Any status except FAIL (exception) is a valid endpoint response
        c.add("API /api/health/scanner reachable", True, detail)
    except Exception as e:
        c.add("API /api/health/scanner reachable", False, str(e)[:60])


def check_api_metrics(c: Checks):
    try:
        import urllib.request
        import json
        with urllib.request.urlopen(f"{c.api_url}/api/metrics", timeout=3) as r:
            data = json.load(r)
        has_scanner = "scanner_health" in data
        detail = "scanner_health section present" if has_scanner else "scanner_health MISSING"
        c.add("API /api/metrics exposes scanner_health", has_scanner, detail)
    except Exception as e:
        c.add("API /api/metrics exposes scanner_health", False, str(e)[:60])


def check_api_backtest_endpoints(c: Checks):
    """Verify /api/backtest/runs + /latest respond (may return 404 if no runs yet)."""
    try:
        import urllib.request
        import urllib.error
        import json
        with urllib.request.urlopen(f"{c.api_url}/api/backtest/runs", timeout=3) as r:
            data = json.load(r)
        count = data.get("count", 0)
        detail = f"{count} runs indexed"
        c.add("API /api/backtest/runs responds", True, detail)
    except Exception as e:
        c.add("API /api/backtest/runs responds", False, str(e)[:60])

    # /latest may 404 legitimately if no runs yet — treat 404 as OK
    try:
        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen(f"{c.api_url}/api/backtest/latest", timeout=3):
                detail = "returned latest run"
        except urllib.error.HTTPError as he:
            if he.code == 404:
                detail = "404 (no runs yet — expected)"
            else:
                raise
        c.add("API /api/backtest/latest responds", True, detail)
    except Exception as e:
        c.add("API /api/backtest/latest responds", False, str(e)[:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000",
                    help="API base URL (default http://localhost:8000)")
    ap.add_argument("--skip-api", action="store_true",
                    help="skip HTTP checks (for CI / offline)")
    args = ap.parse_args()

    c = Checks(args.api)
    print(BOLD("\n=== Post-deploy verification ==="))

    # Filesystem / DB checks (always)
    check_model_artifact(c)
    check_onnx_artifact(c)
    check_db_indexes(c)
    check_ensemble_weights(c)
    check_track_record_columns(c)

    # HTTP checks (need running API)
    if not args.skip_api:
        if check_api_health(c):
            check_api_scanner_health(c)
            check_api_metrics(c)
            check_api_backtest_endpoints(c)
    else:
        print(YELLOW("  [SKIP] HTTP checks (--skip-api)"))

    ok = c.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
