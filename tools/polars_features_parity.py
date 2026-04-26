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


def _rma_numpy(x: np.ndarray, length: int) -> np.ndarray:
    """Wilder's RMA: SMA seed for the first `length` values, then EMA with
    alpha=1/length. Pandas_ta documents `rma()` as
    `close.ewm(alpha=alpha, adjust=False).mean()` — for the ATR case
    this matches our numpy version to floating-point precision."""
    x = np.asarray(x, dtype=np.float64)
    out = np.full_like(x, np.nan)
    if len(x) < length:
        return out
    # Use pandas-style direct ewm (no SMA seed — matches pandas_ta v0.4.x)
    alpha = 1.0 / length
    # Seed with the first non-NaN value, then ewm forward
    seed_idx = int(np.argmax(~np.isnan(x)))
    out[seed_idx] = x[seed_idx] if not np.isnan(x[seed_idx]) else 0.0
    for i in range(seed_idx + 1, len(x)):
        v = x[i] if not np.isnan(x[i]) else 0.0
        out[i] = alpha * v + (1 - alpha) * out[i - 1]
    return out


def pandas_subset(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the subset that has a polars equivalent — pandas reference."""
    out = pd.DataFrame(index=df.index)
    # ── Returns ─────────────────────────────────────────────────────
    out["ret_1"] = df["close"].pct_change()
    out["ret_5"] = df["close"].pct_change(5)
    out["ret_10"] = df["close"].pct_change(10)
    # ── ATR (Wilder, length=14) — uses _rma_numpy for the smoothing ──
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    out["atr_14"] = _rma_numpy(tr, 14)
    # ── Rolling stats ──────────────────────────────────────────────
    out["volatility_20"] = df["close"].pct_change().rolling(20).std()
    out["sma_20"] = df["close"].rolling(20).mean()
    out["high_14"] = df["high"].rolling(14).max()
    out["low_14"] = df["low"].rolling(14).min()
    # ── Candle shape ──────────────────────────────────────────────
    high_low = df["high"] - df["low"] + 1e-10
    out["body_ratio"] = (df["close"] - df["open"]).abs() / high_low
    out["upper_shadow_ratio"] = (df["high"] - df[["close", "open"]].max(axis=1)) / high_low
    out["lower_shadow_ratio"] = (df[["close", "open"]].min(axis=1) - df["low"]) / high_low
    # ── EMA + distance ─────────────────────────────────────────────
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    out["ema_20"] = ema20
    out["ema_distance"] = (df["close"] - ema20) / ema20
    out["above_ema20"] = (df["close"] > ema20).astype(int)
    # ── Williams %R (14) ──────────────────────────────────────────
    h14 = df["high"].rolling(14).max()
    l14 = df["low"].rolling(14).min()
    out["williams_r"] = -100 * (h14 - df["close"]) / (h14 - l14 + 1e-10)
    # ── Higher high / lower low (5-bar lookback) ───────────────────
    out["higher_high"] = (df["high"].rolling(5).max().shift(1) < df["high"]).astype(int)
    out["lower_low"] = (df["low"].rolling(5).min().shift(1) > df["low"]).astype(int)
    return out


def polars_subset(df_pd: pd.DataFrame) -> pd.DataFrame:
    """Same set of features, computed via polars Lazy expressions."""
    df = pl.from_pandas(df_pd)

    # Build min(open, close) and max(open, close) via polars min_horizontal / max_horizontal
    body_max = pl.max_horizontal(pl.col("open"), pl.col("close"))
    body_min = pl.min_horizontal(pl.col("open"), pl.col("close"))
    high_low_eps = pl.col("high") - pl.col("low") + 1e-10
    ema20 = pl.col("close").ewm_mean(span=20, adjust=False)
    h14 = pl.col("high").rolling_max(window_size=14)
    l14 = pl.col("low").rolling_min(window_size=14)
    prev_close = pl.col("close").shift(1)
    tr = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )
    # ATR uses ewm_mean(alpha=1/14) which pandas_ta confirms is the same
    # as their `rma()` implementation (just `ewm(alpha=alpha,
    # adjust=False).mean()` — see pandas_ta.overlap.rma source).
    atr_14_expr = tr.ewm_mean(alpha=1.0 / 14.0, adjust=False).alias("atr_14")

    out = df.select(
        # Returns
        pl.col("close").pct_change().alias("ret_1"),
        pl.col("close").pct_change(5).alias("ret_5"),
        pl.col("close").pct_change(10).alias("ret_10"),
        # Rolling stats
        pl.col("close").pct_change().rolling_std(window_size=20).alias("volatility_20"),
        pl.col("close").rolling_mean(window_size=20).alias("sma_20"),
        pl.col("high").rolling_max(window_size=14).alias("high_14"),
        pl.col("low").rolling_min(window_size=14).alias("low_14"),
        # Candle shape
        ((pl.col("close") - pl.col("open")).abs() / high_low_eps).alias("body_ratio"),
        ((pl.col("high") - body_max) / high_low_eps).alias("upper_shadow_ratio"),
        ((body_min - pl.col("low")) / high_low_eps).alias("lower_shadow_ratio"),
        # EMA-based
        ema20.alias("ema_20"),
        ((pl.col("close") - ema20) / ema20).alias("ema_distance"),
        (pl.col("close") > ema20).cast(pl.Int64).alias("above_ema20"),
        # Williams %R
        (-100 * (h14 - pl.col("close")) / (h14 - l14 + 1e-10)).alias("williams_r"),
        # Higher high / lower low — fill_null mirrors pandas `(... < ...).astype(int)`
        # which yields 0 for the leading bars where the rolling window is empty.
        (pl.col("high").rolling_max(window_size=5).shift(1) < pl.col("high"))
            .fill_null(False).cast(pl.Int64).alias("higher_high"),
        (pl.col("low").rolling_min(window_size=5).shift(1) > pl.col("low"))
            .fill_null(False).cast(pl.Int64).alias("lower_low"),
        # ATR(14) — Wilder smoothing via polars ewm_mean(alpha=1/14)
        atr_14_expr,
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
