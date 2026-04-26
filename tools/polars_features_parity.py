"""
tools/polars_features_parity.py — proof-of-concept parity test:
  pandas-based feature computations  vs  polars equivalents.

Why this script exists
----------------------
Memory `feedback_overfitting_check.md` explicitly forbids data-driven
changes that haven't been parity-validated. The full `compute_features`
in `src/analysis/compute.py` is 500+ lines built on `pandas_ta`, which
has no native polars support — porting it is a multi-hour refactor and
needs bar-by-bar verification on historical training data.

This script tests the SUBSET of computations that have a clean polars
equivalent (basic indicators built from `close.pct_change()` and
`rolling()` aggregates). If parity holds here at the level of
`np.allclose(rtol=1e-6, atol=1e-9)`, it's a green light to start
porting more pieces.

If you ever flip `QUANT_USE_POLARS=1` env var (currently UNREAD by any
production code — wire it up only after the full port is parity-clean):
the production `compute_features` is unchanged. This script is a
research tool, not a production switch.

Run:
  .venv/Scripts/python.exe tools/polars_features_parity.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]


def load_xau_5min() -> pd.DataFrame:
    p = ROOT / "data" / "historical" / "XAU_USD" / "5min.parquet"
    if not p.exists():
        raise SystemExit(
            f"Warehouse parquet missing at {p}. Run "
            "scripts/data_collection/fetch_xau_history.py first."
        )
    df = pd.read_parquet(p).tail(5000).reset_index(drop=True)
    return df


def pandas_subset(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the subset that has a polars equivalent — pandas reference."""
    out = pd.DataFrame(index=df.index)
    out["ret_1"] = df["close"].pct_change()
    out["ret_5"] = df["close"].pct_change(5)
    out["ret_10"] = df["close"].pct_change(10)
    out["volatility_20"] = df["close"].pct_change().rolling(20).std()
    out["sma_20"] = df["close"].rolling(20).mean()
    out["high_14"] = df["high"].rolling(14).max()
    out["low_14"] = df["low"].rolling(14).min()
    out["body_ratio"] = (df["close"] - df["open"]).abs() / (df["high"] - df["low"] + 1e-10)
    return out


def polars_subset(df_pd: pd.DataFrame) -> pd.DataFrame:
    """Same set of features, computed via polars Lazy expressions."""
    df = pl.from_pandas(df_pd)
    out = (
        df.select(
            pl.col("close").pct_change().alias("ret_1"),
            pl.col("close").pct_change(5).alias("ret_5"),
            pl.col("close").pct_change(10).alias("ret_10"),
            pl.col("close").pct_change().rolling_std(window_size=20).alias("volatility_20"),
            pl.col("close").rolling_mean(window_size=20).alias("sma_20"),
            pl.col("high").rolling_max(window_size=14).alias("high_14"),
            pl.col("low").rolling_min(window_size=14).alias("low_14"),
            ((pl.col("close") - pl.col("open")).abs()
             / (pl.col("high") - pl.col("low") + 1e-10)).alias("body_ratio"),
        )
    )
    return out.to_pandas()


def main() -> int:
    df = load_xau_5min()
    print(f"== Loaded {len(df)} bars of XAU/USD 5m")
    print(f"   columns: {list(df.columns)}")
    print()

    print("== pandas baseline")
    t0 = time.perf_counter()
    pd_features = pandas_subset(df)
    pd_t = time.perf_counter() - t0
    print(f"   {pd_t * 1000:.1f} ms — {pd_features.shape}")

    print("== polars equivalent")
    t0 = time.perf_counter()
    pl_features = polars_subset(df)
    pl_t = time.perf_counter() - t0
    print(f"   {pl_t * 1000:.1f} ms — {pl_features.shape}")

    print()
    print(f"== speedup pandas / polars = {pd_t / pl_t:.2f}x")
    print()

    print("== Per-column parity (rtol=1e-6, atol=1e-9):")
    failed = 0
    for col in pd_features.columns:
        a = pd_features[col].to_numpy()
        b = pl_features[col].to_numpy()
        ok = np.allclose(a, b, rtol=1e-6, atol=1e-9, equal_nan=True)
        max_diff = float(np.nanmax(np.abs(a - b))) if len(a) else 0.0
        flag = "OK" if ok else "FAIL"
        print(f"   [{flag}] {col:20s}  max abs diff = {max_diff:.6e}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"[FAIL] {failed} column(s) diverged — DO NOT migrate compute_features yet.")
        return 1
    print("[OK] Subset parity holds. The remaining ~50 features in compute_features still")
    print("     need to be ported individually (pandas_ta doesn't have polars output).")
    print()
    print("Next steps if Janek wants to push the migration further:")
    print("  1. Port the next slice of features (pandas_ta.rsi, pandas_ta.macd, pandas_ta.atr)")
    print("     by replacing them with polars expressions or numpy/numba helpers.")
    print("  2. Run this script after each batch — abort the moment parity drops.")
    print("  3. Once 100% parity holds for the full FEATURE_COLS list, gate the swap")
    print("     behind QUANT_USE_POLARS=1 in compute.py and run a full backtest A/B.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
