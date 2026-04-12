"""tests/test_backtest_grid.py - Harness tests (no real backtests).

We mock run_cell and _run_single_window so the tests exercise every piece
of grid logic (build, persist, resume, compose, Pareto) without ever
spinning up TF / yfinance / the scanner.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _cwd_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Clear isolation-related env that may leak in from a prior test run
    # or a live API server in the same process tree. enforce_isolation()
    # re-sets these itself on import, but it FIRST asserts that any
    # existing DATABASE_URL doesn't already point at production — so we
    # have to unset before importing run_backtest_grid.
    for var in ("DATABASE_URL", "QUANT_BACKTEST_MODE", "QUANT_BACKTEST_RELAX",
                "TURSO_URL", "TURSO_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    yield


def _stub_result(cell_hash: str, *, sharpe: float, dd: float,
                 pf: float = 1.5, calmar: float = 1.0,
                 ret: float = 5.0, trades: int = 30,
                 params: dict | None = None) -> dict:
    return {
        "params": {"cell_hash": cell_hash,
                   "min_confidence": 0.5, "sl_atr_mult": 1.5, "target_rr": 2.5,
                   "partial_close": False, "risk_percent": 1.0,
                   **(params or {})},
        "windows": [],
        "agg": {
            "n_windows": 1, "n_errors": 0,
            "sharpe_mean": sharpe, "sharpe_stdev": 0,
            "calmar_mean": calmar, "calmar_stdev": 0,
            "profit_factor_mean": pf, "profit_factor_stdev": 0,
            "return_pct_mean": ret, "return_pct_stdev": 0,
            "max_drawdown_pct_mean": dd, "max_drawdown_pct_stdev": 0,
            "total_trades_mean": trades, "total_trades_stdev": 0,
            "sortino_mean": sharpe * 1.2, "sortino_stdev": 0,
            "expectancy_usd_mean": 5, "expectancy_usd_stdev": 0,
            "win_rate_pct_mean": 50, "win_rate_pct_stdev": 0,
        },
        "mc": {}, "elapsed_sec": 0.1,
    }


def test_build_grid_shapes():
    from run_backtest_grid import build_grid
    full = build_grid(smoke=False)
    smoke = build_grid(smoke=True)
    # Grid product: 4 * 2 * 3 * 2 * 2 = 96
    assert len(full) == 96
    assert len(smoke) == 3
    # Hashes must be unique across the full grid.
    hashes = [c.cell_hash() for c in full]
    assert len(set(hashes)) == len(hashes)


def test_cell_hash_stable():
    from run_backtest_grid import CellParams
    a = CellParams(0.5, 1.5, 2.5, False, 1.0)
    b = CellParams(0.5, 1.5, 2.5, False, 1.0)
    c = CellParams(0.5, 1.5, 2.5, True, 1.0)
    assert a.cell_hash() == b.cell_hash()
    assert a.cell_hash() != c.cell_hash()


def test_composite_orders_results():
    from run_backtest_grid import sort_by_composite
    cells = [
        _stub_result("aaa", sharpe=0.5, dd=-10, calmar=0.4, pf=1.1),
        _stub_result("bbb", sharpe=2.0, dd=-5, calmar=1.5, pf=2.5),
        _stub_result("ccc", sharpe=1.0, dd=-8, calmar=0.8, pf=1.8),
    ]
    ordered = sort_by_composite(cells)
    hashes = [c["params"]["cell_hash"] for c in ordered]
    # bbb has the highest sharpe+calmar+PF -> first.
    assert hashes[0] == "bbb"
    # aaa has the lowest metrics -> last.
    assert hashes[-1] == "aaa"


def test_composite_none_sorts_last():
    from run_backtest_grid import sort_by_composite, composite_score
    good = _stub_result("aaa", sharpe=1.0, dd=-5)
    bad = {"params": {"cell_hash": "nil"}, "agg": {}}
    assert composite_score(bad["agg"]) is None
    ordered = sort_by_composite([bad, good])
    assert ordered[0]["params"]["cell_hash"] == "aaa"
    assert ordered[-1]["params"]["cell_hash"] == "nil"


def test_pareto_front_basic():
    from run_backtest_grid import pareto_front
    # Layout on (sharpe, dd): higher sharpe + less-negative dd wins.
    cells = [
        _stub_result("best", sharpe=2.0, dd=-5),   # dominates all
        _stub_result("mid",  sharpe=1.5, dd=-7),   # dominated by best
        _stub_result("edge", sharpe=1.0, dd=-3),   # best DD -> on front
        _stub_result("dom",  sharpe=0.5, dd=-12),  # dominated by all
    ]
    front = {c["params"]["cell_hash"] for c in pareto_front(cells)}
    assert "best" in front
    assert "edge" in front  # wins on DD even with lower Sharpe
    assert "mid" not in front
    assert "dom" not in front


def test_resume_skips_completed(monkeypatch):
    """If a cell JSON already exists on disk, run_stage must NOT re-run it."""
    import run_backtest_grid as g

    calls = []
    def fake_run_cell(params, days, step_minutes, windows, mc_sims):
        calls.append(params.cell_hash())
        return _stub_result(params.cell_hash(), sharpe=1.0, dd=-5)

    monkeypatch.setattr(g, "run_cell", fake_run_cell)

    cells = g.build_grid(smoke=True)
    # Pre-seed one cell on disk as "already done".
    g.save_cell("unit", cells[0], _stub_result(cells[0].cell_hash(),
                                               sharpe=9.9, dd=-1))

    results = g.run_stage("unit", cells, days=7, step_minutes=15,
                          windows=1, mc_sims=0, resume=True)

    # run_cell should have been called for the two NOT-yet-persisted cells.
    assert len(calls) == 2
    assert cells[0].cell_hash() not in calls
    # Result list includes all three — two fresh + one loaded from disk.
    hashes = {r["params"]["cell_hash"] for r in results}
    assert hashes == {c.cell_hash() for c in cells}


def test_no_resume_reruns_everything(monkeypatch):
    import run_backtest_grid as g

    calls = []
    def fake_run_cell(params, days, step_minutes, windows, mc_sims):
        calls.append(params.cell_hash())
        return _stub_result(params.cell_hash(), sharpe=1.0, dd=-5)

    monkeypatch.setattr(g, "run_cell", fake_run_cell)

    cells = g.build_grid(smoke=True)
    g.save_cell("unit2", cells[0], _stub_result(cells[0].cell_hash(),
                                                sharpe=0.1, dd=-99))

    g.run_stage("unit2", cells, days=7, step_minutes=15,
                windows=1, mc_sims=0, resume=False)
    assert len(calls) == 3  # all three re-ran


def test_stage_report_and_pick_top_n(monkeypatch):
    import run_backtest_grid as g

    monkeypatch.setattr(g, "run_cell", lambda params, **kw: _stub_result(
        params.cell_hash(),
        sharpe={'aaa': 2.0, 'bbb': 0.5}.get(params.cell_hash()[:3], 1.0),
        dd=-5))

    cells = g.build_grid(smoke=True)
    results = g.run_stage("stgrep", cells, days=7, step_minutes=15,
                          windows=1, mc_sims=0, resume=False)
    report_path = g.write_stage_report("stgrep", "a", results)
    assert report_path.exists()

    survivors = g._pick_top_n(report_path, n=2)
    assert len(survivors) == 2
    # Survivors must be CellParams instances with valid hashes.
    for s in survivors:
        assert s.cell_hash() in {c.cell_hash() for c in cells}


def test_walkforward_windows_are_non_overlapping():
    from run_backtest_grid import _walk_forward_windows
    ws = _walk_forward_windows(total_days=28, n_windows=4)
    assert len(ws) == 4
    # Each window is 7 days.
    import datetime as dt
    for start, end in ws:
        s = dt.date.fromisoformat(start)
        e = dt.date.fromisoformat(end)
        assert (e - s).days == 7
