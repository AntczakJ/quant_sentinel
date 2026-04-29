"""
build_triple_barrier_labels.py — replace binary 0.5-ATR-in-5-bars target with
triple-barrier labels (TP / SL / TIMEOUT) per López de Prado.

For each anchor bar t we simulate a hypothetical entry at close[t]:

  LONG:
    TP_long = close[t] + tp_atr * ATR[t]
    SL_long = close[t] - sl_atr * ATR[t]
  SHORT (mirror):
    TP_short = close[t] - tp_atr * ATR[t]
    SL_short = close[t] + sl_atr * ATR[t]

We then walk forward up to `max_holding_bars` bars. The first barrier crossed
determines the label:

  - WIN     (label=1): TP touched first         -> R = tp_atr / sl_atr
  - LOSS    (label=0): SL touched first         -> R = -1.0
  - TIMEOUT (label=2): neither touched in N     -> R = (close[t+N] - close[t]) / (sl_atr * ATR[t])

Two ambiguous-bar cases are resolved conservatively:
  - both TP and SL hit on the same bar  -> LOSS  (worst-case fill assumption)

Output per anchor bar t (one parquet row):

    timestamp, close, atr,
    long_label, long_r, long_exit_offset,
    short_label, short_r, short_exit_offset

Output path:
    data/historical/labels/triple_barrier_{TF}_tp{tp}_sl{sl}_max{N}.parquet

Numba JIT (when available) accelerates the inner walk-forward kernel ~60x;
falls back to pure-numpy for portability.

Usage:
    python tools/build_triple_barrier_labels.py
    python tools/build_triple_barrier_labels.py --tf 5min --tp-atr 2.0 --sl-atr 1.0 --max-holding 60
    python tools/build_triple_barrier_labels.py --tf 15min --max-holding 30
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


WIN, LOSS, TIMEOUT = 1, 0, 2


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's ATR — same formula as src.analysis.compute uses for parity."""
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


try:
    from numba import njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False
    def njit(*args, **kwargs):  # type: ignore[no-redef]
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return lambda f: f


@njit(cache=True)
def _walk_forward_kernel(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    atr: np.ndarray,
    tp_atr: float,
    sl_atr: float,
    max_holding: int,
):
    """Compute triple-barrier labels for both LONG and SHORT in one pass.

    Returns 6 parallel arrays (length = n):
        long_label, long_r, long_exit_offset,
        short_label, short_r, short_exit_offset
    """
    n = len(close)
    long_label = np.full(n, -1, dtype=np.int8)
    short_label = np.full(n, -1, dtype=np.int8)
    long_r = np.full(n, np.nan, dtype=np.float64)
    short_r = np.full(n, np.nan, dtype=np.float64)
    long_exit = np.full(n, -1, dtype=np.int32)
    short_exit = np.full(n, -1, dtype=np.int32)

    rr = tp_atr / sl_atr if sl_atr > 0 else 1.0

    for t in range(n - max_holding):
        a = atr[t]
        if not np.isfinite(a) or a <= 0:
            continue
        c0 = close[t]

        tp_long = c0 + tp_atr * a
        sl_long = c0 - sl_atr * a
        tp_short = c0 - tp_atr * a
        sl_short = c0 + sl_atr * a

        long_resolved = False
        short_resolved = False

        for k in range(1, max_holding + 1):
            ti = t + k
            h = high[ti]
            l = low[ti]

            # ── LONG side ──
            if not long_resolved:
                tp_hit = h >= tp_long
                sl_hit = l <= sl_long
                if tp_hit and sl_hit:
                    # Same-bar ambiguity: resolve to LOSS (worst-case slippage)
                    long_label[t] = LOSS
                    long_r[t] = -1.0
                    long_exit[t] = k
                    long_resolved = True
                elif tp_hit:
                    long_label[t] = WIN
                    long_r[t] = rr
                    long_exit[t] = k
                    long_resolved = True
                elif sl_hit:
                    long_label[t] = LOSS
                    long_r[t] = -1.0
                    long_exit[t] = k
                    long_resolved = True

            # ── SHORT side ──
            if not short_resolved:
                tp_hit_s = l <= tp_short
                sl_hit_s = h >= sl_short
                if tp_hit_s and sl_hit_s:
                    short_label[t] = LOSS
                    short_r[t] = -1.0
                    short_exit[t] = k
                    short_resolved = True
                elif tp_hit_s:
                    short_label[t] = WIN
                    short_r[t] = rr
                    short_exit[t] = k
                    short_resolved = True
                elif sl_hit_s:
                    short_label[t] = LOSS
                    short_r[t] = -1.0
                    short_exit[t] = k
                    short_resolved = True

            if long_resolved and short_resolved:
                break

        # Timeouts
        if not long_resolved:
            long_label[t] = TIMEOUT
            long_r[t] = (close[t + max_holding] - c0) / (sl_atr * a)
            long_exit[t] = max_holding
        if not short_resolved:
            short_label[t] = TIMEOUT
            short_r[t] = (c0 - close[t + max_holding]) / (sl_atr * a)
            short_exit[t] = max_holding

    return long_label, long_r, long_exit, short_label, short_r, short_exit


def build_labels(
    df: pd.DataFrame,
    tp_atr: float = 2.0,
    sl_atr: float = 1.0,
    max_holding: int = 60,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Compute triple-barrier labels for the supplied OHLC dataframe.

    Args:
        df: must contain columns 'datetime', 'open', 'high', 'low', 'close'.
        tp_atr: TP distance in ATR units.
        sl_atr: SL distance in ATR units.
        max_holding: timeout horizon in bars.
        atr_period: Wilder period for ATR (default 14).

    Returns:
        DataFrame indexed by anchor row (same length as df) with the 6 label
        columns + close/atr passthrough. Anchors with insufficient lookahead or
        zero ATR are kept with sentinel label=-1.
    """
    required = {"datetime", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {missing}")

    df = df.sort_values("datetime").reset_index(drop=True)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    close = df["close"].to_numpy(dtype=np.float64)
    atr = _wilder_atr(high, low, close, atr_period)

    long_lbl, long_r, long_exit, short_lbl, short_r, short_exit = _walk_forward_kernel(
        close, high, low, atr, tp_atr, sl_atr, max_holding
    )

    out = pd.DataFrame({
        "datetime": df["datetime"].values,
        "close": close,
        "atr": atr,
        "long_label": long_lbl,
        "long_r": long_r,
        "long_exit_offset": long_exit,
        "short_label": short_lbl,
        "short_r": short_r,
        "short_exit_offset": short_exit,
    })
    return out


def _print_summary(labels: pd.DataFrame, tp_atr: float, sl_atr: float, max_holding: int):
    valid = labels[labels["long_label"] >= 0]
    n = len(valid)
    if n == 0:
        print("[summary] no valid anchor rows — check ATR / max_holding.")
        return
    print(f"\n[summary] valid anchors: {n:,} of {len(labels):,}")
    print(f"  config: TP={tp_atr:.1f}*ATR, SL={sl_atr:.1f}*ATR, max_holding={max_holding} bars (RR={tp_atr/sl_atr:.2f})")

    for side in ("long", "short"):
        lbl = valid[f"{side}_label"]
        win = (lbl == WIN).mean()
        loss = (lbl == LOSS).mean()
        timeout = (lbl == TIMEOUT).mean()
        avg_r = valid[f"{side}_r"].mean()
        ev = win * (tp_atr / sl_atr) - loss * 1.0 + timeout * valid.loc[lbl == TIMEOUT, f"{side}_r"].mean() if timeout > 0 else win * (tp_atr / sl_atr) - loss * 1.0
        print(f"  {side.upper():5s}: TP {win*100:5.1f}%  SL {loss*100:5.1f}%  TIMEOUT {timeout*100:5.1f}%  avg_R {avg_r:+.3f}")
    print()


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

    if not _HAS_NUMBA:
        print("[warn] numba not available — using pure-numpy kernel (~60x slower)")

    t0 = time.perf_counter()
    labels = build_labels(
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
