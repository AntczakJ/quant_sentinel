# Reproducibility & Deployment Audit — 2026-04-29

## TL;DR
**Three blocker-class bugs in the upcoming retrain.** (1) `train_all.py` trains on yfinance `GC=F` (Gold Futures) but live inference reads TwelveData `XAU/USD` (Spot Gold) — CLAUDE.md notes a $65–75 price gap, meaning every model would be inferring on out-of-distribution data the moment retraining lands. (2) `train_all.py` sets **zero** RNG seeds and **zero** TF-determinism env flags — same script + same data ≠ same model, so two reruns of the new triple-barrier pipeline will diverge unpredictably. (3) Treelite recompile is **not enforced** anywhere — retrain XGB and forget `tools/compile_xgb_treelite.py` and live scanner keeps serving stale predictions for hours/days because `_load_xgb()` silently picks the (now-stale) `.dll` via the Treelite path before falling through. **Fix #1 + #2 + #3 before retraining**, or accept that the new triple-barrier voters are launching on top of a structurally OOD inference path.

---

## Findings by category

### Reproducibility

- **[CRITICAL] No determinism configuration in `train_all.py`**
  **Location:** `train_all.py:1–724` (entire file)
  **Issue:** Grep `tf.random.set_seed|np.random.seed|random.seed|TF_DETERMINISTIC|enable_op_determinism` in `train_all.py` returns **zero matches**. Same for `train_rl.py`, `src/ml/ml_models.py`, `src/ml/attention_model.py`, `src/ml/decompose_model.py`. Only the (auxiliary) `retrain_*_loop.py` scripts and `scripts/train_v2.py` set seeds. The XGB call inside `ml_models.py:93,106` does pass `random_state=42`, but that's the only seed set anywhere in the master pipeline.
  Combined with `class_weight={...}` reductions, mixed-precision float16 (`compute.py:51` enables `mixed_float16` whenever a TF GPU is detected — non-deterministic by default) and CuDNN heuristics, **two consecutive runs of `python train_all.py` will produce different `lstm.keras`, different `attention.keras`, different `rl_agent.keras` weights — and therefore different predictions.**
  **Fix:** Add at the very top of `train_all.py` (BEFORE any `import tensorflow`):
  ```python
  import os
  os.environ["PYTHONHASHSEED"] = "42"
  os.environ["TF_DETERMINISTIC_OPS"] = "1"
  os.environ["TF_CUDNN_DETERMINISTIC"] = "1"
  import random; random.seed(42)
  import numpy as np; np.random.seed(42)
  # then later, after `import tensorflow as tf`:
  tf.keras.utils.set_random_seed(42)
  tf.config.experimental.enable_op_determinism()
  ```
  Same change in `train_rl.py`. `scripts/train_v2.py:44–48` already does this — copy that block.

- **[IMPORTANT] Mixed-precision float16 is enabled unconditionally on TF GPU**
  **Location:** `src/analysis/compute.py:51` (`tf.keras.mixed_precision.set_global_policy('mixed_float16')`)
  **Issue:** Mixed-precision uses non-deterministic reductions on most CuDNN ops. Even with `enable_op_determinism()`, several `mixed_float16` paths fall back to non-deterministic kernels with a soft warning. On Modal T4 (where TF GPU is operational per `modal_tf_gpu_fix_2026-04-27.md`) this matters; on local Windows where TF falls back to CPU it's moot — but Janek runs both.
  **Fix:** Gate `mixed_float16` behind `os.environ.get("QUANT_DETERMINISTIC") != "1"`. Or accept the small training-speed loss in exchange for byte-identical retrains.

- **[IMPORTANT] Modal training and local training will produce different weights**
  **Location:** `tools/modal_train.py:118–180` (debian_slim + TF 2.21.0 + CUDA via `[and-cuda]`); local box is Windows + TF CPU + ONNX-DirectML for inference
  **Issue:** Even with seeds, CUDA kernels on T4 produce different floats than AVX2 CPU kernels on the local 1070-less Windows env. With `mixed_float16` on Modal and `float32` on Windows, divergence is multiplicative. There is no parity test asserting "Modal-trained `lstm.keras` predicts within ε of locally-trained `lstm.keras` on a holdout batch."
  **Fix:** Pick one as canonical (Modal, given GPU availability) and document. Add a minimal CI step: `pytest tests/test_modal_local_parity.py` that loads both `lstm.keras` artefacts and asserts max-abs-diff < 0.02 on a 100-row holdout.

- **[NICE] No persistence of train/val/holdout split RNG**
  **Location:** `train_all.py:218–235` (`split_data` is a deterministic chronological cut; OK), but XGB `subsample=0.8, colsample_bytree=0.7` (`ml_models.py:91`) draws via the booster's internal RNG — `random_state=42` covers it, but only for sklearn-XGB. The DQN replay buffer (`rl_agent.py:84+`) uses `np.random.uniform` which is **not seeded** anywhere if you call `train_dqn` without going through `scripts/train_v2.py`.
  **Fix:** Per-session `np.random.seed` set at the top of `train_all.py` (covered by the [CRITICAL] fix above) is sufficient for XGB; for DQN, also pass a `seed=42` argument into `DQNAgent` and `TradingEnv`.

---

### Versioning

- **[CRITICAL] `train_all.py` does NOT log to the training registry**
  **Location:** `train_all.py:1–724`
  **Issue:** `src/ml/training_registry.py::log_training_run` exists, has nice schema (timestamp, hyperparams, data signature, metrics, git_commit, git_dirty, artifact size), and is API-exposed at `GET /api/training/history`. **It's only called by `retrain_*_loop.py`, `tune_*.py`, `train_rl.py`, `train_transformer.py` — never by `train_all.py`**, which is the master pipeline that produces `lstm.keras`, `attention.keras`, `decompose.keras`, `xgb.pkl`, `rl_agent.keras`. Result: the registry has 7 entries total, the last from 2026-04-18, even though all of those models were retrained 2026-04-24. **You cannot answer "which weights are live, which trained when, on what data, what git commit" from the registry today.**
  **Fix:** Add `log_training_run(model_type=..., ..., notes='train_all master')` calls after each successful sub-step in `train_all.py:600–656`. Five call-sites: XGB, LSTM, Attention, DPformer (currently skipped), DQN. `data_signature` should include the yfinance `period`/`interval` actually fetched and the data hash already computed at line 637.

- **[CRITICAL] No enforcement that Treelite `.dll` matches `xgb.pkl`**
  **Location:** `src/ml/ensemble_models.py:148–166` (Treelite load path), `tools/compile_xgb_treelite.py` (compile-time parity check)
  **Issue:** `_load_xgb()` checks `os.path.exists(treelite_path)` and uses it if present. There is **no check** that `xgb_treelite.dll`'s mtime ≥ `xgb.pkl`'s mtime, no version stamp, no parity assertion. CLAUDE.md says "mismatched .dll vs .pkl is a real bug surface so we never commit it" — and indeed it's `.gitignore`'d — but a freshly retrained `xgb.pkl` on disk + an ancient `xgb_treelite.dll` left over from previous compile = live scanner serves predictions from the OLD model with full Treelite speedup, no warning.
  Today's mtime check: `xgb.pkl` is 2026-04-24 21:09, `xgb_treelite.dll` is 2026-04-26 23:37 — coincidentally fresh. Tomorrow after retrain: `xgb.pkl` will be 2026-04-29 evening, `.dll` still 04-26 (until you remember to rerun). The cache-invalidation path in `ensemble_models.py:74` (`_invalidate_if_stale`) only checks `pkl_path` and `onnx_path`, **not the treelite path**. So even if you _do_ recompile, the in-process cached Treelite `Predictor` won't reload.
  **Fix:** (1) Add `treelite_path` to the `_invalidate_if_stale("xgb", ...)` arg list at line 143. (2) In `_load_xgb()`, before returning Treelite cache, assert `os.path.getmtime(treelite_path) >= os.path.getmtime(pkl_path) - 0.5` and fall through to ONNX/sklearn if not (with a `logger.warning` so it's visible in logs). (3) Make `train_all.py` step #7 (post-training ONNX export, line 657) also invoke the Treelite recompile script as a subprocess — fail loudly if compile fails.

- **[IMPORTANT] No symlink/manifest indicating which weights are "live"**
  **Location:** `models/` directory
  **Issue:** `lstm.keras` is the live model. `lstm_sweep_winner.keras`, `lstm_pre_v2_backup.keras`, `_archive/lstm.h5`, `_backup_20260413T013619/lstm.keras` are all _also_ on disk. Inference reads `lstm.keras` by hardcoded path (`ensemble_models.py:88`). To answer "what was lstm.keras trained from?" you'd need to: (a) check git log for any commit that mentions LSTM; (b) cross-reference with `training_registry.py` (which is empty for `train_all` runs — see above); (c) infer from `lstm_last_accuracy` in `dynamic_params`. None of those answer the question definitively.
  **Fix:** Have `train_all.py` write a sibling `models/MANIFEST.json` after each run with `{"lstm.keras": {"trained_at": ..., "git_commit": ..., "data_signature": ..., "registry_record_id": ...}}` for every artifact it touches. Fast, atomic, easy to grep.

- **[NICE] DQN model is 17 days older than other voters**
  **Location:** `models/rl_agent.keras` mtime 2026-04-12, `lstm.keras` mtime 2026-04-24
  **Issue:** Per `train_all.py:640`, `--skip-rl` defaults to False but the recent retrain on 04-24 was probably run with `--skip-rl` (RL takes ~30 min on CPU). The DQN agent in production hasn't been retrained alongside the 7-voter pipeline since 2026-04-12. Per CLAUDE.md DQN is at "0.25 weight, 66-80% live accuracy" so it's still working, but retraining cadence needs to be consistent.
  **Fix:** Document in CLAUDE.md the canonical retrain command (`python train_all.py` _without_ `--skip-rl`), or split the `rl_agent` retrain into a separate weekly cron and document that.

---

### Inference parity

- **[CRITICAL] Training data source ≠ inference data source — STRUCTURAL OOD**
  **Location:** `train_all.py:117–127` (yfinance `GC=F` 2y/1h), `src/data/data_sources.py:499–513` (TwelveData `XAU/USD` for live), CLAUDE.md memo `data_source_reality.md`
  **Issue:** Training pulls **Gold Futures (GC=F)** from yfinance with 2y of 1h bars. Live inference (`ensemble_models.py:879–887`) pulls **Spot Gold (XAU/USD)** from TwelveData. Per `memory/data_source_reality.md`: "$65-75 price gap." That's a ~1.5% systematic price offset — but more importantly, the contango/backwardation structure of GC=F means returns/volatility/range distributions also differ. The macro-feature side is consistent: `train_all.py:194` fetches `JPY=X` from yfinance, `_fetch_live_usdjpy` (`ensemble_models.py:303–319`) fetches `USD/JPY` from TwelveData — different sources but same instrument, with much smaller divergence.
  **Even worse:** the data warehouse at `data/historical/XAU_USD/` already contains 3 years of XAU/USD parquet sourced from TwelveData (manifest.json:23–29). `train_all.py` ignores it. `scripts/train_v2.py:57–82` reads it — but train_v2 only trains the v2 per-direction models. **The v1 voters that drive the live ensemble (smc, lstm, xgb, attention, dpformer, dqn) are all trained on yfinance GC=F.**
  **Fix:** Rewrite `fetch_training_data` in `train_all.py:105–174` to read `data/historical/XAU_USD/1h.parquet` first, fall back to yfinance only if the warehouse file is missing. Confirm features still compute correctly (they should — `compute_features` is symbol-agnostic). For a sanity check: load the warehouse parquet, compare distribution of `close` against yfinance `GC=F` closes for the same date range; expect ~1.5% systematic offset.

- **[CRITICAL] LSTM scaler is silently `fit_transform`'d at inference if not on disk**
  **Location:** `src/ml/ensemble_models.py:374–375` (`if is_fitted: data = scaler.transform(data); else: data = scaler.fit_transform(data)`)
  **Issue:** If `models/lstm_scaler.pkl` is missing, the inference path **fits a fresh MinMaxScaler on the inference window** (60 bars) instead of using the training-time scaler. This produces nonsense predictions silently — only a `logger.debug` warning ("LSTM scaler nie z treningu — fit_transform (mniej stabilne)"). Today the scaler exists (mtime 2026-04-24), but if a future retrain crashes mid-flight after writing `lstm.keras` but before `lstm_scaler.pkl`, inference will silently switch to per-window fit and predictions will diverge wildly with no alert.
  **Fix:** Promote that `logger.debug` to `logger.error` and return `None` (so the voter is marked unavailable in the ensemble) instead of `fit_transform`'ing. Same check for `attention_scaler.pkl`, `decompose_scaler.pkl`. Fail loud, don't degrade silently.

- **[CRITICAL] FEATURE_COLS is imported live, not pinned per-model**
  **Location:** `src/ml/ensemble_models.py:19` (`from src.analysis.compute import compute_features, FEATURE_COLS`); `compute.py:607–635`
  **Issue:** Models trained at git commit X have weights that expect `len(FEATURE_COLS) == N_X`. If we add a feature later and bump `FEATURE_COLS` to length `N_X+1`, every cached `.keras`/`.pkl` becomes wrong overnight — the model expects an N_X-wide input but `compute_features(...)[FEATURE_COLS]` now returns an N_X+1 wide DataFrame. There is no "this model was trained against feature list F" check. The only safety net is `n_features_in_` on XGBoost (which would error on shape mismatch), but Keras LSTM `.keras` will silently accept any input that has the right dim — it'll just produce noise.
  Evidence in registry: `training_history.jsonl` rows 2/3/4/5 from 2026-04-12 used 31 features (`n_features=31`); current `compute.py:607` defines 36. Today's loaded models claim n_features matching today's COLS list, so the bug is dormant — but the **only reason it works is everyone retrains together every time.**
  **Fix:** When `train_all.py` saves a model, persist a sidecar `models/{name}.feature_cols.json` containing the exact `FEATURE_COLS` list used. At inference, `_load_lstm()`/`_load_xgb()` etc. should compare against the live `FEATURE_COLS`; if mismatched, refuse to load and log error. Cheap, prevents an entire bug class.

- **[IMPORTANT] No automatic ONNX↔native parity test after conversion**
  **Location:** `train_all.py:657–686` (post-training ONNX export); `src/analysis/compute.py:214–290` (`convert_keras_to_onnx`, `convert_xgboost_to_onnx`); `tools/compile_xgb_treelite.py:69–94` (Treelite parity check)
  **Issue:** Treelite has a hard parity assertion (max-abs-diff < 1e-4 or compile fails). **ONNX conversion does NOT.** `convert_keras_to_onnx` returns a path on success and just logs. Every retrain blindly trusts the converted ONNX outputs match the Keras outputs. With opset 15 and `mixed_float16` Keras models, that's a non-trivial assumption — opset 15 doesn't fully support fp16 reductions, so silent dtype upcasting occurs.
  **Fix:** After `convert_keras_to_onnx` in `train_all.py:667`, run a 32-row holdout batch through both Keras `.keras` model and the freshly-written ONNX session, assert `max(abs(diff)) < 0.02`. Reuse the pattern from `tools/compile_xgb_treelite.py:70–94`.

- **[NICE] V2 XGB cache invalidates on json files but not feature_cols.json**
  **Location:** `src/ml/ensemble_models.py:404–449` (`_load_v2_xgb`)
  **Issue:** `_v2_xgb_cache` invalidates when `xau_long_xgb_v2.json` or `xau_short_xgb_v2.json` mtime changes, but the loaded `feature_cols` is read from `xau_long_xgb_v2.meta.json` ONCE at load time. If meta.json updates without touching the .json model, the cache won't reload feature_cols.
  **Fix:** Include meta.json mtime in the cache key.

---

### Deployment robustness

- **[IMPORTANT] `ONNX_FORCE_CPU=1` is set in `.env` — confirm this is intentional**
  **Location:** `.env:54` (`ONNX_FORCE_CPU=1`); `src/analysis/compute.py:201–203` (gates ALL ONNX providers down to `CPUExecutionProvider`)
  **Issue:** Per memory `onnx_force_cpu_workaround.md`: 2026-04-20 DirectML "device suspend" survived reboot, was forced to CPU as workaround. If still set tomorrow, the entire Treelite/ONNX/native chain will skip the GPU path; Treelite still wins for XGB (CPU-native), but LSTM/DQN/Attention all run on TF-CPU at inference, slower. The gating is correct (`get_onnx_providers()` returns `['CPUExecutionProvider']` only). But the ONNX session creation in `_load_lstm()` etc. will succeed with CPU provider — it doesn't refuse to convert+load just because GPU is forced off. So technically nothing breaks, just slower.
  **Fix:** Add `/api/health` field showing `onnx_force_cpu` status, audit weekly. If GPU has been stable for >2 weeks, retest by removing the .env line.

- **[IMPORTANT] Voter accuracy log shows lstm/xgb/attention with n=0 — voter watchdog is probably broken**
  **Location:** `data/voter_accuracy_log.jsonl` last 3 entries (2026-04-27 to 2026-04-29); `api/main.py:2208–2215` (`voter_live_accuracy` thresholds 0.7/0.3); `scripts/voter_watchdog.py:47–55`
  **Issue:** Watchdog calls `/api/voter-live-accuracy` which buckets predictions as "decisive" only when `val > 0.7` or `val < 0.3`. But XGB's empirical output range is **0.26-0.62** (per `ensemble_models.py:1010–1014`'s own comment) — so basically zero XGB predictions ever cross 0.7 or 0.3, and the watchdog reports `n=0` (insufficient) for XGB every single check. Same for Attention (range 0.35-0.63 per line 924). For LSTM the bullish-only mute (line 1196 `LSTM_BULLISH_ONLY = True`) means bearish LSTM samples are never written to `ml_predictions.lstm_pred` — only bullish LSTM crosses 0.7 ever fires. Net: **the watchdog only meaningfully tracks SMC and DQN.** A degraded LSTM/XGB/Attention model would not raise the flag.
  **Fix:** Use per-voter thresholds matching empirical output range. Quick win in `api/main.py:2210–2212`: pass `(0.55, 0.45)` for LSTM/XGB/Attention rather than `(0.7, 0.3)`. Cleaner: read each voter's actual std from `ml_predictions` and use mean ± 0.5σ.

- **[IMPORTANT] Drift alerts go only to Telegram, but Telegram bot was deleted 2026-04-17**
  **Location:** `src/ops/monitoring.py:25–38` (`_send_alert`); CLAUDE.md "Telegram bot deleted 2026-04-17"; `.env` still has `TELEGRAM_BOT_TOKEN`
  **Issue:** The .env tokens still exist, so messages probably reach Telegram and pile up unread. There is no Logfire span emission, no Sentry capture, no email, no console-level critical log on drift alerts. The 6h scheduled `check_and_alert_drift` (api/main.py:1465–1470) silently sends to a dead channel. **A model going bad would not surface in any monitoring dashboard.**
  **Fix:** Add a `logfire.warn("model_drift", ...)` call in `_send_alert` next to the Telegram POST so Logfire dashboard catches it. Also expose the recent-alert list at `GET /api/models/alerts` (already exists per `api/routers/models.py:186`) on the frontend's Models page Health widget.

- **[NICE] On model load failure, the voter is silently marked unavailable**
  **Location:** `src/ml/ensemble_models.py:931–940, 996–1002, 1041–1045` (each voter's `except` arm)
  **Issue:** Correctly fails open (ensemble continues with remaining voters) but only logs at `logger.debug` level. With 7 voters total, losing 2-3 silently still produces an ensemble signal. The compound override (DQN+SMC) only needs 2 voters to fire. So a half-broken ensemble can keep trading.
  **Fix:** Promote the load-failure log from `debug` to `warning`; emit a Logfire metric `voter_load_failures` per voter; if `models_available < 4`, force `ensemble_signal = 'CZEKAJ'` regardless of override paths.

---

### Drift monitoring

- **[CRITICAL] `compute_rolling_accuracy` joins ml_predictions↔trades on DATE — fragile**
  **Location:** `src/ml/model_monitor.py:75–84`
  **Issue:** SQL join is `JOIN trades t ON DATE(mp.timestamp) = DATE(t.timestamp) AND ABS(julianday(mp.timestamp) - julianday(t.timestamp)) < 0.02`. The 0.02-day tolerance = ~28 minutes. With multiple ml_prediction rows per scan (one every 5 min) and multiple trades per day, this join produces a Cartesian-style explosion when the date alignment is loose, especially across the CEST→UTC migration noted in CLAUDE.md `timestamp_tz_state`. Result: rolling accuracy can be wildly off — same `mp` row joined to two `t` rows counts twice.
  **Fix:** Trades carry their own `ml_prediction_id` foreign key (verify in schema); prefer that. Otherwise restrict to `ABS(julianday) < 0.005` (~7 min) AND `LIMIT 1` per ml_prediction.

- **[IMPORTANT] PSI is computed on a sliding 200-row window split in half — too small**
  **Location:** `src/ml/model_monitor.py:147–155` (LIMIT 200)
  **Issue:** PSI splits `ml_predictions` into "older 100 rows" and "newer 100 rows", computes PSI between distributions. With 5-min scanner cycles producing ~288 predictions/day, the "older half" is at most ~10 hours of history. That's not a baseline — that's intra-day micro-fluctuation. PSI > 0.25 will fire on routine intraday volatility regime shifts and never on the slow drift the metric is designed to detect.
  **Fix:** Reference distribution should be the first N predictions after the most recent retrain (read mtime of `lstm.keras` etc., select predictions where `timestamp BETWEEN retrain_ts AND retrain_ts + 7d` — that's the "honeymoon" baseline). Current = last 7 days. Compare those two.

- **[IMPORTANT] No baseline accuracy for ensemble or DQN**
  **Location:** `src/ml/model_monitor.py:287–299` (`_get_baseline_accuracy`)
  **Issue:** Returns `None` for both `dqn` and `ensemble`. So the accuracy-drop check at `model_monitor.py:243–255` literally cannot fire for those two — they're skipped. Yet ensemble accuracy is _the_ metric that matters (DQN-alone + SMC-alone are tracked elsewhere; their composite is the trade signal).
  **Fix:** After a successful retrain, capture rolling-accuracy on the val_df and persist as `ensemble_baseline_accuracy` in `dynamic_params`. Drift check then has something to compare against. For DQN, use `rl_best_reward` already persisted at `train_all.py:433`.

- **[NICE] `voter_watchdog.py` Telegram dependency**
  **Location:** `scripts/voter_watchdog.py:89–106`
  **Issue:** Same Telegram dead-channel issue. Auto-mute action (line 75–86) does change DB params (works fine), but the human notification fails silently.
  **Fix:** Add Logfire emission alongside the Telegram POST.

---

## Pre-training go/no-go

Block retraining until each is true. Items in this exact order — one fix unblocks the next.

- [ ] **Add seeds + `TF_DETERMINISTIC_OPS=1` + `enable_op_determinism()` to `train_all.py` top.** Copy the 7-line block from `scripts/train_v2.py:44–48`. Without this, two reruns produce different weights — you cannot debug a regression.
- [ ] **Switch training data source from yfinance `GC=F` to warehouse parquet `data/historical/XAU_USD/1h.parquet`.** This closes the $65-75 OOD gap. Same `compute_features(...)` call; the parquet has the same OHLCV columns. Falls back to yfinance only if warehouse file missing.
- [ ] **Add `log_training_run(...)` calls to all 5 sub-steps in `train_all.py` (XGB, LSTM, Attention, DPformer when re-enabled, DQN).** Without this, the next "which weights are live and from when?" question takes 20 min of git archaeology.
- [ ] **Make `train_all.py` invoke `tools/compile_xgb_treelite.py` automatically after XGB step (raise SystemExit on parity-check failure).** Belt-and-braces: also add Treelite mtime check + parity assertion to `_load_xgb()` so a stale .dll cannot serve stale predictions.
- [ ] **Add ONNX↔Keras parity test (max-abs-diff < 0.02 on 32-row holdout) inside `train_all.py:667` for each Keras→ONNX conversion.** Refuse to overwrite the ONNX file if parity fails.
- [ ] **Persist `models/{name}.feature_cols.json` sidecar after each model save; have `_load_*` refuse to load on FEATURE_COLS mismatch.** Cheap insurance against silent feature-list drift.
- [ ] **Fix scaler fail-loud: `ensemble_models.py:374–375` should return `None` (voter unavailable) instead of `fit_transform`-on-the-fly when `lstm_scaler.pkl` is missing.** Same for attention/decompose.
- [ ] **Lower voter watchdog thresholds from (0.7, 0.3) to (0.55, 0.45) for LSTM/XGB/Attention** so the live-accuracy log actually accumulates samples for those voters. Current state: lstm/xgb/attention have n=0 in voter_accuracy_log.jsonl, watchdog is effectively dead for them.
- [ ] **Decide: is `ONNX_FORCE_CPU=1` still required?** If the DirectML suspend is fixed, remove it; if not, document the workaround end-state.
- [ ] **Add Logfire warn-emission in `src/ops/monitoring.py::_send_alert`** so drift alerts surface somewhere a human will see (Telegram is dead per CLAUDE.md).
- [ ] **Capture ensemble + DQN baseline accuracy after retrain** to `dynamic_params` (`ensemble_baseline_accuracy`, `dqn_baseline_reward`) so drop-detection has a comparison anchor.

If any of the [CRITICAL] items above are deferred ("we'll fix in v2"), record an explicit note in `memory/next_session_2026-04-30_priorities.md` so the next session sees the debt.
