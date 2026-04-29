# Data-Leak Audit — 2026-04-29

Auditor: Claude (read-only research pass).
Scope: every feature pipeline, scaler, train/val split, and inference path
that feeds the 7-voter ensemble. Triple-barrier label kernel verified.
No code modified.

## Summary

- **6 CRITICAL findings** — must fix before retraining anything.
- **4 IMPORTANT findings** — fix before relying on inference output.
- **3 NICE-TO-FIX** — defensive cleanups; not strictly leaks today but
  primed to become one.

The single most important call: **don't retrain yet**. Three of the six
voters (LSTM, Attention, DPformer/Decompose) currently fit their
`MinMaxScaler` on the entire training dataset before the walk-forward
folds run — every reported walk-forward accuracy on those voters is
inflated by an unknown amount. One voter (DPformer/Decompose) further
uses a centered moving-average that explicitly mixes future bars into the
trend component. And the `features_v2` cross-asset / multi-TF projection
ffills bars that are time-stamped at their START, which means a 5m bar at
14:30 receives 1h-bar data labeled `14:00` whose `close` is the price at
15:00 — a textbook +30 min look-ahead.

## Findings (sorted by severity)

### [CRITICAL] DPformer/Decompose trend uses centered convolution (future leak)

**Location:** `src/ml/decompose_model.py:48`
**Mechanism:** `np.convolve(series, kernel, mode='same')` is symmetric:
the trend value at index `t` is the average of `series[t - period/2 : t + period/2]`.
With `period=20`, the trend at bar `t` literally averages 10 bars from the
future. `seasonal = series - trend` then propagates that future signal
into every downstream feature, residual = `np.diff(seasonal)` propagates it
again, and all three branches of the model (LSTM-trend / Attention-seasonal
/ Dense-residual) train on it. This is consistent with the empirical
val_acc of 78–80% flagged in `train_all.py` line 627 as "suspected data
leak — disabled".
**Evidence:**
```python
# decompose_model.py:46–56
kernel = np.ones(period) / period
if len(series) >= period:
    t = np.convolve(series, kernel, mode='same')   # <-- centered
    t[:period // 2] = t[period // 2]
    t[-(period // 2):] = t[-(period // 2) - 1]
trend[:, col] = t
seasonal[:, col] = series - t
```
**Fix:** swap to a backward-only window: `pd.Series(series).rolling(period).mean().to_numpy()`,
or `np.convolve(series, kernel, mode='full')[: len(series)]` and then
shift / truncate so trend at `t` only sees indices `≤ t`. After the fix,
re-enable training (the disable note in `train_all.py:626-632` becomes
moot).
**Verification:** add a unit test that asserts
`trend[t]` depends only on `series[:t+1]` by perturbing `series[t+1]` and
confirming `trend[t]` is unchanged. Then re-train; honest val_acc will
likely drop to ~55–62% (the LSTM/XGB band).

---

### [CRITICAL] LSTM scaler fitted on full training set before walk-forward folds

**Location:** `src/ml/ml_models.py:172`
**Mechanism:** `scaled = self.scaler.fit_transform(data)` runs before the
`for fold in range(5)` loop. Each fold then slices an already-scaled
`X[:train_end]` / `X[train_end:test_end]`. The scaler's per-feature min/max
were learned from the full training set — i.e., the future. Fold 1 trains
on data that has been normalized using statistics from fold 5. Identical
pattern in the FINAL model fit at line 228 (split is on already-scaled
data). The reported walk-forward accuracy is therefore optimistic.
**Evidence:**
```python
# ml_models.py:171–186
data = features[FEATURE_COLS].values
scaled = self.scaler.fit_transform(data)    # <-- leaks val into train scaling
...
for fold in range(5):
    X_tr, X_te = X[:train_end], X[train_end:test_end]
    ...
```
**Fix:** in each fold (and for the final model), call `MinMaxScaler().fit(X_tr)`
on the train slice only, then `transform(X_te)`. Persist the scaler that
was fit on the FULL train_df at the very end so inference loads
consistent statistics — that's the production scaler. Do NOT use the
"leaked" scaler to compute walk-forward accuracy.
**Verification:** report walk-forward acc with both old and new scaler
flow. Expect a real drop of 2–5 pp on LSTM. Add a test that asserts
`MinMaxScaler.data_max_` after fitting on `X_tr` differs from
`MinMaxScaler.data_max_` after fitting on `X` whenever val data contains
out-of-sample maxima.

---

### [CRITICAL] Attention model — same scaler-on-full-data leak

**Location:** `src/ml/attention_model.py:93`
**Mechanism:** Identical pattern to LSTM: `scaler.fit_transform(data)`
over the full training array, then walk-forward folds use the leaky scaling.
The persisted `attention_scaler.pkl` is also the leaky one.
**Evidence:**
```python
# attention_model.py:92–106
scaler = MinMaxScaler()
scaled = scaler.fit_transform(data)      # <-- leaks
...
for fold in range(3):
    X_tr, X_te = X[:train_end], X[train_end:test_end]
```
**Fix:** mirror the LSTM fix. Per-fold scaler fit on `X_tr` only.
**Verification:** same as LSTM.

---

### [CRITICAL] DeepTrans transformer — same scaler-on-full-data leak

**Location:** `src/ml/transformer_model.py:212`
**Mechanism:** `scaler.fit_transform(data)` runs before the 80/20 train/val
split at line 234. Val accuracy reported by `model.fit(...,
validation_data=(X_val, y_val))` was computed against val data scaled
with statistics that include the val set itself.
**Evidence:**
```python
# transformer_model.py:211–235
scaler = MinMaxScaler()
scaled = scaler.fit_transform(data)            # <-- full data
...
split = int(0.8 * len(X))
X_tr, X_val = X[:split], X[split:]
```
**Fix:** scale after the split: `scaler.fit(X_tr); X_tr = scaler.transform(X_tr); X_val = scaler.transform(X_val)`.
Persist this scaler.
**Verification:** report old vs new val_accuracy on the same dataset.
DeepTrans is currently flag-gated (`QUANT_ENABLE_TRANSFORMER`) so impact
is limited to evaluating whether to enable it.

---

### [CRITICAL] features_v2 multi-TF / cross-asset ffill projects future-tagged bars onto current bar

**Location:** `src/analysis/features_v2.py:117` (`_align_to_index`) and
`src/analysis/features_v2.py:235` (`add_multi_tf_features`).
**Mechanism:** Warehouse parquets and TwelveData responses tag each bar
by its **start** timestamp (verified via `data_sources.py:194` — the
"datetime" field of TwelveData is the bar's open time). When we ffill a
1h dataframe onto a 5m index, the 5m bar at `14:30` looks up the most
recent 1h bar `≤ 14:30`, which is `14:00`. The 1h `14:00` bar's
`close` / `rsi` / `atr` columns are the values at the bar's **end** —
i.e., 15:00 — which is +30 minutes IN THE FUTURE relative to the 5m bar.
Same problem applies to every cross-asset (XAG, EURUSD, TLT, SPY,
BTC, VIX) and every projected higher-TF feature (`h1_rsi`, `h1_atr`,
`h4_*`, `d1_*`). The leak compounds because v2_xgb is the only voter
trained on these features and it's already running live in the ensemble
at weight 0.10. Per-direction walk-forward edge ("PF 2.24 / WR 53.6%")
recorded in `memory/...` is therefore suspect.
**Evidence:**
```python
# features_v2.py:235
projected = tf_indexed[feat].reindex(df.index, method="ffill")
df[col_name] = projected.fillna(0)
```
And from data_sources.py:194 confirming start-time labeling:
```python
df['timestamp'] = pd.to_datetime(df['datetime'], utc=True)
```
**Fix:** before reindexing, **shift the higher-TF dataframe by one bar
forward** so each row carries the data that was actually closed at that
timestamp. Or equivalently, reindex with `method="ffill"` AFTER calling
`tf_indexed.shift(1)`. For cross-asset, do the same — shift forward by
1 bar of the cross-asset's TF before reindexing. Add a comment with
this exact reasoning at the call site.
**Verification:** unit test: build a 1h dataframe where `close = bar_index`,
project onto a 5m index, and assert that the 5m bar at `14:30` sees
`close = 13` (the bar that closed at 14:00) not `close = 14` (the bar
that closes at 15:00). Then re-run the v2_xgb walk-forward; expect WR
to drop by 3–8 pp, possibly below the 50% threshold needed to keep the
voter live.

---

### [CRITICAL] Inference / training distribution mismatch on USDJPY macro features

**Location:** `train_all.py:177–204` (training fetch via `yfinance JPY=X`,
1h only) vs `src/ml/ensemble_models.py:303–319` (inference fetch via
TwelveData `USD/JPY`, 1h fixed regardless of XAU TF).
**Mechanism:** Two independent leaks ride together:
1. **Source mismatch:** training uses yfinance which serves bar boundaries
   on yfinance's clock; inference uses TwelveData with `timezone=UTC`.
   Bar timestamps differ by tens of minutes in some sessions, and
   `close` is computed on different ticker feeds. The model learned
   `usdjpy_zscore_20` distribution from yfinance bars and is fed
   TwelveData bars in production.
2. **TF mismatch & look-ahead:** scanner runs on 5m/15m/30m/1h/4h. For
   anything other than 1h, the inference path fetches USDJPY at 1h
   regardless and ffills onto the XAU index inside `compute_features`
   (`src/analysis/compute.py:873`). The same start-timestamped-bar issue
   from finding #5 applies — a 5m XAU bar at 14:30 receives USDJPY data
   from a 1h bar that closes at 15:00. Training was done at 1h XAU vs
   1h USDJPY where the reindex is the identity, so the model never saw
   this leak in training but does at inference. Direction unclear:
   leaked features at inference might happen to point the right way or
   wrong way; either is a wrong distribution shift.
**Evidence:**
```python
# train_all.py:194–195
uj = yf.Ticker("JPY=X").history(period=period, interval=interval)
```
```python
# ensemble_models.py:314
uj_df = provider.get_candles('USD/JPY', '1h', limit)  # always 1h
```
```python
# compute.py:873
uj = usdjpy_df['close'].reindex(df.index, method='ffill')
```
**Fix:** (a) fetch USDJPY at the *same* TF as XAU during inference (the
provider already supports 5min/15min/30min/4h); (b) shift the USDJPY
series forward by 1 bar before reindexing, identical to the features_v2
fix; (c) standardize on TwelveData for both training and inference —
re-fetch the training USDJPY history from TwelveData warehouse parquet
when the new triple-barrier dataset is built.
**Verification:** parity test that loads a sample 5m XAU window in both
training and inference paths and asserts `usdjpy_zscore_20[t]` matches
within 1e-6. Today's inference `usdjpy_zscore_20` will diverge by a
visible amount from the training one for the same physical timestamp.

---

### [IMPORTANT] LSTM inference path will silently re-fit scaler if `lstm_scaler.pkl` is missing

**Location:** `src/ml/ensemble_models.py:373–375`
**Mechanism:** `_get_scaler()` returns `(scaler, False)` (a fresh
unfitted scaler) when the pickle is missing. The caller then runs
`scaler.fit_transform(data)` on a single 60-bar window from the live
data. Each scan produces wildly different scaling and the model sees
inputs in a different distribution from training. Logged as `debug` so
it slips by silently in production logs.
**Evidence:**
```python
# ensemble_models.py:371–375
if is_fitted:
    data = scaler.transform(data)
else:
    logger.debug("LSTM scaler nie z treningu — fit_transform (mniej stabilne)")
    data = scaler.fit_transform(data)
```
**Fix:** when the persisted scaler is missing, log a `warning` and
return `None` from `predict_lstm_direction` (mark voter unavailable)
rather than fitting a one-window scaler. Apply the same to attention
and decompose voters; transformer already returns None on load failure.
**Verification:** rename `models/lstm_scaler.pkl` and confirm the LSTM
voter shows `status: unavailable` in `/api/models/predictions` instead
of returning a number.

---

### [IMPORTANT] FEATURE_COLS list is not pinned per saved model

**Location:** `src/ml/ml_models.py:171, 303` (LSTM) and inference at
`ensemble_models.py:366, 522` use the live `FEATURE_COLS` constant from
`compute.py`.
**Mechanism:** if `FEATURE_COLS` ever changes (added a feature, reordered
one) between training and inference — even via a hot-reload during
auto-retrain — the saved scaler and `.keras` model expect a column order
that no longer matches what `compute_features(df)[FEATURE_COLS]`
returns. `transformer_model.py` already pins `feature_cols` inside the
scaler pickle (`scaler.pkl` blob at line 263); other voters do not.
This is how the 31→34 feature extension on 2026-04-24 silently risked
breaking persisted models.
**Evidence:**
```python
# ml_models.py:171
data = features[FEATURE_COLS].values
```
no `FEATURE_COLS` is persisted alongside `lstm_scaler.pkl`.
**Fix:** when persisting any scaler, save a dict
`{"scaler": scaler, "feature_cols": list(FEATURE_COLS)}` (mirror
transformer_model.py's pattern). At inference, load both and use the
saved column list — assert it's a subset of current `FEATURE_COLS`.
**Verification:** intentionally remove a feature from `FEATURE_COLS`,
restart the API, and confirm voters refuse to predict instead of
silently shifting columns.

---

### [IMPORTANT] Walk-forward fold size is too small to be honest

**Location:** `src/ml/ml_models.py:75–85` (`fold_size = n // 6` then 5 folds)
**Mechanism:** with 5 folds advancing one fold at a time inside the same
contiguous training set, fold 5 trains on the first ~83% of the data
and tests on the last ~17%. Folds 1–4 test on data immediately adjacent
in time to the train tail, with no embargo — adjacent 5m / 15m bars are
strongly autocorrelated, so the test slice is "soft" overlapping with
the train slice's information content (label leak via temporal
proximity). The final model also uses `validation_data=(X_test, y_test)`
where `X_test = X[split:]` — that's an ~80/20 INTRA-train split, not the
held-out `val_df`. The reported "validation accuracy" is on data
adjacent to the model's last training bar.
**Evidence:**
```python
# ml_models.py:75
fold_size = n // 6
```
**Fix:** insert a `purge_bars` and an `embargo_bars` between train and
test in each fold (López de Prado's purged k-fold). Conservative default:
`purge = max_holding_bars` (60 bars on 5m), `embargo = 5 * purge`.
Switch the FINAL accuracy report to use `val_df` from `train_all.py`
instead of the intra-train 80/20 split.
**Verification:** add a tiny test that asserts no test bar is within
`purge + embargo` of any train bar in the same fold.

---

### [IMPORTANT] dropna inside compute_features removes warmup rows on the joined dataframe

**Location:** `src/analysis/compute.py:893`
**Mechanism:** `df.dropna(inplace=True)` runs after USDJPY reindex/ffill.
USDJPY rolling stats (z-score 20, return 5, corr 20) need >=20 USDJPY bars
of history *aligned to the XAU index*. If the USDJPY series starts later
than XAU (common when warehouse coverage differs by symbol), the leading
~20 XAU bars get dropped silently. Same when training on 60-day 15m XAU
but USDJPY only has 60-day 1h coverage — the alignment may produce NaNs
the model and its scaler must skip. Not a leak per se, but it tanks
sample size invisibly. Worse: in the ENSEMBLE inference path, dropna
followed by `tail(seq_len)` could end up drawing on bars that aren't
consecutive in time, breaking the LSTM's implicit assumption of contiguous
intervals.
**Fix:** after dropna, assert the index is monotonic and contiguous on
the expected TF cadence. If gaps > 1 bar exist near the inference window,
return `None` from the voter rather than silently producing a prediction
on a non-contiguous sequence.
**Verification:** unit test that injects a 6-bar gap into the 5m XAU
data 30 bars before the inference point and confirms the LSTM voter
returns None, not a number.

---

### [NICE-TO-FIX] `chikou_span` definition leaks future, but is unused

**Location:** `src/analysis/indicators.py:16`
**Mechanism:** `chikou_span = df['close'].shift(-kijun)`. Negative shift =
future close pulled into current row. The function returns it as a column
of the result. Nothing in the trading code currently consumes this column
(only `senkou_span_a/b` are referenced by `smc_engine.py:1047`), but
anyone who casually adds `chikou_span` to a feature list would
introduce a CRITICAL leak in one line.
**Fix:** drop the `chikou_span` column from the return dict, or rename
it to `chikou_span_future_LEAK` so the next person notices.
**Verification:** grep for `chikou` post-rename — should still be zero
matches in `src/`.

---

### [NICE-TO-FIX] Triple-barrier label kernel is correct, but ATR is computed without warmup gate

**Location:** `tools/build_triple_barrier_labels.py:59` (`_wilder_atr`)
and `_walk_forward_kernel` line 115.
**Mechanism:** the walk-forward kernel itself looks only at indices
`t+1 .. t+max_holding`, so labeling is leak-free. But Wilder ATR (line 75)
seeds with `tr[:period].mean()` at index `period-1`, and earlier indices
are zero. The kernel guards against zero/non-finite ATR (`if not
np.isfinite(a) or a <= 0: continue`), so labels for the first `period-1`
bars get sentinel `-1`. That's fine — except the resulting parquet still
emits those rows, so a downstream training script that doesn't filter on
`long_label != -1` would feed degenerate samples to the model. Not a
leak but a foot-gun.
**Fix:** add a `valid_mask` column (or filter rows with `long_label == -1`
out of the saved parquet) so downstream training can't accidentally
include warmup rows.
**Verification:** train_v2.py / future trainers should add an explicit
filter `features = features[features['long_label'] != -1]`.

---

### [NICE-TO-FIX] DPformer prediction path does not pass `usdjpy_df`

**Location:** `src/ml/decompose_model.py:276` (`compute_features(df)`
without macro), `src/ml/transformer_model.py:341` (same).
**Mechanism:** training for DPformer in train_all.py passes `usdjpy_df`
when the parent calls it; inference at line 276 calls
`compute_features(df)` without macro. So the macro features are zeros at
inference time even when training included them. This is a TRAIN/INFER
distribution mismatch, not a leak — the model behaves like the macro
features are missing; predictions are still valid but degraded.
DPformer is currently disabled at weight 0.0 so impact is moot, but the
same bug applies to the deeptrans path (`transformer_model.py:341`)
which IS the path that runs when `QUANT_ENABLE_TRANSFORMER=1`.
**Fix:** thread `usdjpy_df` through to inference, mirroring the LSTM /
attention call sites in `ensemble_models.py:920`.
**Verification:** print `usdjpy_zscore_20` at inference time for
deeptrans on a window where it should be non-zero, confirm it's >0.

---

## Pre-training go/no-go

Before kicking off any retrain on the new triple-barrier dataset, all
6 CRITICAL items below must be resolved. The IMPORTANT items can land in
the same PR but aren't strict blockers if scope grows.

### Critical (BLOCK retrain until done)
- [ ] **C1** `src/ml/decompose_model.py:48` — replace `np.convolve(...,
  mode='same')` with a backward-only rolling mean. Re-enable DPformer
  training only after a parity unit test confirms `trend[t]` does not
  depend on `series[t+1]`.
- [ ] **C2** `src/ml/ml_models.py:172` — move `scaler.fit_transform`
  inside each walk-forward fold; persist the final-model scaler trained
  on the full train_df (the production scaler).
- [ ] **C3** `src/ml/attention_model.py:93` — same fix as C2.
- [ ] **C4** `src/ml/transformer_model.py:212` — fit scaler after the
  80/20 split, not before.
- [ ] **C5** `src/analysis/features_v2.py:117, 235` — shift higher-TF
  and cross-asset dataframes by 1 bar of their TF before `reindex(...,
  method='ffill')`. Add unit test that bar `t` only sees data closed at
  or before `t`. Re-run v2_xgb walk-forward on shifted features; if
  edge collapses, mute the v2_xgb voter (set weight 0.0) until it can
  be re-tuned.
- [ ] **C6** `src/analysis/compute.py:873` — same shift fix for USDJPY.
  Additionally: standardize training USDJPY source on TwelveData
  warehouse (matches inference) instead of yfinance JPY=X.

### Important (SHOULD ship before relying on numbers)
- [ ] **I1** `src/ml/ensemble_models.py:373–375` — fail closed when
  scaler is missing, do not fit-on-window.
- [ ] **I2** Persist `feature_cols` alongside every scaler pickle
  (mirror transformer_model.py's blob shape).
- [ ] **I3** Walk-forward folds: add purge + embargo per López de
  Prado, switch the final reported accuracy from 80/20 intra-train to
  the held-out `val_df`.
- [ ] **I4** `src/analysis/compute.py:893` — assert post-dropna index is
  contiguous; voters return None on gap.

### Nice-to-fix (defensive)
- [ ] **N1** Drop `chikou_span` (or rename it to make leak obvious).
- [ ] **N2** Triple-barrier parquet: filter or mark the warmup rows
  with `long_label == -1`.
- [ ] **N3** Pass `usdjpy_df` to DPformer / DeepTrans inference paths.

---

## Notes on what was NOT a leak

To save the next auditor time, these patterns were inspected and look clean:

- `compute_target` at `src/analysis/compute.py:907` is the **target**
  itself, not a feature. The future_max/future_min usage is correct;
  `dropna` after target computation removes the trailing NaN target rows.
- `compute_features` indicators (RSI, MACD, ATR, EMA, Williams %R, CCI,
  Ichimoku, candlestick patterns, ADX, VWAP, volatility_percentile,
  trend_strength) all use **backward** rolling windows. No `center=True`
  found in the live feature path.
- `r_multiple_labels` (`src/learning/labels/r_multiple.py:84`) only
  reads `j in range(i+1, horizon_end)` — strictly forward. OK.
- Triple-barrier kernel (`tools/build_triple_barrier_labels.py:115`)
  same: `for k in range(1, max_holding+1)`, `ti = t + k`. OK.
- DQN state vector (`src/ml/rl_agent.py:692, 259`) uses only
  `close_prices[-20:]` and current balance/position — no feature leak.
- `train_v2.py` LSTM scaler (line 245) is correctly fit on `X_tr` only.
  Other parts of v2 inherit C5/C6 because of the upstream features_v2 leak.
- `compute_features` USDJPY join (compute.py:873) — the leak is the
  *bar-edge* timing per finding #6, not the math itself. Fix the shift,
  not the formula.
- Train/val/holdout split in `train_all.py:218–235` is properly
  chronological (no shuffle, no random_state on the time axis). Good.
