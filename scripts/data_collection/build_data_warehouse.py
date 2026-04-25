#!/usr/bin/env python3
"""
build_data_warehouse.py — Multi-asset, multi-TF historical data fetcher.

Fetches 2-3 years of OHLCV across 10 symbols × 7 TFs from TwelveData,
respecting 55/min rate limit, with incremental update support.

Output: data/historical/{symbol}/{interval}.parquet (partitioned by month)
        data/historical/manifest.json (last-fetched timestamps)

Usage:
    python scripts/data_collection/build_data_warehouse.py
    python scripts/data_collection/build_data_warehouse.py --symbols XAU/USD,USDJPY
    python scripts/data_collection/build_data_warehouse.py --years 5 --resume
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TWELVE_DATA_API_KEY")
if not API_KEY:
    print("ERROR: TWELVE_DATA_API_KEY not set", file=sys.stderr)
    sys.exit(1)

API_BASE = "https://api.twelvedata.com"
RATE_LIMIT_PER_MIN = 55
PER_REQUEST_DELAY = 60.0 / RATE_LIMIT_PER_MIN * 1.1  # ~1.2s safety margin

WAREHOUSE_DIR = Path("data/historical")
MANIFEST_PATH = WAREHOUSE_DIR / "manifest.json"

# ─────────────────────────────────────────────────────────────────────
# SYMBOL CONFIG
# ─────────────────────────────────────────────────────────────────────
SYMBOLS_CONFIG = {
    # symbol: (twelvedata_symbol, timeframes_to_fetch)
    "XAU/USD":   ("XAU/USD",   ["5min", "15min", "30min", "1h", "4h", "1day"]),
    "XAG/USD":   ("XAG/USD",   ["15min", "1h", "4h", "1day"]),
    "USD/JPY":   ("USD/JPY",   ["15min", "1h", "1day"]),
    "EUR/USD":   ("EUR/USD",   ["15min", "1h", "1day"]),
    "DXY":       ("DXY",       ["1h", "1day"]),  # may not exist on free tier
    "TLT":       ("TLT",       ["1h", "1day"]),  # 20-year treasury ETF
    "SPY":       ("SPY",       ["1h", "1day"]),
    "BTC/USD":   ("BTC/USD",   ["1h", "4h", "1day"]),
    "WTI/USD":   ("WTI/USD",   ["1h", "1day"]),
    "VIX":       ("VIX",       ["1day"]),  # only daily for VIX index (often unavailable)
    "VIXY":      ("VIXY",      ["1h", "1day"]),  # ProShares VIX Short-Term ETF (proxy when VIX direct fails)
}

# Bars per call cap from TwelveData
MAX_BARS_PER_CALL = 5000

# Approximate bars per day per timeframe (for chunking)
BARS_PER_DAY = {
    "1min":  60 * 24,
    "5min":  60 * 24 / 5,
    "15min": 60 * 24 / 15,
    "30min": 60 * 24 / 30,
    "1h":    24,
    "4h":    6,
    "1day":  1,
}


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITER (simple token bucket)
# ─────────────────────────────────────────────────────────────────────
class RateLimiter:
    """Sliding-window rate limiter — never exceed N calls in 60s."""

    def __init__(self, calls_per_min: int):
        self.calls_per_min = calls_per_min
        self.call_times: list[float] = []

    def wait(self) -> float:
        """Block until safe to make next call. Returns seconds waited."""
        now = time.time()
        # Drop calls older than 60s
        self.call_times = [t for t in self.call_times if now - t < 60.0]

        if len(self.call_times) >= self.calls_per_min:
            # Wait until oldest call is 60s old
            oldest = self.call_times[0]
            wait_time = 60.0 - (now - oldest) + 0.5  # +0.5s safety
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
                self.call_times = [t for t in self.call_times if now - t < 60.0]
            return wait_time

        # Otherwise enforce minimum delay between calls
        if self.call_times:
            elapsed_since_last = now - self.call_times[-1]
            if elapsed_since_last < PER_REQUEST_DELAY:
                wait_time = PER_REQUEST_DELAY - elapsed_since_last
                time.sleep(wait_time)
                return wait_time
        return 0.0

    def record(self) -> None:
        self.call_times.append(time.time())


# ─────────────────────────────────────────────────────────────────────
# MANIFEST
# ─────────────────────────────────────────────────────────────────────
def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


# ─────────────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────────────
def fetch_chunk(
    rate_limiter: RateLimiter,
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """Fetch a single chunk of OHLCV data."""
    rate_limiter.wait()

    params = {
        "symbol": symbol,
        "interval": interval,
        "start_date": start_date,
        "end_date": end_date,
        "outputsize": MAX_BARS_PER_CALL,
        "apikey": API_KEY,
        "format": "JSON",
        "timezone": "UTC",
    }
    try:
        r = requests.get(f"{API_BASE}/time_series", params=params, timeout=15)
        rate_limiter.record()
        if r.status_code == 429:
            print(f"  429 rate limit hit — waiting 60s")
            time.sleep(60)
            return fetch_chunk(rate_limiter, symbol, interval, start_date, end_date)
        if r.status_code != 200:
            print(f"  ERROR {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
    except requests.exceptions.RequestException as e:
        print(f"  Network error: {e}")
        return None

    if data.get("status") == "error":
        print(f"  API error: {data.get('message')}")
        return None
    if "values" not in data or not data["values"]:
        return None

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    else:
        df["volume"] = 0
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def chunk_date_ranges(
    start: datetime, end: datetime, interval: str
) -> Iterator[tuple[str, str]]:
    """Yield (start_date, end_date) chunks that fit within MAX_BARS_PER_CALL."""
    bars_per_day = BARS_PER_DAY[interval]
    # Each chunk should be ~MAX_BARS_PER_CALL bars to maximize efficiency
    days_per_chunk = max(1, int(MAX_BARS_PER_CALL / bars_per_day))
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=days_per_chunk), end)
        yield (
            cursor.strftime("%Y-%m-%d %H:%M:%S"),
            chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        cursor = chunk_end


def fetch_symbol_tf(
    rate_limiter: RateLimiter,
    label: str,
    td_symbol: str,
    interval: str,
    years: int,
    manifest: dict,
    resume: bool,
) -> tuple[int, int]:
    """
    Fetch full history for one symbol × interval.
    Returns (rows_fetched, api_calls).
    """
    safe_label = label.replace("/", "_")
    out_dir = WAREHOUSE_DIR / safe_label
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{interval}.parquet"

    end_date = datetime.now(timezone.utc).replace(microsecond=0)
    full_start = end_date - timedelta(days=years * 365)

    # Resume: pick up from last saved timestamp
    manifest_key = f"{label}/{interval}"
    if resume and manifest_key in manifest:
        last_fetched = pd.Timestamp(manifest[manifest_key])
        if last_fetched.tzinfo is None:
            last_fetched = last_fetched.tz_localize("UTC")
        start_date = max(full_start, last_fetched.to_pydatetime())
        print(f"  Resuming from {start_date.isoformat()}")
    else:
        start_date = full_start

    if start_date >= end_date:
        print(f"  Nothing to fetch (already up to date)")
        return 0, 0

    all_chunks = []
    api_calls = 0
    for chunk_start, chunk_end in chunk_date_ranges(start_date, end_date, interval):
        df = fetch_chunk(rate_limiter, td_symbol, interval, chunk_start, chunk_end)
        api_calls += 1
        if df is not None and len(df):
            all_chunks.append(df)
            print(f"    chunk {chunk_start[:10]} ->{chunk_end[:10]}: {len(df)} bars")
        else:
            print(f"    chunk {chunk_start[:10]} ->{chunk_end[:10]}: empty")

    if not all_chunks:
        return 0, api_calls

    new_data = pd.concat(all_chunks, ignore_index=True).drop_duplicates(
        subset=["datetime"]
    ).sort_values("datetime").reset_index(drop=True)

    # Merge with existing
    if out_file.exists():
        existing = pd.read_parquet(out_file)
        merged = pd.concat([existing, new_data], ignore_index=True)
        merged = merged.drop_duplicates(subset=["datetime"]).sort_values(
            "datetime"
        ).reset_index(drop=True)
    else:
        merged = new_data

    merged.to_parquet(out_file, index=False, compression="snappy")
    manifest[manifest_key] = merged["datetime"].iloc[-1].isoformat()
    save_manifest(manifest)
    return len(new_data), api_calls


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="all", help="comma-separated, or 'all'")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--resume", action="store_true",
                    help="skip already-fetched data based on manifest")
    ap.add_argument("--tfs", default="all",
                    help="comma-separated TFs, or 'all'")
    args = ap.parse_args()

    # Filter symbols
    if args.symbols == "all":
        symbols = list(SYMBOLS_CONFIG.keys())
    else:
        symbols = [s.strip() for s in args.symbols.split(",")]

    rate_limiter = RateLimiter(RATE_LIMIT_PER_MIN)
    manifest = load_manifest()

    total_rows = 0
    total_calls = 0
    t_start = time.time()
    skipped = []

    for label in symbols:
        if label not in SYMBOLS_CONFIG:
            print(f"\n=== SKIP {label} (not in config) ===")
            continue
        td_symbol, tfs = SYMBOLS_CONFIG[label]
        if args.tfs != "all":
            wanted_tfs = [t.strip() for t in args.tfs.split(",")]
            tfs = [t for t in tfs if t in wanted_tfs]

        print(f"\n=== {label} ({td_symbol}) — TFs: {tfs} ===")
        for tf in tfs:
            print(f"  TF {tf}:")
            try:
                rows, calls = fetch_symbol_tf(
                    rate_limiter, label, td_symbol, tf,
                    args.years, manifest, args.resume,
                )
                total_rows += rows
                total_calls += calls
                print(f"  ->{rows} new rows, {calls} API calls")
            except Exception as e:
                print(f"  EXCEPTION on {label}/{tf}: {e}")
                skipped.append(f"{label}/{tf}: {e}")

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"DONE — {total_rows} total rows, {total_calls} API calls")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"Manifest: {MANIFEST_PATH}")
    if skipped:
        print(f"\nSKIPPED ({len(skipped)}):")
        for s in skipped:
            print(f"  - {s}")


if __name__ == "__main__":
    main()
