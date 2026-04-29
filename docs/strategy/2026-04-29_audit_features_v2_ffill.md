# features_v2 Temporal Leak Audit — 2026-04-29

Auditor: Claude (read-only research pass).
Scope: every ffill / multi-TF join / asof / merge / shift in
`src/analysis/features_v2.py`, plus the `compute.py` USDJPY join and the
inference path in `src/ml/ensemble_models.py::predict_v2_xgb_direction`.
No production code modified.

## TL;DR

`v2_xgb` (LIVE @ weight 0.10, claimed PF 2.24 OOS) is contaminated by
**three CRITICAL temporal leaks** in `features_v2.py` and one in
`compute.py` (USDJPY). All four exhibit the same root cause:
**warehouse parquets label bars by their START timestamp**, but our
ffill+reindex semantically asks "what value was available AT this
timestamp?". A 5m XAU bar at 14:30 ffilled to a 1h cross-asset row
labeled `14:00` reads a `close` that materializes at 15:00 — **+30 min
look-ahead**. Worse, the cross-asset stream is hard-coded to `1h`
regardless of inference TF (line 320), and `_align_to_index` ffills
without ever shifting, so this leak hits every cross-asset feature
(XAG, EURUSD, TLT, SPY, BTC, VIX) and every higher-TF feature
(`h1_*`, `h4_*`, `d1_*`).

**Recommendation:** mute `v2_xgb` (set weight 0.0 in `_get_voter_weights`)
until the four shifts below land and the per-direction walk-forward is
re-run. PF 2.24 is contaminated and cannot be trusted as-is.

---

## Ranked leak sites

| # | File:Line | Severity | Mechanism (one-line) | Fix |
|---|-----------|----------|----------------------|-----|
| 1 | `src/analysis/features_v2.py:235` | CRITICAL | Higher-TF (1h/4h/1d) feature ffilled onto 5m by start-stamp; `h1_close@14:00` actually closes at 15:00 → up to **+55 min** look-ahead on 5m, **+3h55m** on 4h | Shift HTF index by **+1 TF interval** before reindex (e.g. `tf_indexed.shift(1, freq='1h')` for 1h) |
| 2 | `src/analysis/features_v2.py:117` (`_align_to_index`) | CRITICAL | Generic cross-asset ffill helper; same start-stamp issue. Cross-asset is **hard-coded `1h`** at line 320 → consistent **+1h leak** on all 5m/15m/30m bars; +0 leak on 1h-anchored | Shift cross-asset df by **+1 cross-asset TF** before `reindex(...)` (e.g. `s.shift(1, freq='1h')` for 1h cross-asset) |
| 3 | `src/analysis/compute.py:873` | CRITICAL | USDJPY ffill onto XAU index; mirrors leak #2. Inference always pulls USDJPY @ 1h (`ensemble_models.py:314`) regardless of XAU TF, so a 5m XAU bar at 14:30 reads USDJPY close that materializes at 15:00 → **+30 min** | Shift USDJPY by **+1 USDJPY-TF** before reindex; also fetch USDJPY at the *same* TF as XAU |
| 4 | `src/ml/ensemble_models.py:314` | IMPORTANT (train/infer mismatch) | Inference fetches USDJPY @ `'1h'` constant; training is also 1h via yfinance JPY=X (`train_all.py:194`) — but XAU inference TF is 5m/15m/30m/4h. Distribution mismatch on top of leak #3 | Pass scanner TF into `_fetch_live_usdjpy(tf=...)`; standardize on TwelveData warehouse for train+infer parity |
| 5 | `src/analysis/indicators.py:16` | NICE | `chikou_span = df['close'].shift(-kijun)` is a **negative shift** = explicit future leak. Currently *unused* by features_v2 / scanner (only `senkou_span_a/b` consumed), so no live impact today | Drop column or rename `chikou_span_future_LEAK` so future devs notice |

### Detailed entry — #1 multi-TF projection (`features_v2.py:235`)

```python
# features_v2.py:232-238
for feat in target_features:
    col_name = f"{prefix}_{feat}"
    if feat in tf_indexed.columns:
        projected = tf_indexed[feat].reindex(df.index, method="ffill")
        df[col_name] = projected.fillna(0)
```

`tf_indexed` is e.g. the 1h XAU DataFrame already passed through
`compute_features` upstream. Index entries are start-of-bar timestamps
(verified: warehouse parquets are written from `data_sources.py:194`
`pd.to_datetime(df['datetime'], utc=True)`, which the TwelveData docs
confirm is bar-open). `df.index` is 5m start-of-bar timestamps.

Concrete walk-through:
- `df.index[k]` = `2026-03-15 14:30:00`
- Most recent 1h row with index ≤ `14:30` is `14:00:00`
- The 1h `14:00` row's `rsi`, `atr`, `close`, `macd`, etc. are
  computed from prices through end-of-bar = **15:00:00**
- 5m bar's `h1_rsi` therefore "knows" the price at `15:00` while we
  pretend we're at `14:30`. **+30 min look-ahead.**

The leak compounds with TF:
- 5m anchored on 4h: a 5m bar at `00:05` reads `h4_*` from the 4h bar
  labeled `00:00` whose close is at `04:00` → **+3h55m** look-ahead
- 5m anchored on 1d: a 5m bar at `00:05` reads `d1_*` from the daily
  bar labeled `00:00` whose close is at `+24h` → **+23h55m** look-ahead

Severity: **CRITICAL — PRICE-BASED FUTURE.** `h1_atr`, `h1_rsi`,
`d1_above_ema20`, `d1_trend_strength` are all derivatives of close
which materializes in the future. v2_xgb's published PF is suspect.

### Detailed entry — #2 cross-asset projection (`features_v2.py:117`)

```python
# features_v2.py:99-117  _align_to_index
def _align_to_index(other_df, target_index, col="close"):
    ...
    if "datetime" in other_df.columns:
        s = other_df.set_index("datetime")[col].sort_index()
    else:
        s = other_df[col].sort_index()
    ...
    return s.reindex(target_index, method="ffill")
```

Hard-coded interval at the call site:

```python
# features_v2.py:317-320  compute_features_v2
if higher_tf_dfs is None:
    higher_tf_dfs = load_higher_tf_warehouse("XAU/USD")
if cross_asset_dfs is None:
    cross_asset_dfs = load_cross_asset_warehouse("1h")  # ← hard 1h
```

Same mechanism as leak #1 but for cross-asset closes (XAG, EUR, TLT,
SPY, BTC, VIX). `xag_corr_20`, `xag_ret_5`, `xag_zscore_20`,
`eurusd_*`, `tlt_*`, `spy_*`, `btc_*`, `vix_*` — **13 of 13 cross-asset
features** are leaked. On a 5m XAU bar at `14:30`, every one of them
reads the cross-asset bar that closes at `15:00`.

Severity: **CRITICAL — PRICE-BASED FUTURE** (most are price returns/zscores;
`vix_level` is a regime-future).

### Detailed entry — #3 USDJPY ffill (`compute.py:873`)

```python
# compute.py:870-882
if usdjpy_df is not None and len(usdjpy_df) >= 20 and 'close' in usdjpy_df.columns:
    try:
        uj = usdjpy_df['close'].reindex(df.index, method='ffill')
        uj_mean = uj.rolling(20).mean()
        uj_std = uj.rolling(20).std()
        df['usdjpy_zscore_20'] = ((uj - uj_mean) / (uj_std + 1e-10)).fillna(0).clip(-5, 5)
        df['usdjpy_ret_5'] = uj.pct_change(5).fillna(0).clip(-0.1, 0.1)
        df['xau_usdjpy_corr_20'] = df['close'].rolling(20).corr(uj).fillna(0)
```

Identical to #2 but for USDJPY. Inference path
(`ensemble_models.py:314`) hard-codes 1h USDJPY regardless of XAU TF
→ same +30 min on 5m, +1h on 30m, etc.

Severity: **CRITICAL — PRICE-BASED FUTURE** for `usdjpy_zscore_20`,
`usdjpy_ret_5`, `xau_usdjpy_corr_20`.

### Detailed entry — #4 inference TF mismatch + source mismatch (`ensemble_models.py:314`)

```python
# ensemble_models.py:303-319
def _fetch_live_usdjpy(limit: int = 200) -> Optional[pd.DataFrame]:
    try:
        from src.data.data_sources import get_provider
        provider = get_provider()
        uj_df = provider.get_candles('USD/JPY', '1h', limit)  # always 1h
```

Two leaks ride together:
1. **Source drift:** training uses yfinance JPY=X (`train_all.py:194`),
   inference uses TwelveData USD/JPY. Bar boundaries and tick feeds
   differ. `usdjpy_zscore_20` distribution at training time ≠ at
   inference time, even before fix #3 lands.
2. **TF mismatch reinforces leak #3:** scanner cascade is
   `5m/15m/30m/1h/4h`. For everything except 1h, the 1h USDJPY ffill
   crosses bar boundaries → live 5m bar at 14:30 sees USDJPY close at
   15:00.

Severity: **IMPORTANT** (degrades inference even after #3 is fixed).

### Other patterns checked — clean

- **No `pd.merge_asof` calls** anywhere in `features_v2.py` or
  `compute.py`. (Grepped the entire `src/` tree.)
- **No `.shift(-N)`** in `features_v2.py`. The only negative shifts in
  `src/` are:
  - `compute.py:911-912` — these are TARGET computation
    (`future_max`, `future_min`), NOT features. Correct usage; the
    target *should* look forward.
  - `indicators.py:16` `chikou_span` — see leak #5 (unused but
    foot-gun).
- **No `.shift(0)`** anywhere. (Trivially a no-op anyway.)
- **`_safe_zscore`, `_safe_corr`, `_safe_returns`** all use
  `s.rolling(window, ...).{mean,std,corr}()` and `s.pct_change(periods)`.
  Pandas rolling with default `closed='right'` and pct_change with
  positive periods are both **backward-only** by spec. ✔
- **`compute_features_v2` step 1** (line 323) calls
  `compute_features(df, usdjpy_df=usdjpy_df)`. The base v1 features
  there (RSI, MACD, ATR, EMA, ADX, VWAP, vol percentile, trend
  strength, candlestick patterns, ichimoku senkou_a/b, williams %R,
  CCI) all use backward-only windows. The leak in `compute.py` is
  only in the USDJPY block (#3).
- **Step 2 of `compute_features_v2`** (`add_cross_asset_features`)
  calls `_align_to_index` which is leak #2. Inherited.
- **Step 3** (`add_multi_tf_features`) is leak #1. Inherited.

---

## Drop-in patch — leak #1 (most critical, hits every multi-TF feature)

Below is a ready-to-paste replacement for the body of
`add_multi_tf_features` in `src/analysis/features_v2.py`. The diff is
a single line of new logic per TF (`tf_indexed = tf_indexed.shift(1, freq=...)`)
plus a TF→pandas-offset map.

```python
def add_multi_tf_features(
    df: pd.DataFrame,
    higher_tf_dfs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Add features from higher TFs projected onto current df's timestamps.

    LEAK FIX (2026-04-29): warehouse parquets label bars by START time.
    A 1h bar labeled `14:00` carries close/rsi/atr that materialize at
    `15:00`. Naïve `reindex(method='ffill')` therefore lets the 5m bar
    at `14:30` peek at data from `15:00` — a +30 min look-ahead.

    Fix: shift each HTF dataframe forward by exactly one HTF bar before
    ffill. After the shift, the row labeled `15:00` carries the data
    that was actually closed at `15:00`, so a 5m bar at `14:30` ffills
    backward to `14:00` whose data is the close at `14:00`. No future
    leak.

    Args:
        df: current TF dataframe (typically 5m)
        higher_tf_dfs: dict like {'1h': df_1h, '4h': df_4h, '1d': df_1d}
            (each must have features computed via compute_features).
    """
    if df.index.name != "datetime" and "datetime" in df.columns:
        df = df.set_index("datetime")

    tf_prefix_map = {"1h": "h1", "4h": "h4", "1d": "d1"}
    # pandas offset for each TF — used to shift HTF index forward by ONE bar
    tf_offset_map = {
        "1h": pd.Timedelta(hours=1),
        "4h": pd.Timedelta(hours=4),
        "1d": pd.Timedelta(days=1),
        "1day": pd.Timedelta(days=1),
    }

    for tf_label, tf_df in higher_tf_dfs.items():
        prefix = tf_prefix_map.get(tf_label, tf_label)
        if tf_df is None or len(tf_df) == 0:
            continue
        if "datetime" in tf_df.columns:
            tf_indexed = tf_df.set_index("datetime").sort_index()
        else:
            tf_indexed = tf_df.sort_index()

        # ── LEAK FIX: align bar TIMESTAMP with bar CLOSE TIME ──
        offset = tf_offset_map.get(tf_label)
        if offset is not None:
            # Shifting the INDEX forward by one bar makes index[i] equal
            # to the bar's close time instead of its open time.
            tf_indexed = tf_indexed.copy()
            tf_indexed.index = tf_indexed.index + offset

        target_features = {
            "h1": ["rsi", "atr", "above_ema20", "trend_strength",
                   "macd", "volatility_percentile"],
            "h4": ["rsi", "atr", "above_ema20", "trend_strength"],
            "d1": ["rsi", "above_ema20", "trend_strength"],
        }.get(prefix, [])

        for feat in target_features:
            col_name = f"{prefix}_{feat}"
            if feat in tf_indexed.columns:
                # ffill now correctly returns the value of the most
                # recently CLOSED HTF bar at-or-before the target ts.
                projected = tf_indexed[feat].reindex(df.index, method="ffill")
                df[col_name] = projected.fillna(0)
            else:
                df[col_name] = 0.0

    return df
```

### Companion fix — leak #2 (`_align_to_index`)

```python
def _align_to_index(other_df: pd.DataFrame, target_index: pd.DatetimeIndex,
                    col: str = "close",
                    bar_offset: pd.Timedelta = pd.Timedelta(hours=1)) -> pd.Series:
    """
    Reindex other_df[col] to target_index using forward-fill.

    LEAK FIX (2026-04-29): cross-asset warehouse parquets label bars by
    START time. To avoid the 5m@14:30 reading a 1h@14:00 close (which
    materializes at 15:00), we shift the source dataframe's INDEX
    forward by exactly one source-TF bar before reindex. After the
    shift, index[i] is the bar's close-time, so ffill returns the most
    recently CLOSED bar at-or-before each target timestamp.

    bar_offset must match the source df's TF (default 1h, since
    load_cross_asset_warehouse loads 1h cross-asset by default).
    """
    if col not in other_df.columns:
        return pd.Series(np.nan, index=target_index)
    if "datetime" in other_df.columns:
        s = other_df.set_index("datetime")[col].sort_index()
    else:
        s = other_df[col].sort_index()
    if s.index.tz is not None and target_index.tz is None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    elif s.index.tz is None and target_index.tz is not None:
        s.index = s.index.tz_localize("UTC")

    # ── LEAK FIX: shift index forward by ONE source bar ──
    s = s.copy()
    s.index = s.index + bar_offset

    return s.reindex(target_index, method="ffill")
```

Caller change required: `add_cross_asset_features` should pass
`bar_offset=pd.Timedelta(hours=1)` (the cross-asset warehouse load
hard-codes `interval='1h'`). Or, better, plumb the cross-asset TF
through from `load_cross_asset_warehouse` so the offset always matches
whatever was loaded.

### Companion fix — leak #3 (`compute.py:873`)

```python
if usdjpy_df is not None and len(usdjpy_df) >= 20 and 'close' in usdjpy_df.columns:
    try:
        # LEAK FIX (2026-04-29): shift USDJPY index forward by one bar
        # before reindex, so a 5m XAU bar at 14:30 reads the USDJPY bar
        # CLOSED at 14:00 (not the bar that opens at 14:00 and closes at
        # 15:00). Inference always fetches USDJPY at 1h
        # (ensemble_models._fetch_live_usdjpy → '1h'); training does too
        # (train_all.py JPY=X interval='1h'). So 1h offset is correct.
        uj_series = usdjpy_df['close'].copy()
        if not isinstance(uj_series.index, pd.DatetimeIndex):
            uj_series.index = pd.to_datetime(usdjpy_df['datetime']
                                             if 'datetime' in usdjpy_df.columns
                                             else usdjpy_df.index)
        uj_series.index = uj_series.index + pd.Timedelta(hours=1)
        uj = uj_series.reindex(df.index, method='ffill')

        uj_mean = uj.rolling(20).mean()
        uj_std = uj.rolling(20).std()
        df['usdjpy_zscore_20'] = ((uj - uj_mean) / (uj_std + 1e-10)).fillna(0).clip(-5, 5)
        df['usdjpy_ret_5']     = uj.pct_change(5).fillna(0).clip(-0.1, 0.1)
        df['xau_usdjpy_corr_20'] = df['close'].rolling(20).corr(uj).fillna(0)
```

---

## Test that would catch each leak

A single unit test pattern catches all three. Drop into
`tests/test_features_v2_no_leak.py`:

```python
import numpy as np
import pandas as pd
import pytest

def _make_5m_df(n=200):
    idx = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    close = np.linspace(100, 200, n)  # strictly monotonic — easy to detect
    return pd.DataFrame({
        "datetime": idx, "open": close, "high": close, "low": close,
        "close": close, "volume": np.ones(n) * 1000,
    })

def _make_1h_df(n=20):
    idx = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    # close encodes the bar's 1-based ordinal so we can assert which
    # bar's close was used.
    close = np.arange(1, n + 1, dtype=float) * 1000
    df = pd.DataFrame({
        "datetime": idx, "open": close, "high": close, "low": close,
        "close": close, "volume": np.ones(n) * 1000,
    })
    return df

def test_multi_tf_no_future_leak():
    """The 5m bar at 14:30 must see the 1h bar that CLOSED at 14:00,
    NOT the 1h bar opening at 14:00 (which closes at 15:00)."""
    from src.analysis.features_v2 import add_multi_tf_features
    from src.analysis.compute import compute_features

    df_5m = _make_5m_df(n=20*12)  # 20 hours of 5m bars
    df_5m = df_5m.set_index("datetime")
    df_1h = _make_1h_df(n=20)
    df_1h_feat = compute_features(df_1h.copy())  # adds rsi/atr/...

    out = add_multi_tf_features(
        df_5m.copy(), {"1h": df_1h_feat},
    )
    # Bar at 14:30 (15th 5m bar of hour 14) — the 14:00 1h bar OPENS at
    # 14:00 and CLOSES at 15:00. After fix, our 14:30 bar must NOT carry
    # data from the 14:00→15:00 1h bar. It must carry data from the
    # 13:00→14:00 bar (the one that just closed at 14:00).
    ts = pd.Timestamp("2026-01-01 14:30:00", tz="UTC")
    assert ts in out.index, "14:30 must be present"
    # The h1_rsi at 14:30 must equal the rsi computed using bars
    # through 14:00 (i.e., the row whose ORIGINAL index was 13:00 in the
    # 1h df). After the +1h shift fix, that's the 13:00 row.
    expected_rsi = df_1h_feat.set_index("datetime")["rsi"].iloc[13]  # 13:00 bar
    assert out.loc[ts, "h1_rsi"] == pytest.approx(expected_rsi, abs=1e-9), (
        f"LEAK: h1_rsi@14:30 = {out.loc[ts, 'h1_rsi']:.4f}, "
        f"expected {expected_rsi:.4f} (close-of-13:00 bar)"
    )

def test_features_v2_immune_to_future_mutation():
    """Mutating close[t+1..t+N] must not change features at t."""
    from src.analysis.features_v2 import compute_features_v2

    df = _make_5m_df(n=400).set_index("datetime")
    feats_a = compute_features_v2(df.copy(), higher_tf_dfs={}, cross_asset_dfs={})

    # Mutate the last 100 bars wildly
    df_mut = df.copy()
    df_mut.iloc[-100:, df_mut.columns.get_loc("close")] = 999_999.0
    df_mut.iloc[-100:, df_mut.columns.get_loc("high")]  = 999_999.0
    df_mut.iloc[-100:, df_mut.columns.get_loc("low")]   = 999_999.0
    feats_b = compute_features_v2(df_mut, higher_tf_dfs={}, cross_asset_dfs={})

    # Pick a row 200 bars before end — strictly in the past relative to
    # the mutation. Every feature must be identical.
    common = feats_a.index.intersection(feats_b.index)
    test_ix = common[-150]  # 150 bars before end, mutation is in last 100
    a = feats_a.loc[test_ix].drop(["open", "high", "low", "close", "volume"], errors="ignore")
    b = feats_b.loc[test_ix].drop(["open", "high", "low", "close", "volume"], errors="ignore")
    pd.testing.assert_series_equal(a, b, check_exact=False, atol=1e-9)
```

(Don't run — assertions documented as the contract that the fix must
make true.)

---

## What does v2_xgb actually see at training vs inference?

**Training (`scripts/train_v2.py`):** 5m XAU is loaded from
`data/historical/XAU_USD/5min.parquet`, indexed by start-of-bar
timestamp. `compute_features_v2(df)` is called with default kwargs, so
`higher_tf_dfs = load_higher_tf_warehouse('XAU/USD')` (1h, 4h, 1day
parquets) and `cross_asset_dfs = load_cross_asset_warehouse('1h')`
(XAG, EUR, TLT, SPY, BTC, VIX/VIXY at 1h). USDJPY is **not** passed
during training (`compute_features_v2` doesn't fetch it; it's only
fetched if the caller passes `usdjpy_df=...`, which `train_v2.py:75`
does not). So training v2_xgb has zero USDJPY signal — the
`usdjpy_*` columns are all zeros at training time. The 13 cross-asset
features and 13 multi-TF features ARE populated, but every one of them
is contaminated by leaks #1 and #2 — each carries +30 min of future
information on average for a 5m bar (more for 4h/1d projections).

**Inference (`predict_v2_xgb_direction` →
`compute_features_v2(df.copy())`):** the 5m XAU window comes from the
live data provider (TwelveData). `compute_features_v2` re-runs the
same warehouse load: `higher_tf_dfs = load_higher_tf_warehouse(...)`
and `cross_asset_dfs = load_cross_asset_warehouse('1h')`. So in
inference, multi-TF and cross-asset features come from the **same
warehouse parquets that were used at training** — meaning the same
+30 min look-ahead is present in inference too. **The leak does not
cause a train/infer distribution shift; it causes both sides to be
contaminated identically.** That's why the model "looks great" in
walk-forward and probably continues to look better than reality in
shadow logs: it never sees a clean dataset to be honest with.

**Where train ≠ infer:** USDJPY is the only mismatch. Training v2_xgb
(via `train_v2.py`) has `usdjpy_zscore_20 = usdjpy_ret_5 =
xau_usdjpy_corr_20 = 0` for every row because `usdjpy_df` is never
threaded in. Inference (via `predict_v2_xgb_direction` →
`compute_features_v2(df.copy())` → `compute_features(df,
usdjpy_df=None)`) ALSO has them zeroed because `compute_features_v2`
doesn't forward `_fetch_live_usdjpy()` either — the call at
`features_v2.py:323` is `compute_features(df, usdjpy_df=usdjpy_df)`
where `usdjpy_df` is the kwarg passed to `compute_features_v2`, which
defaults to `None`. So USDJPY features are zero in both train and
infer for v2_xgb. **No leak from #3/#4 actually flows into v2_xgb
today** — those leaks affect v1 voters (lstm/attention/xgb/dqn
through `_compute_ensemble_features`) but not v2_xgb because the v2
path simply ignores USDJPY end-to-end. **The "PF 2.24 OOS" finding is
contaminated by leaks #1 and #2 only.** Fixing #3/#4 is still
required for the v1 voters but won't move v2_xgb numbers.

**Net implication:** re-running per-direction walk-forward on shifted
features (leaks #1, #2 fixed) is the only way to know whether v2_xgb
has any real edge. Expected drop: 3–8 pp WR per the audit-1 doc; my
read is the high end is more likely because both higher-TF and
cross-asset paths are leaked simultaneously. Until then, set
`v2_xgb` weight to 0.0.

---

## Action checklist (recap)

- [ ] Apply patch #1 (`add_multi_tf_features` HTF index shift).
- [ ] Apply patch #2 (`_align_to_index` cross-asset index shift +
      thread `bar_offset` from caller).
- [ ] Apply patch #3 (`compute.py` USDJPY index shift) — fixes v1 LSTM/
      Attention/XGB/DQN; v2_xgb unaffected because it doesn't use USDJPY.
- [ ] Patch #4: pass scanner TF into `_fetch_live_usdjpy(tf)`;
      standardize on TwelveData for training USDJPY too.
- [ ] Mute `v2_xgb` weight to 0.0 in `_get_voter_weights()` until
      walk-forward re-runs cleanly on shifted features.
- [ ] Add `tests/test_features_v2_no_leak.py` (template above).
- [ ] Re-run `scripts/walk_forward_v2.py --warehouse` after patches;
      record new PF/WR per direction. If edge survives, restore
      v2_xgb weight to 0.10.
- [ ] (Optional, NICE) Drop or rename `chikou_span` in
      `indicators.py:16` so future devs can't accidentally feed it.
