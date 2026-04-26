# Phase 1 — Data Warehouse Scope

**Created:** 2026-04-26 04:00 CEST (post sweep session)
**Status:** scope only; not yet started
**Blocker for:** any honest small-sample work — see `memory/asymmetry_flip_2026-04-26.md`
**Follows:** `docs/strategy/2026-04-25_max_winrate_master_plan.md` Phase 1

## Why this is now top priority

Tonight's sweep produced PF 0.24 baseline on 20 trades / 30 days. Walk-forward 3 windows showed 1 / 4 / 5 trades per window — *zero statistical power*. Every A/B comparison is dominated by sample noise. The "asymmetry flip" finding (LONG/SHORT direction reversed under B1-B5) was only detectable because the 5x WR gap (60% LONG vs 10% SHORT) was large enough to clear the noise floor — but smaller signals are invisible.

Conclusion: tactical iteration on this codebase is bounded by sample size, not by ideas. Until we have ≥500 historical trades to validate against, every "improvement" is a coin flip.

## What we need

A local, reproducible historical database containing 2-3 years of multi-asset OHLCV data + a labels file regenerated from triple-barrier or R-multiple targets. Backtests read from this; ML training reads from this; comparisons fix the data so re-runs are bit-identical.

## Concrete deliverable list

### 1.1 Data fetch script (`scripts/data_collection/fetch_all_history.py`)

- Pulls TwelveData for all symbols listed in `2026-04-25_max_winrate_master_plan.md` §1.1
  (XAU, XAG, USDJPY, EURUSD, UUP, TLT, SPY, BTC, WTI, VXX) at multiple TFs.
- Rate-limit aware: 55 calls/min, 1.2s pacing, retries on transient 5xx.
- Incremental: reads `data/historical/manifest.json`, fetches only since
  `last_fetched`. First run takes ~15 min; subsequent runs ~30 sec.
- Writes parquet partitioned by `{symbol}/{interval}.parquet`.
- Failure mode: partial writes → temp file then atomic rename.

### 1.2 Storage layout

```
data/historical/
  XAU_USD/
    1m.parquet      # 1 year only (storage: ~50MB)
    5m.parquet      # 3 years (~30MB)
    15m.parquet     # 3 years (~10MB)
    30m.parquet     # 3 years (~5MB)
    1h.parquet      # 3 years (~3MB)
    4h.parquet      # 3 years (~1MB)
    1d.parquet      # 5 years (~200KB)
  XAG_USD/
    ... (same TFs subset)
  USDJPY/, EURUSD/, UUP/, TLT/, SPY/, BTC_USD/, WTI/, VXX/
    ... (1h + 1d typically sufficient)
  manifest.json     # last_fetched per (symbol, interval)
```

Total disk: ~150 MB. DuckDB index optional — parquet alone is fast enough.

### 1.3 Backtest provider integration

Modify `src/backtest/historical_provider.py::HistoricalProvider`:
- Add `from_warehouse(symbol, interval)` constructor that reads parquet
  instead of yfinance.
- Existing `from_yfinance` stays for ad-hoc tests.
- `_cache` populated identically — downstream code unchanged.
- Add manifest version bump trigger: regenerate cache if parquet file mtime
  changes since last load.

### 1.4 Macro / FRED fetcher

- `scripts/data_collection/fetch_fred.py`: FFR, CPI, UNRATE, GDP, M2,
  WTISPLC. Daily samples, 5 years. ~10 calls.
- Stored as `data/historical/macro/{series}.parquet`.
- Used by `compute_features` (already supports macro_data; just point at
  warehouse instead of live API).

### 1.5 News calendar archive

Forex Factory JSON endpoint — already used live. Backfill 1 year of
event metadata (date, time, currency, impact tier, actual vs forecast)
into `data/historical/news/{YYYY-MM}.parquet`.

### 1.6 Validation harness

`scripts/data_collection/validate_warehouse.py`:
- Detects gaps (missing bars for non-weekend hours).
- Compares parquet OHLC against TwelveData live for last 24h to catch
  silent drift.
- Reports: rows per symbol/TF, oldest+newest timestamp, gap count.

## Success criteria

- Single command `python scripts/data_collection/fetch_all_history.py`
  brings entire warehouse to current.
- `python run_production_backtest.py --warehouse --days 365` runs against
  parquet, produces ≥300 trades on 1-year window.
- Two consecutive runs of identical config produce bit-identical
  backtest output (true determinism, not just seeded RNG).

## Time estimate

- Code: ~6-8 hours (single sitting)
- First fetch: ~30 min (rate-limit bound)
- Validation + first 1-year backtest: ~2 hours
- Total: 1 working day

## Risks / known gotchas

- TwelveData free tier has a daily call cap. Verify limits before fetch
  marathon to avoid mid-run cutoff.
- yfinance has a known 5m/1m history limit (60 days). Long-history asks
  must go through TwelveData regardless of fallback chain.
- Crypto (BTC) may be the only 24/7 asset; rest have session gaps which
  must be handled in feature engineering (no forward-fill across nights).
- Parquet read-on-load is fast but `_cache` on a 3-year 5m series is
  ~315k rows in memory per asset. With 10 assets = ~3M rows. Fits
  in 16GB but optimize column selection (drop volume on FX).

## Out of scope (for Phase 1 specifically)

- Triple-barrier label regen (Phase 2 in master plan).
- ML retraining on new labels (Phase 4).
- Walk-forward harness rewrite (Phase 5).

## How to start next session

1. Read `docs/strategy/2026-04-25_max_winrate_master_plan.md` §1 for
   the full master plan context.
2. Read this scope doc.
3. Check TwelveData API key is in `.env` (`TWELVE_DATA_API_KEY`).
4. Begin with `scripts/data_collection/fetch_all_history.py` for XAU
   only. Validate the pipeline end-to-end on one asset before fanning
   out to the rest.
