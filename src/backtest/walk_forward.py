"""
walk_forward.py — Rolling-window walk-forward backtest validation.

Splits historical period into N rolling windows:
  Train: [t, t + train_days]
  Test:  [t + train_days, t + train_days + test_days]
  Then: t += step_days

For each window:
  1. Train models on train period (or skip if read-only walk-forward)
  2. Run production backtest pipeline on test period
  3. Record metrics (WR, PF, Sharpe, max DD, return)

Aggregate across all windows for statistical significance.

Usage (read-only — uses current models, just rolls test window):
    from src.backtest.walk_forward import walk_forward
    results = walk_forward(
        start_date='2024-01-01',
        end_date='2026-04-01',
        train_days=90,
        test_days=7,
        step_days=7,
    )
    print_summary(results)
"""
from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger("quant_sentinel.walk_forward")


@dataclass
class WindowResult:
    window_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_trades: int
    n_wins: int
    n_losses: int
    n_be: int
    win_rate: float
    profit_factor: float
    cumulative_pnl: float
    max_drawdown_pct: float
    sharpe: Optional[float] = None
    return_pct: Optional[float] = None
    error: Optional[str] = None


@dataclass
class WalkForwardResults:
    windows: list[WindowResult]
    config: dict

    @property
    def n_windows(self) -> int:
        return len(self.windows)

    @property
    def successful_windows(self) -> list[WindowResult]:
        return [w for w in self.windows if w.error is None and w.n_trades > 0]

    def aggregate(self) -> dict:
        """Aggregate metrics across all successful windows."""
        succ = self.successful_windows
        if not succ:
            return {"error": "no successful windows"}

        wrs = [w.win_rate for w in succ]
        pfs = [w.profit_factor for w in succ if w.profit_factor != float("inf")]
        pnls = [w.cumulative_pnl for w in succ]
        dds = [w.max_drawdown_pct for w in succ]

        return {
            "n_windows": len(succ),
            "n_trades_total": sum(w.n_trades for w in succ),
            "win_rate_mean": statistics.mean(wrs),
            "win_rate_stdev": statistics.stdev(wrs) if len(wrs) > 1 else 0.0,
            "profit_factor_mean": statistics.mean(pfs) if pfs else 0.0,
            "profit_factor_stdev": statistics.stdev(pfs) if len(pfs) > 1 else 0.0,
            "cumulative_pnl_total": sum(pnls),
            "cumulative_pnl_mean_per_window": statistics.mean(pnls),
            "max_drawdown_worst": min(dds),
            "max_drawdown_mean": statistics.mean(dds),
            "windows_profitable_pct": sum(1 for p in pnls if p > 0) / len(pnls) * 100,
        }

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "n_windows": self.n_windows,
            "n_successful": len(self.successful_windows),
            "aggregate": self.aggregate(),
            "windows": [asdict(w) for w in self.windows],
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


def generate_windows(
    start_date: str,
    end_date: str,
    train_days: int,
    test_days: int,
    step_days: int,
) -> list[tuple[datetime, datetime, datetime, datetime]]:
    """Generate (train_start, train_end, test_start, test_end) tuples."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    cursor = start
    windows = []
    while True:
        train_start = cursor
        train_end = cursor + timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + timedelta(days=test_days)
        if test_end > end:
            break
        windows.append((train_start, train_end, test_start, test_end))
        cursor = cursor + timedelta(days=step_days)
    return windows


def run_one_test_window(
    test_start: datetime,
    test_end: datetime,
    backtest_runner: Callable,
) -> dict:
    """
    Run backtest on a single test window.

    backtest_runner signature: (start_date, end_date) -> dict with metrics
    """
    return backtest_runner(test_start, test_end)


def walk_forward(
    start_date: str = "2024-01-01",
    end_date: str = "2026-04-01",
    train_days: int = 90,
    test_days: int = 7,
    step_days: int = 7,
    backtest_runner: Callable | None = None,
    train_runner: Callable | None = None,
) -> WalkForwardResults:
    """
    Run rolling walk-forward validation.

    Args:
        start_date, end_date: total period to roll over
        train_days: training window size
        test_days: test window size (= step_days for non-overlap)
        step_days: how far to advance between windows
        backtest_runner: callable(start_date, end_date) -> {metrics dict}
            If None, uses default that calls run_production_backtest
        train_runner: callable(start_date, end_date) -> None (re-trains models)
            If None, skip training (read-only walk-forward using current models)

    Returns:
        WalkForwardResults with per-window + aggregate metrics
    """
    config = {
        "start_date": start_date,
        "end_date": end_date,
        "train_days": train_days,
        "test_days": test_days,
        "step_days": step_days,
        "train_enabled": train_runner is not None,
    }

    windows_def = generate_windows(start_date, end_date, train_days, test_days, step_days)
    logger.info(f"Walk-forward: {len(windows_def)} windows planned")

    if backtest_runner is None:
        backtest_runner = _default_backtest_runner

    results: list[WindowResult] = []
    for idx, (train_s, train_e, test_s, test_e) in enumerate(windows_def):
        logger.info(
            f"Window {idx + 1}/{len(windows_def)}: "
            f"train [{train_s.date()} -> {train_e.date()}], "
            f"test [{test_s.date()} -> {test_e.date()}]"
        )
        try:
            if train_runner:
                train_runner(train_s, train_e)
            metrics = backtest_runner(test_s, test_e)
            wr = WindowResult(
                window_idx=idx,
                train_start=str(train_s.date()),
                train_end=str(train_e.date()),
                test_start=str(test_s.date()),
                test_end=str(test_e.date()),
                n_trades=metrics.get("total_trades", 0),
                n_wins=metrics.get("wins", 0),
                n_losses=metrics.get("losses", 0),
                n_be=metrics.get("breakevens", 0),
                win_rate=metrics.get("win_rate_pct", 0.0),
                profit_factor=metrics.get("profit_factor", 0.0),
                cumulative_pnl=metrics.get("cumulative_profit", 0.0),
                max_drawdown_pct=metrics.get("max_drawdown_pct", 0.0),
                return_pct=metrics.get("return_pct"),
            )
        except Exception as e:
            logger.exception(f"Window {idx + 1} failed: {e}")
            wr = WindowResult(
                window_idx=idx,
                train_start=str(train_s.date()),
                train_end=str(train_e.date()),
                test_start=str(test_s.date()),
                test_end=str(test_e.date()),
                n_trades=0, n_wins=0, n_losses=0, n_be=0,
                win_rate=0.0, profit_factor=0.0, cumulative_pnl=0.0,
                max_drawdown_pct=0.0, error=str(e),
            )
        results.append(wr)

    return WalkForwardResults(windows=results, config=config)


def _default_backtest_runner(start: datetime, end: datetime) -> dict:
    """Wrapper around run_production_backtest for walk-forward use."""
    days = (end - start).days
    if days < 1:
        return {"total_trades": 0}
    import json as _json
    import subprocess, sys, os, tempfile
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    # Prefer the .venv python if available (matches local dev), else
    # fall back to whatever Python is running this process — both work
    # on Windows + Unix and don't depend on CWD.
    venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
    py_exec = str(venv_py) if venv_py.exists() else sys.executable

    # Use --output to write the stats dict to a temp JSON file. We read
    # that file instead of parsing stdout. Two reasons:
    #   1. Stdout encoding is platform-dependent (Windows cp1252 vs UTF-8)
    #      and the child prints Unicode dashes / Polish chars that break
    #      the parent's decode.
    #   2. The text-parser was fragile — colon-containing values, value
    #      strings with multiple tokens, etc. JSON gives the dict directly.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as _tmp:
        out_path = _tmp.name
    try:
        cmd = [
            py_exec,
            str(repo_root / "run_production_backtest.py"),
            "--reset",
            # Pass explicit --start AND --end. The original walk_forward
            # set a `BACKTEST_START_DATE` env var that nothing in
            # `run_production_backtest.py` reads — so every window
            # backtested the same default range (last N days from data
            # tail) and produced identical metrics across all 4 windows
            # (caught 2026-04-27 evening). Now each window gets the
            # right slice.
            "--start", start.strftime("%Y-%m-%d"),
            "--end", end.strftime("%Y-%m-%d"),
            # Use the local 3-year parquet warehouse instead of yfinance.
            # 10× faster (no HTTP) AND matches TwelveData spot the live
            # scanner uses (yfinance GC=F is futures, $65-75 different).
            "--warehouse",
            "--output", out_path,
        ]
        env = os.environ.copy()
        # Defense-in-depth on encoding (the JSON path doesn't actually
        # depend on stdout, but error logs from a failure run still go
        # through stdout/stderr so we want them readable).
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        result = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=3600,
            cwd=str(repo_root),
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            logger.warning(
                f"Backtest subprocess returned {result.returncode} for "
                f"{start} → {end}: "
                f"{(result.stderr or '')[-500:]}"
            )
        # Read the JSON output (always present unless backtest crashed
        # before writing — in which case the file stays empty).
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return {"total_trades": 0}
            return _json.loads(content)
        except (FileNotFoundError, _json.JSONDecodeError) as e:
            logger.warning(f"Could not read backtest stats for {start}: {e}")
            return {"total_trades": 0}
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def print_summary(results: WalkForwardResults) -> None:
    """Pretty-print walk-forward results."""
    agg = results.aggregate()
    print("\n" + "=" * 70)
    print("WALK-FORWARD BACKTEST SUMMARY")
    print("=" * 70)
    print(f"  Windows total:         {results.n_windows}")
    print(f"  Windows successful:    {len(results.successful_windows)}")
    if "error" in agg:
        print(f"  ERROR: {agg['error']}")
        return
    print(f"  Trades total:          {agg['n_trades_total']}")
    print(f"  WR mean (stdev):       {agg['win_rate_mean']:.1f}% ({agg['win_rate_stdev']:.1f}%)")
    print(f"  PF  mean (stdev):      {agg['profit_factor_mean']:.2f} ({agg['profit_factor_stdev']:.2f})")
    print(f"  PnL cumulative:        {agg['cumulative_pnl_total']:+.2f}")
    print(f"  PnL per window mean:   {agg['cumulative_pnl_mean_per_window']:+.2f}")
    print(f"  Max DD worst:          {agg['max_drawdown_worst']:.2f}%")
    print(f"  Max DD mean:           {agg['max_drawdown_mean']:.2f}%")
    print(f"  Windows profitable:    {agg['windows_profitable_pct']:.0f}%")
    print("=" * 70)
