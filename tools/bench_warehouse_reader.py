"""Quick benchmark: pandas vs DuckDB on warehouse parquet reads.

Run: .venv/Scripts/python.exe tools/bench_warehouse_reader.py
"""
import time
from pathlib import Path

import duckdb
import pandas as pd

P = Path("data/historical/XAU_USD/5min.parquet")
POSIX = str(P).replace("\\", "/")


def bench(label, fn, runs=5):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        df = fn()
        times.append(time.perf_counter() - t0)
    times.sort()
    print(
        f"{label:32s} median={times[len(times)//2]*1000:7.1f} ms  "
        f"min={min(times)*1000:7.1f} ms  rows={len(df)}"
    )


print(f"File: {P} ({P.stat().st_size / 1024 / 1024:.1f} MB)")
print()
print("--- Full read ---")
bench("pandas pd.read_parquet", lambda: pd.read_parquet(P))
bench("duckdb read_parquet",
      lambda: duckdb.sql(f"SELECT * FROM read_parquet('{POSIX}')").df())

# Typical backtest pattern: last N days only
N_BARS = 30 * 24 * 12  # 30 days × 24 h × 12 (5-min bars)
print()
print(f"--- Filtered: last {N_BARS} bars (~30 days of 5m) ---")
bench("pandas (read+tail)",
      lambda: pd.read_parquet(P).tail(N_BARS))
bench("duckdb (LIMIT)",
      lambda: duckdb.sql(
          f"SELECT * FROM read_parquet('{POSIX}') ORDER BY datetime DESC LIMIT {N_BARS}"
      ).df())

# Multi-asset cross-symbol scan — pandas needs glob+concat, DuckDB does it natively
import glob
print()
print("--- Cross-symbol: avg/min/max close per symbol on 1day files ---")


def pandas_xs():
    rows = []
    for path in sorted(glob.glob("data/historical/*/1day.parquet")):
        symbol = path.split("/")[-2] if "/" in path else path.split("\\")[-2]
        df = pd.read_parquet(path)
        rows.append({
            "symbol": symbol,
            "n": len(df),
            "avg": df["close"].mean(),
            "min": df["close"].min(),
            "max": df["close"].max(),
        })
    return pd.DataFrame(rows)


def duckdb_xs():
    return duckdb.sql(
        "SELECT regexp_extract(filename, 'historical[\\\\/](.+?)[\\\\/]', 1) AS symbol, "
        "       COUNT(*) AS n, AVG(close) AS avg, MIN(close) AS min, MAX(close) AS max "
        "FROM read_parquet('data/historical/*/1day.parquet', filename=true) "
        "GROUP BY symbol ORDER BY symbol"
    ).df()


bench("pandas (loop+concat)", pandas_xs)
bench("duckdb (single SQL)",  duckdb_xs)
