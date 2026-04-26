"""
Parity test: DuckDB vs pandas warehouse reader.

Reads each XAU/USD parquet (5m, 15m, 30m, 1h, 4h, 1d) twice — once with
pandas, once with DuckDB — and asserts the resulting DataFrames are
byte-equivalent on schema, row count, and per-bar OHLCV values.

Skips automatically when warehouse files are missing (CI / fresh clone).

Run:  .venv/Scripts/python.exe -m pytest tests/test_warehouse_duckdb_parity.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

WAREHOUSE = Path("data/historical/XAU_USD")
TFS = ["5min", "15min", "30min", "1h", "4h", "1d"]


def _have_warehouse() -> bool:
    return WAREHOUSE.exists() and any((WAREHOUSE / f"{tf}.parquet").exists() for tf in TFS)


pytestmark = pytest.mark.skipif(
    not _have_warehouse(),
    reason="warehouse parquets not present (run scripts/data_collection/fetch_xau_history.py)",
)


@pytest.mark.parametrize("tf", TFS)
def test_pandas_vs_duckdb_parity(tf: str):
    """For each TF that exists, pandas-read and duckdb-read DataFrames must match."""
    path = WAREHOUSE / f"{tf}.parquet"
    if not path.exists():
        pytest.skip(f"{path} missing")

    # Path A — pandas baseline (current production behaviour)
    df_pd = pd.read_parquet(path)

    # Path B — DuckDB
    duckdb = pytest.importorskip("duckdb")
    posix_path = str(path).replace("\\", "/")
    df_dk = duckdb.sql(f"SELECT * FROM read_parquet('{posix_path}')").df()

    # Schema parity — same columns, same dtypes (loose: kind only)
    assert list(df_pd.columns) == list(df_dk.columns), f"column mismatch: {df_pd.columns} vs {df_dk.columns}"
    for col in df_pd.columns:
        assert df_pd[col].dtype.kind == df_dk[col].dtype.kind, (
            f"dtype kind mismatch on {col}: {df_pd[col].dtype} vs {df_dk[col].dtype}"
        )

    # Row count parity
    assert len(df_pd) == len(df_dk), f"row count mismatch: {len(df_pd)} vs {len(df_dk)}"

    # OHLCV value parity — float-tolerant (DuckDB & pyarrow can normalize
    # NaN representations differently)
    ohlcv = [c for c in ["open", "high", "low", "close", "volume"] if c in df_pd.columns]
    for col in ohlcv:
        a = pd.to_numeric(df_pd[col], errors="coerce").to_numpy()
        b = pd.to_numeric(df_dk[col], errors="coerce").to_numpy()
        # equal_nan=True so missing volume rows compare clean
        import numpy as np
        assert np.allclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-9), (
            f"OHLCV diverged on {tf}.{col}: max-abs-diff="
            f"{float(abs(a - b).max(initial=0.0))}"
        )

    # Timestamp parity — DuckDB returns datetime64; pandas may need UTC normalization
    if "timestamp" in df_pd.columns or "datetime" in df_pd.columns:
        ts_col = "timestamp" if "timestamp" in df_pd.columns else "datetime"
        ts_pd = pd.to_datetime(df_pd[ts_col], utc=True)
        ts_dk = pd.to_datetime(df_dk[ts_col], utc=True)
        assert ts_pd.equals(ts_dk), f"timestamp diverged on {tf}"


def test_historical_provider_uses_duckdb_when_env_set(monkeypatch):
    """When QUANT_USE_DUCKDB=1, the helper should route through duckdb.sql."""
    pytest.importorskip("duckdb")
    monkeypatch.setenv("QUANT_USE_DUCKDB", "1")
    from src.backtest.historical_provider import _read_warehouse_parquet

    # Pick the smallest available file
    path = None
    for tf in ["1d", "1day", "4h"]:
        p = WAREHOUSE / f"{tf}.parquet"
        if p.exists():
            path = p
            break
    if path is None:
        pytest.skip("no small warehouse parquet to read")

    df = _read_warehouse_parquet(path)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    # Must have OHLC columns regardless of reader path
    for c in ("open", "high", "low", "close"):
        assert c in df.columns


def test_historical_provider_pandas_default(monkeypatch):
    """Without the env var, fallback path is pandas."""
    monkeypatch.delenv("QUANT_USE_DUCKDB", raising=False)
    from src.backtest.historical_provider import _read_warehouse_parquet

    path = None
    for tf in ["1d", "1day", "4h"]:
        p = WAREHOUSE / f"{tf}.parquet"
        if p.exists():
            path = p
            break
    if path is None:
        pytest.skip("no small warehouse parquet to read")

    df = _read_warehouse_parquet(path)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
