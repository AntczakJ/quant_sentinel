"""
tests/test_grid_endpoints.py — TestClient coverage for /api/grid/*.

Covers happy-path, missing-grid 404, path-traversal guard on rollback,
and preview-mode (confirm=false) on apply / rollback. Uses the same
TestClient pattern as tests/test_api_endpoints.py.

These tests don't depend on a running uvicorn — TestClient drives the
ASGI app directly. They DO touch sentinel.db read paths via NewsDB
inside the grid router; that's read-only, no writes happen unless
confirm=true (which we never set in tests).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

try:
    from api.main import app
except ImportError as e:  # pragma: no cover
    pytest.skip(f"Cannot import FastAPI app: {e}", allow_module_level=True)

client = TestClient(app)


# ─── /api/grid/list ─────────────────────────────────────────────


def test_grid_list_returns_array():
    r = client.get("/api/grid/list")
    assert r.status_code == 200
    data = r.json()
    assert "grids" in data
    assert isinstance(data["grids"], list)


def test_grid_list_contains_prod_v1_when_present():
    r = client.get("/api/grid/list")
    assert r.status_code == 200
    names = {g["name"] for g in r.json()["grids"]}
    # prod_v1 is the canonical grid in `reports/wf_grid_prod_v1_{A,B}/`.
    # Skip — and don't fail the suite — if Janek hasn't run the grid here.
    if "prod_v1" not in names:
        pytest.skip("grid prod_v1 report not present on this checkout")
    g = next(g for g in r.json()["grids"] if g["name"] == "prod_v1")
    assert g["stages"], "prod_v1 should have at least one stage entry"


# ─── /api/grid/preview ──────────────────────────────────────────


def test_grid_preview_unknown_grid_returns_404():
    r = client.get("/api/grid/preview", params={"grid": "this_does_not_exist_xyz"})
    assert r.status_code == 404


def test_grid_preview_prod_v1_returns_diff():
    r = client.get("/api/grid/preview", params={"grid": "prod_v1"})
    if r.status_code == 404:
        pytest.skip("grid prod_v1 report not present on this checkout")
    assert r.status_code == 200
    body = r.json()
    assert body["grid"] == "prod_v1"
    assert "diff" in body and isinstance(body["diff"], list)
    # The diff entry shape — each row must have these keys.
    for row in body["diff"]:
        for key in ("param", "current", "winner", "change_pct", "unchanged"):
            assert key in row, f"missing {key} in {row}"
    # Metrics block carries Sharpe/PF/return/dd
    metrics = body.get("metrics", {})
    for key in ("sharpe_mean", "profit_factor_mean", "return_pct_mean", "max_drawdown_pct_mean"):
        assert key in metrics


# ─── /api/grid/apply ────────────────────────────────────────────


def test_grid_apply_without_confirm_is_preview_only():
    """Sanity: apply without confirm:true must NOT write to dynamic_params."""
    r = client.post(
        "/api/grid/apply",
        json={"grid": "prod_v1", "confirm": False},
    )
    if r.status_code == 404:
        pytest.skip("grid prod_v1 report not present on this checkout")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["applied"] is False
    assert "winner" in body
    # Reason text describes the no-write reason.
    assert "preview-only" in (body.get("reason") or "")


def test_grid_apply_unknown_grid_returns_404():
    r = client.post("/api/grid/apply", json={"grid": "no_such_grid", "confirm": False})
    assert r.status_code == 404


# ─── /api/grid/backups ──────────────────────────────────────────


def test_grid_backups_returns_array():
    r = client.get("/api/grid/backups")
    assert r.status_code == 200
    body = r.json()
    assert "backups" in body
    assert isinstance(body["backups"], list)
    # Each entry should have these keys when not empty.
    for b in body["backups"]:
        for key in ("filename", "path", "backup_ts_utc", "params"):
            assert key in b


# ─── /api/grid/rollback — path traversal guard ─────────────────


@pytest.mark.parametrize("evil", [
    "../etc/passwd",
    "..\\Windows\\System32\\config",
    "/absolute/path.json",
    ".hidden.json",
])
def test_grid_rollback_rejects_path_traversal(evil: str):
    r = client.post(
        "/api/grid/rollback",
        json={"backup_filename": evil, "confirm": False},
    )
    assert r.status_code == 400, f"path traversal '{evil}' should be rejected, got {r.status_code}"


def test_grid_rollback_missing_file_returns_404():
    r = client.post(
        "/api/grid/rollback",
        json={"backup_filename": "this_backup_does_not_exist_zz.json", "confirm": False},
    )
    assert r.status_code == 404


def test_grid_rollback_without_confirm_is_preview():
    """If a backup exists, calling rollback without confirm should preview only."""
    listing = client.get("/api/grid/backups").json()
    if not listing["backups"]:
        pytest.skip("no grid backups present")
    name = listing["backups"][0]["filename"]
    r = client.post(
        "/api/grid/rollback",
        json={"backup_filename": name, "confirm": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["applied"] is False
    assert "would_restore" in body
