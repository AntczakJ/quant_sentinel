"""
build_triple_barrier_labels.py — CLI wrapper that calls the canonical
`src.learning.labels.triple_barrier_labels` (+ `r_multiple_labels`) library
function and serializes the result to a parquet warehouse.

Use-case: bulk-generate labels for offline training pipelines that prefer
to read from disk (e.g. `train_all.py --target triple_barrier`) rather
than recompute on every run.

Encoding (canonical, matches `src/learning/labels/`):
   1 = TP hit  (winner)
  -1 = SL hit  (loser)
   0 = Time barrier hit (timeout)

Output columns (one row per anchor bar):
    datetime, close, atr,
    label_long, bars_to_exit_long, exit_price_long, r_long,
    label_short, bars_to_exit_short, exit_price_short, r_short

Output path:
    data/historical/labels/triple_barrier_{symbol}_{tf}_tp{N}_sl{N}_max{N}.parquet

The library function is Numba-JIT accelerated when numba is available
(~60x speedup on 100k+ rows). This CLI handles file I/O only — math
lives in `src.learning.labels`.

Usage:
    python tools/build_triple_barrier_labels.py
    python tools/build_triple_barrier_labels.py --tf 5min --tp-atr 2.0 --sl-atr 1.0 --max-holding 60
    python tools/build_triple_barrier_labels.py --tf 15min --max-holding 24
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's ATR — same formula `src/analysis/compute.py` uses for parity."""
    n = len(close)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        a = high[i] - low[i]
        b = abs(high[i] - close[i - 1])
        c = abs(low[i] - close[i - 1])
        tr[i] = max(a, b, c)
    atr = np.zeros(n, dtype=np.float64)
    if n < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def build_labels_df(
    df: pd.DataFrame,
    tp_atr: float = 2.0,
    sl_atr: float = 1.0,
    max_holding: int = 60,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Compute triple-barrier + R-multiple labels for both directions.

    Args:
        df: must contain columns 'datetime', 'open', 'high', 'low', 'close'.
        tp_atr: TP distance in ATR units.
        sl_atr: SL distance in ATR units.
        max_holding: timeout horizon in bars.
        atr_period: Wilder period for ATR (default 14).

    Returns:
        DataFrame with one row per anchor — encoding -1/0/1 (canonical).
    """
    from src.learning.labels import triple_barrier_labels, r_multiple_labels

    required = {"datetime", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {missing}")

    df = df.sort_values("datetime").reset_index(drop=True)

    # Compute ATR ourselves (the library expects an `atr` column).
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    close = df["close"].to_numpy(dtype=np.float64)
    atr = _wilder_atr(high, low, close, atr_period)

    enriched = df.assign(atr=atr)

    tb_both = triple_barrier_labels(
        enriched, direction="both",
        tp_atr=tp_atr, sl_atr=sl_atr, max_horizon_bars=max_holding,
    )
    rm_both = r_multiple_labels(
        enriched, direction="both",
        sl_atr=sl_atr, max_horizon_bars=max_holding,
    )

    # r_multiple_labels with direction='both' returns columns:
    #   r_realized_long, r_mfe_long, r_mae_long, bars_to_sl_long, ...short
    # We want r_realized for the per-direction "what R did this round-trip
    # earn" column. mfe/mae available alongside for richer downstream
    # consumption.
    out = pd.DataFrame({
        # Preserve tz info from input — stripping it via `.values` was the
        # 2026-04-30 join-failure: warehouse df is tz-aware UTC, but
        # `.values` on a tz-aware Series yields naive numpy datetimes,
        # so downstream merge_on='datetime' fails with type mismatch.
        "datetime": df["datetime"].reset_index(drop=True),
        "close": close,
        "atr": atr,
        "label_long": tb_both["label_long"].values,
        "bars_to_exit_long": tb_both["bars_to_exit_long"].values,
        "exit_price_long": tb_both["exit_price_long"].values,
        "r_long": rm_both["r_realized_long"].values,
        "r_mfe_long": rm_both["r_mfe_long"].values,
        "r_mae_long": rm_both["r_mae_long"].values,
        "label_short": tb_both["label_short"].values,
        "bars_to_exit_short": tb_both["bars_to_exit_short"].values,
        "exit_price_short": tb_both["exit_price_short"].values,
        "r_short": rm_both["r_realized_short"].values,
        "r_mfe_short": rm_both["r_mfe_short"].values,
        "r_mae_short": rm_both["r_mae_short"].values,
    })
    return out


def _print_summary(labels: pd.DataFrame, tp_atr: float, sl_atr: float, max_holding: int):
    n = len(labels)
    if n == 0:
        print("[summary] no anchor rows.")
        return
    print(f"\n[summary] {n:,} anchor rows  "
          f"(TP={tp_atr:.1f}*ATR, SL={sl_atr:.1f}*ATR, "
          f"max_holding={max_holding} bars, RR={tp_atr/sl_atr:.2f})")

    for side in ("long", "short"):
        lbl = labels[f"label_{side}"]
        win = (lbl == 1).mean()
        loss = (lbl == -1).mean()
        timeout = (lbl == 0).mean()
        avg_r = labels[f"r_{side}"].mean()
        print(f"  {side.upper():5s}: TP {win*100:5.1f}%  SL {loss*100:5.1f}%  "
              f"TIMEOUT {timeout*100:5.1f}%  avg_R {avg_r:+.3f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tf", default="5min", help="warehouse TF (5min/15min/30min/1h/4h)")
    ap.add_argument("--symbol", default="XAU_USD")
    ap.add_argument("--tp-atr", type=float, default=2.0, help="TP distance in ATR units")
    ap.add_argument("--sl-atr", type=float, default=1.0, help="SL distance in ATR units")
    ap.add_argument("--max-holding", type=int, default=60, help="timeout horizon in bars (default 60 = 5h on 5m)")
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--out", default=None, help="explicit output path (defaults to data/historical/labels/...)")
    args = ap.parse_args()

    src_path = _REPO_ROOT / "data" / "historical" / args.symbol / f"{args.tf}.parquet"
    if not src_path.exists():
        raise FileNotFoundError(src_path)

    print(f"[load] {src_path}")
    df = pd.read_parquet(src_path)
    print(f"  rows: {len(df):,}  range: {df['datetime'].min()} -> {df['datetime'].max()}")

    t0 = time.perf_counter()
    labels = build_labels_df(
        df,
        tp_atr=args.tp_atr,
        sl_atr=args.sl_atr,
        max_holding=args.max_holding,
        atr_period=args.atr_period,
    )
    t1 = time.perf_counter()
    print(f"[build] {len(labels):,} rows in {t1-t0:.1f}s")

    _print_summary(labels, args.tp_atr, args.sl_atr, args.max_holding)

    if args.out:
        out_path = Path(args.out)
    else:
        out_dir = _REPO_ROOT / "data" / "historical" / "labels"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"triple_barrier_{args.symbol}_{args.tf}_tp{args.tp_atr:g}_sl{args.sl_atr:g}_max{args.max_holding}.parquet"
        out_path = out_dir / out_name

    labels.to_parquet(out_path, compression="snappy")
    print(f"[save] {out_path}  ({out_path.stat().st_size / (1024*1024):.1f} MB)")


if __name__ == "__main__":
    main()
