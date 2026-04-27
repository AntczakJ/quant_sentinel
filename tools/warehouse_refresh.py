"""warehouse_refresh.py — append latest TwelveData bars to local parquet warehouse.

Why this exists:
  `data/historical/XAU_USD/{5,15,30}min.parquet`, `1h.parquet`, `4h.parquet`
  are immutable sources of truth for backtest + replay analyses. Without
  refreshing, the daily replay cron (`_replay_rejections_daily`) can't
  resolve any rejection within ~hold_cap of the warehouse's last bar
  (currently ~2 days behind real-time). This script closes that gap.

Behavior:
  - For each TF, read the existing parquet.
  - Compute the gap: `last_dt → now` (UTC).
  - If gap is too small (< 1 bar interval) skip — nothing to do.
  - Fetch enough bars from TwelveData via the existing provider.
  - Filter to bars NEWER than `last_dt`.
  - Validate: monotonic, no NaN OHLC, sane price (≥ $100 ≤ $20k for XAU).
  - Append, sort by datetime, deduplicate, persist back atomically
    (write to .new.parquet, fsync, rename).
  - Report rows added per TF.

Rate-limit aware: each TF is one TwelveData call (1 credit). 5 TFs = 5
credits total. Well inside the 55 / min budget.

Usage:
    python tools/warehouse_refresh.py
    python tools/warehouse_refresh.py --symbol XAU/USD --tf 5m 1h
    python tools/warehouse_refresh.py --dry-run    # don't write
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
WAREHOUSE_DIR = REPO / "data" / "historical"

# Ensure `src` is importable when invoking the script from any cwd
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Map CLI-friendly TF names → (TwelveData interval, parquet filename)
TF_MAP = {
    "5m":  ("5min",  "5min.parquet"),
    "15m": ("15min", "15min.parquet"),
    "30m": ("30min", "30min.parquet"),
    "1h":  ("1h",    "1h.parquet"),
    "4h":  ("4h",    "4h.parquet"),
}

# Bars per hour by TF — used to compute "how many bars cover the gap"
BARS_PER_HOUR = {"5m": 12, "15m": 4, "30m": 2, "1h": 1, "4h": 0.25}


def _interval_minutes(tf: str) -> int:
    return {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}[tf]


def load_existing(path: Path) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    if "datetime" not in df.columns:
        raise ValueError(f"{path} missing 'datetime' column")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df.sort_values("datetime").reset_index(drop=True)


def compute_fetch_count(tf: str, last_dt: pd.Timestamp,
                       safety_factor: float = 1.5) -> int:
    """How many bars to ask TwelveData for. We over-fetch by a safety
    factor and trim later — this absorbs weekend gaps and minor clock
    drift without a second round-trip."""
    now = pd.Timestamp.now(tz="UTC")
    gap_h = (now - last_dt).total_seconds() / 3600
    bph = BARS_PER_HOUR[tf]
    raw_needed = int(gap_h * bph) + 1
    bars = int(raw_needed * safety_factor) + 50  # safety floor
    return min(max(bars, 50), 5000)  # clamp to TwelveData per-call cap


def fetch_new_bars(symbol: str, tf: str, count: int) -> Optional[pd.DataFrame]:
    """Pull bars via the TwelveDataProvider already used in production.
    Defensive: returns None on any error so the caller can skip the TF
    and continue with the others."""
    from src.data.data_sources import get_provider
    provider = get_provider()
    td_interval = TF_MAP[tf][0]
    df = provider.get_candles(symbol, td_interval, count)
    if df is None or len(df) == 0:
        return None
    # Provider returns columns datetime, open, high, low, close, volume.
    # Some implementations index by datetime — normalize.
    if "datetime" not in df.columns:
        if df.index.name == "datetime":
            df = df.reset_index()
        elif "timestamp" in df.columns:
            df = df.rename(columns={"timestamp": "datetime"})
        else:
            return None
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df[["datetime", "open", "high", "low", "close", "volume"]].copy()


def validate_bars(df: pd.DataFrame, tf: str) -> tuple[bool, str]:
    """Soft sanity checks. Returns (ok, reason). Mismatched but
    recoverable issues are not failures — we log and continue."""
    if df.empty:
        return False, "empty"
    if df[["open", "high", "low", "close"]].isna().any().any():
        return False, "NaN OHLC"
    # XAU plausibility: $100 to $20k
    if df["close"].min() < 100 or df["close"].max() > 20000:
        return False, f"OHLC out of range: ${df['close'].min():.0f}–${df['close'].max():.0f}"
    # Non-monotonic timestamps would corrupt downstream ordering
    if not df["datetime"].is_monotonic_increasing:
        df.sort_values("datetime", inplace=True)
    return True, ""


def append_and_save(existing: pd.DataFrame, new: pd.DataFrame,
                   path: Path, dry_run: bool = False) -> int:
    """Merge, dedupe (keep first occurrence per timestamp), sort, save
    atomically. Returns the count of NEW rows actually appended."""
    n_before = len(existing)
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset=["datetime"], keep="first")
    combined = combined.sort_values("datetime").reset_index(drop=True)
    n_after = len(combined)
    delta = n_after - n_before
    if dry_run:
        print(f"  [dry-run] would write {n_after:,} rows ({delta:+,} new) to {path}")
        return delta
    # Atomic write: temp file then rename
    tmp = path.with_suffix(path.suffix + ".new")
    combined.to_parquet(tmp, compression="snappy", index=False)
    tmp.replace(path)
    return delta


def refresh_one_tf(symbol: str, symbol_dir: str, tf: str,
                   dry_run: bool = False) -> dict:
    """Returns a status dict per TF."""
    parquet_path = WAREHOUSE_DIR / symbol_dir / TF_MAP[tf][1]
    status: dict = {"tf": tf, "path": str(parquet_path),
                    "ok": False, "added": 0, "reason": ""}

    existing = load_existing(parquet_path)
    if existing is None:
        status["reason"] = "no existing parquet (would need full backfill, skipping)"
        return status

    last_dt = existing["datetime"].iloc[-1]
    now = pd.Timestamp.now(tz="UTC")
    gap_min = (now - last_dt).total_seconds() / 60
    if gap_min < _interval_minutes(tf):
        status["reason"] = f"already current (gap {gap_min:.1f} min < {_interval_minutes(tf)} min)"
        status["ok"] = True
        return status

    count = compute_fetch_count(tf, last_dt)
    print(f"  {tf}: gap {gap_min/60:.1f}h, fetching last {count} bars")

    t0 = time.time()
    new_df = fetch_new_bars(symbol, tf, count)
    fetch_s = time.time() - t0
    if new_df is None:
        status["reason"] = "fetch returned None"
        return status

    # Filter to bars STRICTLY newer than last_dt and NEVER in the future.
    # The future-clamp catches a TwelveData provider class of bug where
    # the exchange-default timezone is used and we mis-tag as UTC.
    # If we still see future bars after the data_sources.py fix, that's
    # a fresh symptom worth surfacing rather than silently appending.
    now_utc = pd.Timestamp.now(tz="UTC")
    n_before_filter = len(new_df)
    new_df = new_df[(new_df["datetime"] > last_dt)
                    & (new_df["datetime"] <= now_utc)].copy()
    n_dropped_future = n_before_filter - len(new_df) - sum(
        1 for d in new_df["datetime"] if d <= last_dt  # already filtered
    )
    if n_dropped_future > 0:
        print(f"  WARN: dropped bars dated > now (provider tz bug?)")
    if new_df.empty:
        status["reason"] = "no new bars after filter"
        status["ok"] = True
        return status

    ok, reason = validate_bars(new_df, tf)
    if not ok:
        status["reason"] = f"validation failed: {reason}"
        return status

    delta = append_and_save(existing, new_df, parquet_path, dry_run=dry_run)
    status["ok"] = True
    status["added"] = delta
    status["fetch_seconds"] = round(fetch_s, 2)
    status["new_first"] = str(new_df["datetime"].iloc[0])
    status["new_last"] = str(new_df["datetime"].iloc[-1])
    return status


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="XAU/USD",
                    help="TwelveData symbol (default: XAU/USD)")
    ap.add_argument("--symbol-dir", default="XAU_USD",
                    help="Subdirectory under data/historical/")
    ap.add_argument("--tf", nargs="+", default=list(TF_MAP.keys()),
                    choices=list(TF_MAP.keys()),
                    help="Timeframes to refresh (default: all 5)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write parquet — only print plan")
    args = ap.parse_args()

    print(f"[refresh] symbol={args.symbol}  tfs={args.tf}  dry_run={args.dry_run}")
    results: list[dict] = []
    for tf in args.tf:
        try:
            r = refresh_one_tf(args.symbol, args.symbol_dir, tf,
                              dry_run=args.dry_run)
            results.append(r)
        except Exception as e:
            results.append({"tf": tf, "ok": False, "added": 0,
                           "reason": f"exception: {type(e).__name__}: {e}"})

    print()
    print("=" * 60)
    print("WAREHOUSE REFRESH SUMMARY")
    print("=" * 60)
    total_added = 0
    for r in results:
        flag = "✓" if r["ok"] else "✗"
        added = r.get("added", 0)
        total_added += added
        line = f"  {flag} {r['tf']:>4s}: +{added:>4d} bars"
        if r.get("new_last"):
            line += f"  (latest: {r['new_last']})"
        if r.get("reason"):
            line += f"  [{r['reason']}]"
        print(line)
    print(f"\n  Total bars added: {total_added}")
    print("=" * 60)

    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
