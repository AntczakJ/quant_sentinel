# Changelog

All notable changes to Quant Sentinel. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-05-02 — full audit + 17 commits + factor weight tuning APPLIED

After 49h continuous live run produced 5/5 LONG-LOSS = -$80.94, ran a
comprehensive audit and shipped 17 commits ranging from safety fixes to
forward-WR-improving analytics + tuning.

#### Critical bug fixes

- **`1a253cf`** — `_voter_value` persistence. For 24+ days, only lstm/xgb
  were being self-learner-tuned because muted voters (steady state at
  weight floor 0.05) had `status="muted_low_weight"` and `_voter_value`
  returned None for any voter with status field. Now: only
  `unavailable`/`disabled` → None; muted voters persist their value.
  Self-learner now tunes all 6 prob voters + DQN.
- **`f9d9712`** — DQN attribution wired (`dqn_action` 0/1/2 →
  HOLD/LONG/SHORT). Was previously frozen at init weight.
- **`0ee0a5d`** — `v2_xgb_pred` schema migration. v2_xgb was invisible
  to self-learner before; now in the loop.
- **`bebd89b`** — Phase 8 production weights restored after SHORT
  training overwrote `models/{xgb,lstm,attention}.{pkl,keras,onnx}`.
  SHORT models preserved at `models/short_2026-05-02/` (gitignored).

#### Scanner safety + correctness

- **`f9d9712`** — FVG-direction filter moved post-direction-set. Now
  uses `direction_str` instead of `current_trend` proxy, fixing the
  case where ML override produces direction != trend.
- **`0d91f69`** — Toxic-imminent gate (n>=15 AND WR<35% → demand active
  ML support, drop conflict threshold to 0.30). Self-defends BEFORE the
  full toxic n>=20 hard block. Currently fires for `[M5] Trend Bull +
  FVG` (n=22, WR 13.6%, count threshold-imminent).
- **`0d91f69`** — Lower scalp ML conflict threshold 0.65 → 0.50. Old
  was tuned when LSTM_BULLISH_ONLY masked LSTM bearish votes;
  post-Phase-8 all 4 ML voters bidirectional.
- **`f9d9712`** — `_relax` startup leak detection (logger.error
  once-per-process if BACKTEST_RELAX leaks to live worker).
- **`3c829f2`** + **`c6d763d`** — smc_engine defensive fixes:
  `find_ob_confluence` div-by-zero guard + `max()` empty default,
  `atr_mean` NaN-safe `tail(14).mean()`.

#### Database hygiene

- **`60381ec`** — `purge_old_rejected_setups(30d)` added to daily
  retention task. Was unbounded growth (~500 rows/day for 23 days).
- **`60381ec`** — `report_stale_params(60d)` read-only diagnostic.
- **`60381ec`** — `from_yfinance` warns CRITICAL when `yf_symbol="GC=F"`
  used with `symbol="XAU/USD"` ($65-75 spot/futures gap).

#### Observability + analytics (forward-WR)

- **`f9d9712`** — `model_agreement.decisive_ratio` and `available` keys
  added (additive, no behavior change).
- **`bd39b55`** — `ml_majority_disagrees` + ml_long/ml_short/ml_neutral
  counts in agreement output. Catches the 5/5 LONG-LOSS signature
  (ML voted SHORT but ensemble fired LONG due to SMC + weight gates).
- **`813a8d2`** — `factor_edge_report.py` empirical factor → outcome
  correlation. Cohort N=46 baseline 19.6% WR found:
    bos +20.4pp lift, ichimoku_bear +11.7pp (BUMPS),
    fvg -11.2pp, killzone -11.2pp, ichimoku_bull -8.5pp, macro -9.6pp (CUTS).
- **`813a8d2`** — `apply_factor_weight_tuning.py` **APPLIED** to live DB:
    weight_bos:           1.598 → 1.800
    weight_ichimoku_bear: 0.926 → 1.150
    weight_fvg:           1.281 → 0.700
    weight_killzone:      1.137 → 0.700
    weight_ichimoku_bull: 1.187 → 0.850
    weight_macro:         1.108 → 0.800
  Rollback: `python scripts/apply_factor_weight_tuning.py --rollback`
- **`14f0c87`** — `hourly_edge_report.py`. Cohort N=46 shows 4-7 UTC
  and 7-11 UTC consistently lose; 16-17 UTC NY best.
- **`80d2f4b`** — `analyze_short_shadow.py`. Awaits ≥30 post-restart
  trades for shadow data accumulation.
- **`bd39b55`** — `pattern_rolling_wr.py`. All-time vs 30d WR per
  pattern. Catches regime drift.

#### Training infrastructure

- **`9ef79fc`** — `QUANT_TRAIN_OUTPUT_DIR` env override in
  `MLPredictor.__init__` + `train_attention_model`. Prevents future
  SHORT-overwrites-LONG incidents (the 2026-05-02 cause).
- **`9ef79fc`** — `src/ml/short_shadow.py` SHORT XGB shadow logger
  wired into `_persist_prediction`. Lazy-loads
  `models/short_2026-05-02/xgb.pkl` (acc 60.3%); writes
  `shadow_short_xgb` to predictions_json each cycle. No live impact.
- **v2_xgb retrain** (background, models saved to `models/v2/`):
  - LONG XGB v2: best CV MAE (Huber) 1.46
  - SHORT XGB v2: best CV MAE 1.08 (lower error → SHORT more
    predictable in current regime)
  62 features (cross-asset + multi-TF + macro). Production unchanged.

#### Voter correlation re-validation

- Post-restoration re-run confirms Camp B remains broken:
  lstm↔attention direction agreement 52.9% (vs pre-Phase-8 89.4%).
  5 effective voters out of 5 loaded, no clusters at |r|>=0.85.
  Mean off-diagonal direction agreement 60.4%.

#### Tests + docs

- **`77fc171`** — 7 audit regression tests covering all FAZA changes.
  Total 459 tests passing (445 pre-existing + 7 audit + 7 new today).
- **`31d1614`** — CLAUDE.md streak threshold 5→8 docs sync,
  scanner.py:663 premium override comment fix.
- **memory/wr_improvements_2026-05-02.md** — full session retrospective.
- **memory/session_2026-05-02_full_audit.md** — audit phase narrative.

#### Pending Janek action

After API restart (waiting on him):
1. Treelite recompile: `python tools/compile_xgb_treelite.py`
2. Walk-forward 2-yr: `python scripts/run_walk_forward.py --start
   2024-04-01 --end 2026-04-01 --quick --out logs/wf_post_audit.json`

### 2026-04-30 (~13:10) — API restart + voter correlation BREAKTHROUGH

#### API restart on Phase 8 + LSTM-rerun models

- API uvicorn started 12:53:09 UTC, port 8000 active
- Preflight 12/12 PASS (after one bug fix to import the right loader names)
- All 9 BG tasks started (scanner 5min / prices 5s / resolver 5min /
  monitor 1h / retention 24h / health 10min / params-drift 30min /
  macro-snapshot 5min / replay 24h)
- Startup cleanup deleted 14 phantom trades (entry $2350 vs live $4720
  ref) — synthetic from pre-fix pytest pollution
- **First live trade #217**: LONG @ $4638.04 on M5, Grade B (40/100,
  7 SMC factors), RSI 72.6, Trend Bull + FVG, lot 0.01 (capped),
  R:R 2.0, generated 12:54:13

#### Voter correlation re-run on post-retrain models — BREAKTHROUGH

The 2026-04-29 D.2 audit found "Camp B" — lstm and attention with
**89.4% direction agreement** (effectively one voter wearing two hats),
opposed to "Camp A" (xgb/v2_xgb/dqn 67-84% mutual). Cross-camp
agreement only 10-19% = active signal cancellation. Effective voter
count was ~4 of 5 loaded.

After Phase 8 retrain on triple_barrier target with all leak fixes:

| Pair | 2026-04-29 (pre-retrain) | 2026-04-30 (post-retrain) |
|---|---|---|
| **lstm ↔ attention** | **89.4%** (Camp B) | **52.9%** (random) |
| xgb ↔ lstm | (not listed top) | 50.8% |
| lstm ↔ dqn | <19% (cross-camp) | 75.2% (new cluster) |
| v2_xgb ↔ dqn | 67-84% (Camp A) | 88.6% (preserved) |
| attention ↔ everyone | 89% with lstm | <55% with all |

**Result: ~5 effective voters out of 5 loaded.** No clusters at
|r| ≥ 0.85. Mean off-diagonal agreement 59.3% (diverse but not random).

Highest pairwise Pearson now: 0.305 (xgb-lstm), down from 0.40
(lstm-attention). Attention is **truly orthogonal** to every other
voter (Pearson < 0.1 across the row).

**Implications:**
- `LSTM_BULLISH_ONLY` hardcoded TRUE no longer needed (Janek can flip
  to `0` via .env after monitoring period). The bearish-anti-signal
  flag was for the pre-leak LSTM; the new LSTM with cleaned pipeline
  + triple_barrier target is bidirectionally honest.
- Phase 8 retrain met its **primary goal**: voter diversity restored.
- Sharpe -0.49 ensemble holdout is NOT from voter cancellation
  (resolved). It's regime mismatch — training data spans 2023-04 →
  2026-04 (mixed regimes including 2024 ranging period), holdout is
  most-recent ~6 months strong-bull. Live behavior on actual recent
  market regime should be more aligned.

The script bug (decompose_model import after Batch C.1 deletion) was
fixed in `eecaef5`.

### 2026-04-30 (~12:15) — Phase 8 finished + LSTM re-run with purge=12

Phase 8 overnight retrain completed exit 0 after 12h 28min wall-clock
(40,981s DQN alone — early-stopped at episode 177, patience=80
triggered when avg reward stopped improving).

#### Final Phase 8 results

| Voter | Walk-forward acc | Holdout acc | Holdout Sharpe |
|---|---|---|---|
| XGB | 0.629 | 57.6% | -0.78 |
| LSTM | 0.702 ⚠️ | 69.2% | -0.94 |
| Attention | 0.575 | (n/a) | (n/a) |
| DQN | early-stop ep 177, reward +14.37 | 0% (no trades) | 0 |
| **Ensemble** | — | **50.1%** | **-0.49** |

Ensemble holdout split: 287 LONG / 681 SHORT / 1758 CZEKAJ. Holdout
period was the most-recent ~6 months = strong bull. Models trained
on mixed regimes (2023-04 → 2026-04) over-predict SHORT in pure-bull
holdout → negative Sharpe.

Max DD on ensemble holdout: 9.6% — within the -10% threshold.

LSTM 0.702 walk-forward = the purge=5 vs needed=12 contamination flagged
mid-flight. Re-run with auto-purge=12 launched immediately after Phase 8
completion (background task `b0z541aef`, ~22 min ETA).

#### Treelite recompiled

`tools/compile_xgb_treelite.py` after Phase 8: parity 5.96e-08, native
sklearn 5.8ms vs Treelite 6.8ms median (Treelite slightly slower on
this batch — but N=1 inference path is what matters live).

#### Preflight: 12/12 PASS

After fixing one bug in the preflight script (`_load_attention` doesn't
exist — attention loads inside `predict_attention_direction`):

  - calibration_killswitch: PASS (DISABLE_CALIBRATION=1 in .env)
  - calibration_pkl_neutral: PASS (3 entries fitted=False)
  - feature_cols_pin: PASS (36 cols match in-memory FEATURE_COLS)
  - artifacts_present: PASS (all 6 model files)
  - treelite_freshness: PASS (fresher than xgb.pkl)
  - voter_loaders: PASS (xgb=treelite, lstm=onnx, dqn=loaded)
  - inference_smoke: PASS (xgb=0.493, lstm=0.488)
  - port_8000_free: PASS
  - pause_flag: PASS
  - db_clean: PASS (59 trades, 0 phantom OPEN)
  - voter_weights: PASS (sum=1.000, attention=0.33, xgb=0.33,
    smc/lstm/dqn/deeptrans=0.083 each, v2_xgb=0.0)
  - env_safety_flags: PASS (DISABLE_TRAILING=1, MAX_LOT_CAP=0.01)

#### Decision posture before API restart

Sharpe negative across all voters on holdout is a real concern but
plausible given:
  - Holdout period is monomorphic (strong bull) vs training
    multi-regime
  - Triple-barrier 2.0 ATR TP / 1.0 ATR SL is wider than typical
    holding period — TP seldom hit in 12-bar window
  - Models correctly flag uncertainty as CZEKAJ in 60% of bars
  - Live operational stack has multiple safeguards: kill-switch
    calibration, MAX_LOT_CAP=0.01, DISABLE_TRAILING, B7 SHORT-block,
    streak auto-pause, v2_xgb muted

Worst-case blast radius if SHORT-bias persists live:
  ~8 consecutive losses × 0.01 lot × ~$50 avg = ~$400 before
  auto-pause kicks in (streak threshold = 8).

Plan: complete LSTM re-run (purge=12) → re-verify preflight →
voter correlation re-run → THEN propose API restart with all
findings documented. User's call.

### 2026-04-30 (~01:00) — Inspection + preflight + audit polish (waiting for Phase 8)

While Phase 8 (overnight retrain) cooks, autonomous push 3 — close
the remaining low-hanging audit items + ship operational tooling for
the morning return.

#### `scripts/inspect_phase8_retrain.py` — overnight retrain summarizer

Parses `logs/phase8_retrain.log`, regex-extracts per-voter walk-forward
accuracies, DQN reward, Bayesian opt params, holdout backtest stats.
Compares against audit-derived thresholds:

  - voter accuracy: [0.50, 0.70]   (>0.70 = leak suspected)
  - DQN reward: > 0
  - PF: > 1.0
  - max DD: > -10%

Plus presence checks for required artifacts. Exit 0 = green / 1 = red /
2 = incomplete. Tested mid-Phase-8: correctly caught XGB 0.629 (OK),
Attention 0.575 (OK), LSTM 0.702 (RED — see below).

#### LSTM 0.702 finding + auto-purge fix

Mid-Phase-8 inspection caught LSTM walk-forward acc 0.702 — borderline
above the 0.70 red-flag threshold. Root cause: `WF_PURGE_BARS` defaults
to 5 (matches binary target's 5-bar lookahead) but triple_barrier with
`max_holding=12` needs purge=12. Last (12-5)=7 train bars had labels
depending on prices in the test slice.

XGB picked up only +0.05 lift from this — its stronger regularization
(depth=6, reg_alpha=0.1, reg_lambda=1.0) limits overfitting on the
leaky tail. LSTM with 50 epochs + EarlyStopping picked it up.

Fix: `train_all.py` now auto-extracts `max_holding` from the label
parquet filename pattern `..._max{N}.parquet` and sets
`WF_PURGE_BARS={N}` automatically when `--target=triple_barrier`.
Caller can still override via env var.

Phase 8 currently running already loaded train_all.py with default
purge=5 — its LSTM result is contaminated. Re-run LSTM after Phase 8
with the fix active. `tests/test_train_all_auto_purge.py` (8 cases)
locks regex + integration behavior so a future filename convention
change doesn't silently re-introduce the leak.

#### `scripts/preflight_api_restart.py` — 12-check sanity gate

Run BEFORE every `uvicorn ... start`, especially after a fresh
retrain. Catches the bug classes that bit us today:

  1. DISABLE_CALIBRATION=1 set in env or .env
  2. calibration_params.pkl all entries fitted=False
  3. models/feature_cols.json present + dim matches FEATURE_COLS
  4. xgb.pkl, lstm.keras, attention.keras + scalers present
  5. Treelite DLL fresher than xgb.pkl (else stale-DLL guard refuses)
  6. _load_xgb / _load_lstm / _load_attention all return non-None
  7. Inference smoke (xgb + lstm) returns finite [0, 1]
  8. Port 8000 free
  9. SCANNER_PAUSED flag check
  10. No phantom OPEN trades with entry < 1000
  11. Voter weights sum > 0.5 (else ensemble dead via floor mute)
  12. .env DISABLE_TRAILING + MAX_LOT_CAP set

Exit 0 = green; 1 = at least one failure (DO NOT start API).

#### `scripts/run_walk_forward.py --retrain` flag (P1.12)

Audit P1.12: walk-forward harness was passing `train_runner=None`,
making it a regime-stability test of static models, NOT walk-forward.
Now opt-in via `--retrain` flag — each window's `_xgb_only_train_runner`:
reads train slice from warehouse, joins USDJPY for macro features,
loads triple-barrier labels (auto-set WF_PURGE_BARS), calls
`ml.train_xgb` with precomputed_target. XGB-only (LSTM/Attention
would 30x runtime). Default mode stays --static.

Override target via env: `QUANT_WF_TARGET=binary` for legacy
compute_target. Default is triple_barrier when labels parquet exists.

#### `src/ml/decompose_model.py` — full delete (P2.5 final)

Voter was already dropped from production fusion in Batch C.1 (default
weights init + track-record loop). The .py file was kept as inert
dead code on the basis of "no runtime imports" — but
`tests/test_compute.py::TestDecomposition` still imported it. Now
fully gone:

  - src/ml/decompose_model.py: deleted (309 lines)
  - tests/test_compute.py::TestDecomposition: removed (2 tests)
  - test_compute.py: kept the deprecation comment as tombstone

The module's centered-convolution leak (`np.convolve(mode='same')`)
is now physically impossible to reintroduce. Inference stub at
ensemble_models.py:983 left as NEUTRAL return so DB writers don't break.

#### `LSTM_BULLISH_ONLY` env-overridable (P2.7)

Was hardcoded `True` based on 2026-04-16 finding. That finding was
on the PRE-cleaning-pipeline LSTM with multiple data leaks. Post-
Phase-8 retrain on warehouse + triple_barrier with all leaks closed,
the bearish anti-signal may not persist. Plus LSTM is currently
weight-floored anyway (0.05 in DB → muted).

Now reads `LSTM_BULLISH_ONLY` env, default "1" (preserves current
behavior). Flip to "0" via .env after Phase 8 + voter correlation
re-run validates new LSTM is bidirectionally sane.

#### Master audit closure status

19 of 22 findings closed across the day (86%). Remaining 3:

  - P1.6/P1.7 calibration redesign (DEFER until post-Phase-8 + 1 day live)
  - P1.10/P1.11 voter diversity (RESEARCH — re-run correlation post-retrain)
  - P2.4 confidence multipliers (DEFER until calibration redesigned)
  - P2.6 DeepTrans drop/shrink (DEFER until post-Phase-8 inspection)

All remaining items either need Phase 8 results to act on, OR are
low-priority polish that has no leverage until calibration is
redesigned.

### 2026-04-30 (early morning) — Phases 4 + 5 — canonical triple-barrier + train_all --target

Janek came back online and asked to push through the rest of the
sequence (Phase 1 smoke retrain → Phase 4 canonical TB → Phase 5
consumer wiring → Phase 6 smoke TB → Phase 8 overnight retrain).

#### Phase 1 — Full-data smoke retrain results

`train_all.py --source warehouse --tf 1h --skip-rl --skip-bayes
--skip-backtest --epochs 1 --seed 42` on 19,508 bars 1h XAU + USDJPY:

- XGB walk-forward accuracy: **0.526** over 5 folds, 13,655 train bars
- Top features: trend_strength (0.049), volatility (0.041), atr (0.041),
  vwap_distance_atr (0.040), atr_ratio (0.040)
- 36 FEATURE_COLS pinned to `models/feature_cols.json`
- Determinism block kicked in correctly (seed=42)

**THE honest baseline.** Pre-fix Decompose 0.769 / DPformer 0.78-0.80
were leak-inflated. Anything claiming 0.7+ accuracy after this point
should be re-investigated.

#### TF determinism seed bug

LSTM crashed in walk-forward fit with "Random ops require a seed
to be set when determinism is enabled." `train_all.py` sets
`TF_DETERMINISTIC_OPS=1` at module load, but the `tf.random.set_seed`
call was gated `if args.seed != 42` — so default runs left TF unseeded.
Fixed: ALWAYS seed (numpy + python + tf), regardless of override.

#### Phase 4 — Single canonical triple-barrier impl

Two parallel triple-barrier impls existed with **different encodings**
that would silently break any cross-consumer:

  src/learning/labels/triple_barrier.py    (canonical, encoding -1/0/1,
                                             integrated with 5+ scripts)
  tools/build_triple_barrier_labels.py     (mine, Numba JIT, 0/1/2)

Resolution:

1. **Library kept canonical.** `src/learning/labels/triple_barrier.py`
   now has a Numba-JIT inner kernel (~60x speedup on 100k+ rows). Public
   API unchanged. Encoding stays -1/0/1. All 12 existing label tests pass.

2. **CLI rewritten as thin wrapper.** `tools/build_triple_barrier_labels.py`
   delegates math to the library. Computes ATR (Wilder 14-period) since
   library expects an `atr` column, then calls
   `triple_barrier_labels(direction='both')` + `r_multiple_labels`.
   Output schema:
     datetime, close, atr,
     label_long, bars_to_exit_long, exit_price_long,
     r_long, r_mfe_long, r_mae_long,
     label_short, bars_to_exit_short, exit_price_short,
     r_short, r_mfe_short, r_mae_short

3. **Old encoding parquets deleted + regenerated.** Three TFs on full
   warehouse 2023-04 → 2026-04:

   | TF    | Bars   | LONG TP | LONG avg_R | SHORT TP | SHORT avg_R |
   |-------|--------|---------|-----------|----------|-------------|
   | 5min  | 232k   | 33.4%   | +0.272    | 31.0%    | -0.069      |
   | 15min | 78k    | 30.9%   | +0.245    | 27.4%    | -0.082      |
   | 1h    | 19k    | 28.5%   | +0.342    | 24.0%    | -0.086      |

   Bull-market sanity: LONG +R drift, SHORT -R for entire period.

4. **CLI bug caught + fixed:** my pre-refactor code did
   `rm_both.iloc[:, 1].values` for r_short, which is the SECOND
   column of `r_multiple_labels`' DataFrame — but that's
   `r_mfe_long`, not `r_realized_short`. Result: SHORT avg_R
   showed +1.925 (the LONG max-favorable-excursion in a bull market).
   Now uses explicit `rm_both["r_realized_short"]`.

5. `tests/test_triple_barrier_labels.py` rewritten — schema verifies
   new column names, encoding asserts canonical -1/0/1. 18/18 label
   tests pass (12 library + 6 CLI wrapper).

#### Phase 5 — train_all --target {binary, triple_barrier}

`src/ml/ml_models.py::train_xgb` and `train_lstm` accept new optional
`precomputed_target=None` arg. None → legacy `compute_target`
(backwards-compatible). When supplied, target overrides the legacy call.

`train_all.py` adds:
  --target {binary, triple_barrier}    (default: binary)
  --target-direction {long, short}     (default: long)

When `--target=triple_barrier`:
  1. Globs `data/historical/labels/triple_barrier_{symbol}_{tf}_*.parquet`
     and picks the most-recently-modified file.
  2. Joins labels to train_df by datetime.
  3. Maps -1/0/1 → binary `(label_long == 1).astype(int)` — model
     learns "did LONG hit TP" (TIMEOUT and SL both → 0). Directly
     aligned with how we trade.
  4. Passes binary Series as `precomputed_target` to XGB and LSTM.

For per-direction training: invoke twice with `--target-direction long`
then `short`. Future: 3-class classifier head learning -1/0/1 directly
(Batch E+1).

`scripts/smoke_train_xgb_triple_barrier.py` (new) — XGB-only smoke
test for the triple-barrier path. Pairs with the existing
`smoke_train_xgb.py` (binary). When both produce sane numbers, Phase 8
overnight retrain is ready to ship.

### 2026-04-29 (night) — P2.2 + P2.3 + smoke validator

Three additional polish commits after Batches B + C + D.1.

#### P2.2 — walk-forward purge + embargo

`compute_target` looks 5 bars ahead so the last 5 train labels depend
on prices that fall in the next test slice — every reported fold
accuracy was biased upward by an unknown systematic amount. Both
`train_xgb` and `train_lstm` walk-forward loops now drop `WF_PURGE_BARS`
(env, default 5) bars from the END of each train slice, then skip
`WF_EMBARGO_BARS` (default 1) bars before test starts. Configurable so
when triple-barrier consumers ship (`WF_PURGE_BARS=60` to match
`max_holding`) the same harness extends.

#### P2.3 — v2 R-multiple objective MSE → pseudo-Huber

R-multiple distribution has fat tails (TIMEOUT outcomes ±2..±5 ATR).
MSE squared those tails into dominating training weight. Optuna search
in `scripts/train_v2.py` now uses `reg:pseudohubererror` (with
`huber_slope` in 0.5..2.0 search space), CV metric switched to MAE.
Final model also uses pseudo-Huber. Meta JSON renamed `best_cv_mse` →
`best_cv_metric`.

#### `scripts/smoke_train_xgb.py` — pipeline validator

End-to-end smoke run on a 6-month XAU 1h slice (~4500 bars, ~15-30s).
Verifies warehouse read + USDJPY alignment + compute_features (post
ffill fix) + feature_cols.json pinning + DISABLE_CALIBRATION + purge
defaults. Backs up `models/xgb.pkl` and restores after. Smoke artifacts
go to `models/_smoke/`.

**First-run baseline:** walk-forward accuracy **0.578 over 5 folds**.
This is THE honest number. Pre-fix Decompose 0.769 and DPformer
0.78-0.80 were leak-inflated by `np.convolve(mode='same')` and
scaler fit-on-full-set. Any future training that beats 0.58 after
the fixes is real lift; anything claiming 0.7+ should be re-investigated.

Use this BEFORE every full retrain to catch plumbing regressions in
seconds instead of after a 4h training run.

### 2026-04-29 (late evening) — Batches B + C + D.1 — close 6 P0/P1 audit blockers

Following up on the four-agent audit verdict from earlier in the
evening. Janek pushed back ("a czemu nie dzisiaj?") on my conservative
"queued for tomorrow" framing — the queueing was unjustified scoping,
not a real blocker. Pushed through B + C + D.1 in the same session;
only Batch E (actual retraining, multi-hour compute) is held back so
the cleaned pipeline can be verified end-to-end before burning hours.

#### Batch B — training pipeline rewrite

`train_all.py` now reads the 3-year TwelveData warehouse parquet
instead of yfinance GC=F (Gold Futures, $65-75 spot-vs-futures gap).
USDJPY macro proxy switched to warehouse parquet too.

- New CLI: `--source warehouse|yfinance` (default warehouse),
  `--tf 5min|15min|30min|1h|4h|1day` (default 1h), `--seed N`
- Determinism block at module top: PYTHONHASHSEED, TF_DETERMINISTIC_OPS,
  TF_CUDNN_DETERMINISTIC, random.seed, np.random.seed (mirrors
  `scripts/train_v2.py:43-48`)
- `models/feature_cols.json` written after every training run with
  the FEATURE_COLS list + n_features + trained_at + source/tf/symbol.
  Inference can now assert dim parity instead of trusting re-import.
- `cal.fit_all()` post-training step DISABLED — would re-fit the
  same broken `fit_from_history` pattern that produced the inverted
  Platt parameters. Kill-switch from Batch A handles inference.
- `_load_xgb` refuses to serve a stale `xgb_treelite.dll` (mtime
  older than `xgb.pkl` by >1s). Logs warning, falls through to ONNX
  or sklearn. Forces `tools/compile_xgb_treelite.py` rerun after
  retraining.

#### Batch C.1 — drop Decompose voter

Future-leak confirmed: `np.convolve(mode='same')` is symmetric and
pulls 10 future bars into trend at bar t. Voter was already
weight-muted (0.05 floor) but the leak surfaced as 78-80% val_acc
which mis-led training-time evaluation. Removed from default
weights init AND models track-record loop in `ensemble_models.py`.
Inference stub left as NEUTRAL (downstream consumers see stable
shape). `decompose_model.py` source not deleted yet (dead code, full
sweep is follow-up).

#### Batch C.2 — scaler fit per-fold (LSTM / Attention / DeepTrans)

Three voters had MinMaxScaler/StandardScaler fit on the FULL training
set BEFORE walk-forward fold split — fold 1 saw fold N+1 statistics.
Refactored to per-fold pattern:

```python
for fold_train, fold_val in tscv.split(X_full):
    scaler = MinMaxScaler().fit(X_full[fold_train])
    X_train = scaler.transform(X_full[fold_train])
    X_val   = scaler.transform(X_full[fold_val])
    # ...
final_scaler = MinMaxScaler().fit(X_full)  # save for inference
```

Files: `src/ml/ml_models.py` (LSTM), `src/ml/attention_model.py`,
`src/ml/transformer_model.py` (DeepTrans, has 80/20 split not WF —
same class of bug, same shape of fix).

Verification: `scripts/verify_scaler_per_fold.py` (new) monkey-patches
`MinMaxScaler.fit` to log shapes, drives all three train fns. Asserts
>1 fit() call and distinct sizes. PASS for all three (LSTM 6 fits,
Attention 4 fits, DeepTrans 2 fits).

#### Batch C.3 — features_v2 ffill leak fix

Audit doc `docs/strategy/2026-04-29_audit_features_v2_ffill.md`
revealed: TwelveData warehouse parquets label bars by START time, so
a 5m anchor at 14:30 ffilled with the 1h bar labeled 14:00 reads a
`close` that materializes at 15:00 (+30 min look-ahead). +3h55m on 4h,
+23h55m on daily projection. Three call sites fixed:

- `features_v2.py::_align_to_index` (cross-asset)
- `features_v2.py::add_multi_tf_features` (HTF projection)
- `compute.py` USDJPY block

All three now shift the source index FORWARD by one source-interval
before reindexing — so the 5m anchor reads the bar that already
CLOSED, not the one currently in progress. v2_xgb's "PF 2.24 OOS"
finding from 2026-04-25 was contaminated by this leak; voter weight
muted in DB from 0.10 → 0.0 pending walk-forward re-validation on
shifted features.

#### Batch D.1 — wire update_ensemble_weights to resolver

`update_ensemble_weights` was defined in `ensemble_models.py:726` but
never called anywhere. Voter weights frozen at hand-mutated values
forever — self-learning effectively dead.

Wired into `_auto_resolve_trades` (api/main.py) immediately after
`update_factor_weights`. For each resolved trade:

1. Query matching `ml_predictions` row by `trade_id`.
2. Compute `long_was_winning` = (status WIN ∧ direction LONG) ∨
   (status LOSS ∧ direction SHORT).
3. For each voter raw P(LONG wins): correct iff `(P > 0.5) ==
   long_was_winning`.
4. Pass correct/incorrect lists to `update_ensemble_weights` with
   learning_rate=0.02 (existing EMA-smoothed update fn).

Wrapped in try/except + debug error so a malformed prediction row
never crashes the resolver loop.

### 2026-04-29 (evening) — Pre-training audit (NO-GO) + Batch A hotfixes

Four parallel read-only audit agents launched before authorizing any
retraining. All four reached NO-GO independently. 15 distinct findings
ranked P0/P1/P2/P3. Batch A (P0 hotfixes) shipped same evening; Batches
B-E queued for following sessions.

#### Added — `docs/strategy/2026-04-29_audit_{1..4}_*.md` + `_pretraining_master.md`

Five-doc audit set saved to `docs/strategy/`:

- `audit_1_data_leaks.md` — 6 CRITICAL data-leak paths in features
  (centered convolution in Decompose; scaler fit-on-full-set in all 4
  neural voters; multi-TF and USDJPY ffill leaking +30 min into v2_xgb
  which is LIVE @0.10).
- `audit_2_architecture.md` — capacity vs data ratio, voter diversity
  (4 ML voters share the same 34-feature vector — different inductive
  biases on identical info don't decorrelate).
- `audit_3_reprodeploy.md` — `train_all.py:117-127` fetches yfinance
  `GC=F` (Gold Futures) for training; live inference uses TwelveData
  XAU/USD (Spot Gold). $65-75 price gap. Plus zero determinism seeds
  in `train_all.py` and no stale-dll detection for Treelite XGB.
- `audit_4_label_ensemble.md` — Platt calibration parameters
  mathematically inverting signals (`a≈-0.17` for all 3 calibrated
  voters); `update_ensemble_weights` defined but never called →
  voter weights frozen at hand-mutated values; the "7-voter ensemble"
  is in fact 3 voters because the other four sit at floor weight 0.05
  below the 0.10 active threshold; just-shipped triple-barrier labels
  not wired anywhere.
- `pretraining_master.md` — synthesis of all four with severity-
  ranked deduplication, fix order Batches A–E, pre-training go/no-go
  checklist.

#### Fixed — `src/ml/model_calibration.py` — `DISABLE_CALIBRATION` env flag (P0.1)

`ModelCalibrator.calibrate` early-returns the raw prediction unchanged
when `DISABLE_CALIBRATION=1`, bypassing both the fitted-Platt path
AND the 20% uncalibrated-shrinkage path. Set in `.env`. Reversible.

Pre-existing `models/calibration_params.pkl` backed up to
`models/calibration_params_2026-04-29_inverted.pkl.bak` and overwritten
with all `fitted: False` (defense-in-depth — env flag is primary).

The audit verified by loading the .pkl directly and simulating the
mapping across raw 0.10..0.90: output stuck in 0.36..0.40 monotonic
DECREASING in raw, i.e. high raw → low calibrated → ensemble votes
SHORT regardless of model output. Live since the calibration was last
fit; explains why live cohort PF 0.83, return -1.08% pattern resembles
near-random with slight negative drift.

#### Fixed — `tests/test_local_db.py`, `tests/test_new_features.py` — pytest no longer pollutes `data/sentinel.db`

While preparing Batch A: discovered 14 phantom trades (ids 203-216) in
production `sentinel.db` with identical entry=$2350 (live XAU is ~$4574).
Source:

```
tests/test_local_db.py:8       os.environ['DATABASE_URL']='data/sentinel.db'  ← prod!
tests/test_local_db.py:63      db.log_trade('LONG', 2350.0, ..., 'TEST', ...)
tests/test_new_features.py:214 db.log_trade(direction='LONG', price=2350.0, ...)
```

Both are script-style (no `def test_*`); pytest imports them during
collection, runs the module body, inserts trades. Each `pytest tests/`
ran 2 inserts. Fix:

1. Both files now create a per-process tempfile SQLite, set
   `DATABASE_URL` to it BEFORE any database import.
2. After setenv they call `_reinit_connection_for_test()` to invalidate
   any cached module-level `_conn` from earlier test imports — without
   this, an earlier test's `from src.core.database import NewsDB` would
   pin `_conn` to prod and our setenv would have no effect.
3. Best-effort tempfile cleanup on `atexit` (Windows file-lock
   tolerated).
4. Phantom trades 203-216 marked `status='CANCELED'` with audit
   reference in `failure_reason` — prevents API auto-resolver from
   trying to close them against $4574 live price (which would mint
   fake $200 instant-TP profits each).
5. `data/sentinel_backup_2026-04-29_pre_calibration_neutralize.db`
   snapshotted before any DB mutation (gitignored).

#### Tests

`tests/test_new_modules.py::TestModelCalibrator` gains
`test_calibrate_disabled_returns_raw` (verifies kill-switch identity
for both fitted-voter path and unknown-voter path) +
`test_calibrate_unknown_model_applies_shrinkage` gains a
`monkeypatch.delenv` to make the existing test env-independent.

Full pytest: **429 passed / 1 skipped** (was 412/1 yesterday). Verified
`pytest tests/ -q` does NOT increase `sentinel.db` trade count (59 → 59
after a clean run).

#### Not changed — pending user approval

- API NOT restarted yet. Calibration kill-switch takes effect on next
  uvicorn reload because the calibrator caches at module import.
- No retraining. P0.2 (yfinance vs TwelveData training/inference
  distribution mismatch) and P0.3 (v2_xgb features_v2 ffill leak) are
  still active and need Batches B + C before any model is touched.

### 2026-04-29 (late) — sim_time helper + triple-barrier labels + lot-sizing scaffold

Big-batch session: closed the sim-time leak family on the deepest level,
shipped Phase 2 master-plan core (triple-barrier label builder), and
scaffolded Lot Sizing Option A behind an env flag for the 2026-05-04
decision gate. rsi_extreme audit landed (verdict: WAIT — sample drift
flipped the headline 57.4% claim to 32.4%; do not act).

#### Added — `src/trading/sim_time.py` (single source of truth for "now")

Centralizes the sim-vs-wall-clock decision in a single helper that the
backtest harness, scanner filters, smc_engine session classifier, and
Asia ORB voter all share. Production paths default-call wall-clock UTC;
when `QUANT_BACKTEST_MODE=1` and `scanner._SIM_CURRENT_TS[0]` is bound
by `run_production_backtest.py`, we return the simulated bar timestamp.

#### Fixed — three deeper sim-time leaks (not in the original A+B1+B2+B3 family)

The 2026-04-29 audit pattern (`grep -nE "datetime\.now|_persistent_cache"
src/trading/`) surfaced four more wall-clock reads that contaminated
backtest factor scoring. All routed through the new `sim_time.now_utc()`:

- `src/trading/smc_engine.py::is_market_open` — was anchoring CET
  weekend/hour gating to wall-clock when called without a `dt_cet` arg
  (every call site in scanner does this).
- `src/trading/smc_engine.py::get_active_session` — same pattern;
  session classification (overlap/london/ny/asian/off_hours/weekend),
  which feeds both the +15 Asia ORB factor and the session-based risk
  multiplier in `finance.py:104` (overlap=1.0x, asian=0.6x, etc.),
  was using TODAY's UTC hour for any 2024 setup.
- `src/trading/asia_orb.py::get_asia_range` — Asia window anchoring
  defaulted to wall-clock, so backtests built ranges from today's
  Asian session and never produced ORB hits on historical bars.
- `src/trading/asia_orb.py::detect_orb_signal` — same default.

Net effect: with these fixes, a 2024 backtest now classifies session,
killzone, and Asia ORB on the actual simulated hour. Production
behavior is unchanged (env flag unset → wall-clock fallback).

#### Added — `tools/build_triple_barrier_labels.py` (Phase 2 master plan core)

Replaces the binary `compute_target` (0.5 ATR up-move within 5 bars,
flagged tautological in `memory/label_baseline_2026-04-26.md`) with
proper triple-barrier labels per López de Prado:

- For each anchor bar, simulates LONG and SHORT entries, walks forward
  up to `max_holding` bars, and records first-barrier-touched as one
  of {WIN, LOSS, TIMEOUT} with R-multiple.
- Numba-JIT inner loop processes XAU 5min full warehouse (232,129 rows)
  in 2.9s; falls back to pure-numpy when Numba unavailable.
- Output: `data/historical/labels/triple_barrier_{symbol}_{tf}_tp{N}_sl{N}_max{N}.parquet`.

**First-pass distribution** (TP=2*ATR, SL=1*ATR, RR=2, on full warehouse):

| TF    | Bars   | LONG TP | LONG avg_R | SHORT TP | SHORT avg_R |
|-------|--------|---------|-----------|----------|-------------|
| 5min  | 232k   | 33.4%   | +0.054    | 31.0%    | -0.022      |
| 15min | 78k    | 30.9%   | +0.058    | 27.4%    | -0.063      |
| 1h    | 19k    | 28.6%   | +0.093    | 24.0%    | -0.082      |

Validates: random LONG entry on 2023-2026 XAU has positive expected R
across all TFs (gold drift); random SHORT has negative R. Filter
job is to push WR above the 30%-band baseline. **No model training
yet** — labels exist, v2 XGB consumption is the next phase.

#### Added — `USE_FLAT_RISK` env-flag scaffold in `src/trading/finance.py`

Per `docs/strategy/2026-04-27_lot_sizing_rebuild_design.md` Option A:
when `USE_FLAT_RISK=1`, replaces the entire Kelly + daily-DD + session
+ vol + loss-streak risk-percent compounding stack with a single explicit
percentage (default 0.5%, configurable via `FLAT_RISK_PCT`). Logs both
"would have used X%" and "now using Y%" for audit.

**OFF by default — no behavior change today.** Decision gate remains
2026-05-04 per design doc; this is reversible plumbing only.

#### Added — `docs/strategy/2026-04-29_rsi_extreme_audit.md`

Re-runs the 2026-04-27 finding "rsi_extreme SHORT 57.4% WR n=101
(Bonferroni-clear)" against current data. **Verdict: stale.** Sample
grew n=101 → n=232 (+128%); SHORT WR dropped to 32.4% (Wilson 26-40%).
The single-window result reversed under more data — exactly the
overfitting-check failure mode `feedback_overfitting_check.md` warns
about. Bimodal sub-finding: RSI<5 SHORT 95.2% WR (n=42) vs RSI 5-15
SHORT 0% WR (n=70) — but action deferred until macro_snapshots can
backfill regime context (currently 29 rows from 2026-04-27 only).

Side-finding: 4h SHORT rejections show constant `rsi=22.8` across
28 rows — a logging artefact worth investigating separately.

#### Tests

- `tests/test_sim_time.py` (6 cases) — sim/wall fallback, env-flag
  behavior, end-to-end through smc_engine.get_active_session and
  asia_orb.get_asia_range with simulated 2024-08-15 anchor.
- `tests/test_triple_barrier_labels.py` (6 cases) — barrier ordering,
  TP-hit, SL-hit, timeout, sentinel for no-lookahead, real XAU 5min
  distribution sanity.
- `tests/test_finance_flat_risk.py` (4 cases) — env-flag presence,
  default pct, custom pct.

Total new: 16 cases. Full pytest: **428 passed / 1 skipped** (was
412/1 before this batch; +16 = exactly the new tests).

### 2026-04-27 (late evening) — Factor audit + macro snapshots + walk-forward unblock

WR-improvement push that intentionally avoids touching live trading
config (live cohort still N=3 — too small for any tuning). Three
research-side deliverables:

#### Added — `scripts/factor_importance_audit.py`
Twin-view factor importance analysis with overfitting guards:
- **Trade-side** (n=32): per-factor presence vs WIN/LOSS, Fisher exact,
  Bonferroni multi-comparison correction, direction split, time slice
  pre/post Phase-B.
- **Rejection-side** (n=9227 logged, only n=40 resolved): per-filter
  would-have-WR vs baseline. Reveals the rejection resolver was never
  built — `docs/SHADOW_LOG_DIRECTIONAL_ALIGNMENT.md` designs
  `scripts/replay_directional_alignment.py` but it doesn't exist.
- Output: `docs/strategy/2026-04-27_factor_importance_audit.md`.

**Realne odkrycie** (early signal, sample limited):
`bos` (Break of Structure) jest najsilniejszym predyktorem WR mamy:
+40.9pp delta (46% z vs 5% bez), n=13/32, raw p=0.010. LONG-only
view nawet ostrzejszy: +50pp przy n=4. Hypothesis worth re-testing
when sample reaches 100+. **Nie podejmujemy akcji** dopóki próbka
nie urośnie i nie przejdzie Bonferroni.

#### Added — `macro_snapshots` table + persister BG task
- New SQLite table `macro_snapshots` (id, timestamp, macro_regime,
  usdjpy_zscore, usdjpy_price, atr_ratio, uup, tlt, vixy,
  market_regime, signals_json) with indexes on timestamp + regime.
- `NewsDB.write_macro_snapshot(...)` and `get_recent_macro_snapshots()`.
- `_persist_macro_snapshots` BG task in `api/main.py` lifespan —
  5 min cadence, decoupled from trade evaluation, survives
  scanner pause. Activates on next API restart.
- New endpoint `GET /api/macro/snapshots?limit=N` — paginated history.
- **Why:** the 2026-04-27 SHORT #200 forensics had to infer
  `macro_regime` from `factors`-dict presence (no `short_in_bull_regime`
  key meant regime wasn't zielony). With persistence we get direct
  ground truth — enables future B7-efficacy audits, regime-conditioned
  WR analyses, and the factor-audit's "did edge depend on regime?"
  question.
- **First snapshot recorded** (smoke test):
  `regime=zielony, USDJPY z=−1.14, ATR ratio=1.00, market=ranging`,
  i.e. B7 currently ARMED for any SHORT setup.

#### Fixed — `src/backtest/walk_forward.py` (three bugs in one harness)

The walk-forward harness existed in `src/backtest/walk_forward.py` +
`scripts/run_walk_forward.py` but had three layered bugs that meant it
had never produced honest results:

1. **WinError 2 — relative interpreter path.** `.venv/Scripts/python.exe`
   was passed as the subprocess argv[0] without resolving against the
   repo root, so it only worked when CWD was the repo root. Fixed with
   absolute path from `__file__`, `sys.executable` fallback, and
   explicit `cwd=repo_root` on the subprocess.

2. **AttributeError — Windows cp1252 stdout.** `subprocess.run(text=True)`
   uses the platform locale codec for decode, which is cp1252 on
   Windows. The backtest's UTF-8 dashes / Polish chars trip that decode
   and `result.stdout` becomes `None`, then `splitlines()` explodes.
   Fixed by `encoding="utf-8", errors="replace"` plus child env
   `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`. Also rerouted the
   results parsing — instead of fragile stdout grep on the FINAL
   RESULTS block, use `--output <tmp.json>` and load the dict directly.

3. **Silently identical windows — env var nobody reads.** The runner
   set `BACKTEST_START_DATE=<window>` env var per cycle, but
   `run_production_backtest.py` doesn't read that variable. It uses
   `--start` / `--end` CLI flags or falls back to "last N days from
   data tail". So **every window backtested the same default range**
   and produced identical metrics. Caught only when window 0-3 all
   came back as `4 trades, 0 wins, -27.30 PnL` exactly. Fixed by
   passing `--start` and `--end` explicitly to the subprocess.

After all three fixes, `scripts/run_walk_forward.py --quick` runs
end-to-end and produces window-distinct results. Smoke run on
2026-Q1 warehouse data is a 30/7/14 walk-forward (4 windows).

#### Added — `scripts/replay_directional_alignment.py` (built + run)

Implements the spec from `docs/SHADOW_LOG_DIRECTIONAL_ALIGNMENT.md`.
Reads forward bars from the local 5-min warehouse parquet (no API hits)
and walks bar-by-bar to determine whether each rejected setup would have
hit TP or SL first. Updates `would_have_won` per row.

**First full run resolved 8,450 of 9,294 unresolved rejections in 15 s**
(844 skipped because they happened after the warehouse cutoff). The DB
went from "40 resolved / 9,227 NULL" to "8,490 resolved / 844 NULL"
in one execution.

Two metrics surfaced separately to avoid the loose-criterion bias:
- **WR_strict** = TP-hits / (TP-hits + SL-hits) — only setups that
  resolved at a level. Compares directly to the `1 / (1 + R_target)`
  break-even (33.8% at R=1.96).
- **WR_loose** = any-positive / total — includes time-exits with
  PnL>0 from a barely-green close. Easy to confuse with edge.

**Findings on the resolved sample (mostly W15-W17 of 2026):**

| Filter | n@level | WR_strict | Verdict |
|---|---:|---:|---|
| `session_performance` | 43 | 0.0% | ✅ catches losers (perfect) |
| `directional_alignment` | 419 | 11.5% | ✅ catches losers (closes shadow-log study; <45% bucket → "validate hard-block stays") |
| `confluence` | 1,305 | 24.1% | ✅ catches losers |
| `toxic_pattern` | 228 | 19.3% | ✅ catches losers |
| **`rsi_extreme`** | **154** | **45.5%** | **🚨 BLOCKS WINNERS** (Bonferroni p=0.022) |
| `atr_filter` | 220 | 40.0% | neutral after correction |

After Bonferroni multi-comparison correction over 6 filters with
n_at_level ≥ 30, **only `rsi_extreme` clears the 0.05 threshold as a
"blocks winners" candidate**. (An earlier draft of this changelog
flagged `atr_filter` too; that was an artefact of an audit-script bug
treating `would_have_won ∈ {2, 3}` time-exit codes as wins. Fixed.)

**Direction split for `rsi_extreme`** (the one survivor):
- LONG: 22.6% WR_strict (n=53) — catches losers correctly
- SHORT: 57.4% WR_strict (n=101) — Bonferroni p<0.0001 corrected

**Per timeframe** (`rsi_extreme`):
- 30m: 94.4% WR (n=18) ↘ underpowered
- 15m: 65.2% WR (n=23)
- 5m:  47.0% WR (n=66)
- 1h:  36.8% WR (n=19) ↘ underpowered
- 4h:   0.0% WR (n=28) — sample skewed; SL bias

**Actionable (with overfitting caveats):** `rsi_extreme` appears to
be over-rejecting SHORT-side setups in the W15-W17 window. But: (1)
sample is one 17-day window in one regime, (2) `macro_snapshots`
wasn't persisted then so we can't slice by regime, (3) walk-forward
is still pending. **Not a live config change.** Hypothesis tracked
for re-test once `macro_snapshots` accumulates 2+ weeks of regime
data and the daily replay cron resolves a wider sample.

#### Added — `_replay_rejections_daily` BG task

Runs the replay script once per 24h via subprocess (same pattern
walk_forward uses for run_production_backtest). 30-min boot delay
to avoid competing with scanner. Logs `[replay] daily run done — N
rows resolved` per cycle. Pairs with `_persist_macro_snapshots` so
each future rejection gets BOTH ground-truth outcome AND regime
context — the missing piece for proper regime-conditioned filter
audits. Activates on next API restart.

Caveat: rejections within ~hold_cap (4 h) of "now" can't be replayed
until the warehouse is refreshed past their forward window, so they
stay NULL and get picked up on a later night's run. Warehouse refresh
cadence is a separate question (currently manual).

### 2026-04-27 (evening) — Modal TF GPU fixed end-to-end

The "TF falls back to CPU on Modal T4" issue tracked since the Modal
pipeline went live is now resolved. Diagnostic verdict:

```
[1/5] nvidia-smi:        Tesla T4, 15360 MiB, driver 580.95.05    OK
[2/5] nvidia/* pkgs:     14 (cublas/cudnn/cuda_runtime/...)        OK
[3/5] TF import:         tf=2.21.0 in 5.86 s                       OK
[4/5] list GPU devices:  1 GPU [/physical_device:GPU:0]            OK
[5/5] 512×512 matmul:    55.87 ms on /GPU:0                        OK
VERDICT: TF GPU is OPERATIONAL ✓
```

#### Fixed
- **Image base swap**: `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`
  + `add_python="3.13"` → `debian_slim(python_version="3.13")`. The
  CUDA base shipped cuDNN ~9.0/9.1 (paired with CUDA 12.4) but TF 2.21
  expects CUDA 12.5+ + cuDNN 9.3+. The system cuDNN was getting
  resolved before the pip-installed `nvidia-cudnn-cu12==9.21.1.3`,
  silently breaking GPU init. New image lets `tensorflow[and-cuda]`
  own all CUDA + cuDNN end-to-end via pip — no system libs to
  conflict with. Same TF version, same train_all.py — only the
  underlying base image changed.
- **TF version pin**: bumped from `>=2.20` to `==2.21.0` in the Modal
  image so cuDNN co-install version (9.21.1.3) stays locked-in. uv
  lock already had 2.21.0 resolved; this just stops a future TF 2.22
  surprise from drifting the cuDNN version.

#### Added
- **`gpu_diagnostic` Modal function** + **`gpu_check` local entrypoint**
  in `tools/modal_train.py`. 5-step probe: nvidia-smi → site-packages
  inventory → TF import → `list_physical_devices('GPU')` → real GPU
  matmul. Returns structured findings dict for assertion in
  CI / wrapper scripts. Cost: ~30 s warm / ~3 min first cold start
  (image build). Run `modal run tools/modal_train.py::gpu_check`
  before any full training run when the stack changes.
- **Belt-and-braces `LD_LIBRARY_PATH`** in the image env, listing all
  11 `nvidia/*/lib` paths. TF 2.18+ auto-discovers these at import
  time, but the explicit env helps any sub-process or native lib
  lookup that doesn't go through Python's site-packages logic.

#### Verified next
- New image deployed under `quant-sentinel-train`. Sunday 03:00 UTC
  cron will use the GPU build automatically — no further action.
- 5-epoch smoke training run kicked off as final end-to-end gate.

### 2026-04-27 (afternoon) — TwelveData hardening + lot-sizing design

#### Fixed
- **Env-name drift in observability layer** — `api/routers/system.py`
  recommendations + system/info checked `TWELVEDATA_KEY` and
  `FINNHUB_KEY`, but `.env` (and `src/core/config.py`) actually use
  `TWELVE_DATA_API_KEY` and `FINNHUB_API_KEY`. Settings → Recommendations
  was showing a permanent "TwelveData API key missing" warning even
  though the provider was initialized correctly. Same drift hit the
  startup `[ENV]` report in `api/main.py` for the Turso keys
  (`TURSO_AUTH_TOKEN`/`TURSO_DATABASE_URL` → `TURSO_TOKEN`/`TURSO_URL`).
  Verified: post-restart, recommendations endpoint returns 0 items.

#### Removed
- Dead `get_fx_rate` in `src/trading/finance.py` — sole yfinance call
  on the live-trading-adjacent path. Grep confirmed zero callers
  in repo. Live trading path is now 100 % TwelveData (yfinance lives
  only in offline training + legacy backtest fallback).

#### Added
- **Credit-budget alarm** in `RateLimiter` (`src/api_optimizer.py`).
  Once-per-cooldown WARN when last-min usage crosses
  `alarm_threshold` (default 45 / safe-limit 52 / hard-limit 55).
  Alarm fans out to `logger.warning` + Logfire `rate_limiter.high_usage`
  event + Sentry breadcrumb. Tunable via env vars
  `TWELVEDATA_ALARM_THRESHOLD` and `TWELVEDATA_ALARM_COOLDOWN_SEC`.
  `get_stats()` now exposes `alarm_threshold`, `alarm_cooldown_sec`,
  and `last_alarm_ts` so the Settings widget can show the threshold
  marker and the most recent alarm age.
- **Settings `RateLimitBlock` refactor** — bar now visualizes
  rolling-minute *usage* (0 → 55) with green / gold / red zones,
  plus marker lines at the alarm threshold (gold) and skip-cycle
  guard (red). Three-color legend + new "Last alarm" stat.
- **`twelvedata_plan_policy.md` memory** — declares the project rule
  that all live data goes through TwelveData (paid plan, 55 / min
  hard cap), documents env-var name (`TWELVE_DATA_API_KEY`), and
  notes the rate budget envelope for new live fetches.

#### Investigated
- **SHORT trade #200** (2026-04-27 01:08 UTC, +14.86 PLN, lot 0.01) —
  factors dict had no `short_in_bull_regime` key, confirming
  `macro_regime` was not "zielony" at trade time. B7 logic verified
  working on the first live SHORT post-flip. Side-finding:
  `macro_regime` is computed live but not persisted — no
  `macro_snapshots` table — so historical audits of this kind
  rely on inferring from `factors` presence.

#### Documented
- **`docs/strategy/2026-04-27_lot_sizing_rebuild_design.md`** —
  3-option design doc (constant 0.5 % / model-driven R-mult /
  ¼-Kelly) with explicit decision gate (≥ 30 post-config trades + 7d
  PF within ±20 % of backtest 1.21 + B7 verified). Recommendation:
  **Option A** once gate clears, no implementation before
  2026-05-04.

### 2026-04-27 — Logfire / Sentry / Modal wired up

End-to-end activation of the three external services that the v4 push
left as soft-stub. All three now actively shipping data:

- **Logfire**: project `antczak-j/quant-sentinel` created at
  `https://logfire-eu.pydantic.dev/antczak-j/quant-sentinel`, EU region,
  credentials in `.logfire/logfire_credentials.json` (gitignored). API
  startup picks them up automatically. `POST /api/system/test-trace`
  returned `{ok: true}` and the span landed in the dashboard.
- **Sentry**: DSN in `.env` (gitignored), env report confirms
  `SENTRY_DSN: OK` at startup. `POST /api/system/test-error` raised
  the intentional ZeroDivisionError and Sentry captured it (500 in
  the API log; event in Issues).
- **Modal Labs**: token at `~/.modal.toml`, workspace `antczakj`. App
  deployed at `https://modal.com/apps/antczakj/main/deployed/quant-sentinel-train`.
  First deploy with the full ML stack (TF + Torch + transformers +
  sentence-transformers + treelite ≈ 6 GB) hit the free-tier image-build
  shutdown; trimmed `tools/modal_train.py` to what `train_all.py`
  actually imports (numpy / pandas / sklearn / xgboost / TF / scipy /
  tqdm / pydantic ≈ 2-3 GB) and the second deploy succeeded in 76 s.

#### Fixed
- `_safe_version` in `api/routers/system.py` falls back to `.VERSION`
  attr — `sentry_sdk` exposes `VERSION` (uppercase), not
  `__version__`, so /api/system/info was returning null for it.

#### Added later in the same day (after the auth flow)

After the three integrations were live, an extension batch added:

- **Cmd+K "External" group** — three palette actions (Open Logfire
  dashboard / Open Sentry Issues / Open Modal app), each just a
  `window.open()` with the right URL. Entries also bump the Recent
  ring so they show up at the top of the palette after first use.
- **Settings ExternalServicesBlock** — three sub-cards with status
  pills (`✓ ACTIVE` green when configured, else muted) and "Open
  dashboard ↗" button per service. Status comes from a new
  `/api/system/info.integrations` field that probes file presence
  beyond just env vars (Logfire credentials file, ~/.modal.toml).
- **`scripts/start.ps1`** — PowerShell wrapper for everyday DX:
  `api`, `dev`, `both`, `stop`, `status`, `restart` subcommands.
  Idempotent (checks ports first, won't double-spawn). Auto-runs
  `npm install` if frontend/node_modules is missing.
- **Logfire structured event in resolver loop** — every
  `_auto_resolve_trades` cycle ends with
  `_logfire.info("resolver.cycle.done", open_count=N,
  trades_resolved=K, spot_price=X)` so the resolver path is as
  searchable in the Logfire dashboard as the scanner side. An
  `resolver.cycle.failed` exception event covers the error path.
- **`GET /api/scanner/peek`** — read-only ad-hoc indicator
  snapshot. Computes ATR(14), RSI(14), EMA-20 distance, 14-bar
  high/low, 20-bar volatility on the latest 100 bars of any TF.
  No SMC scoring, no ML inference, no DB writes — answers "why no
  trade today?" without dropping into a shell. Settings page
  ScannerPeekBlock card with TF picker (5m/15m/30m/1h/4h),
  bias pill (bullish/bearish/neutral from EMA distance + RSI),
  and 8-tile metric grid. 30 s polling.

#### Modal pipeline — ongoing issues
- TF inside the T4 container still falls back to CPU despite
  `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` base + `tensorflow
  [and-cuda]`. XGBoost CUDA does work (`device='cuda'` confirmed).
  Cost overhead at weekly cadence: ~$0.50/mc wasted on T4 that's
  underused by LSTM. Tracked for next session.
- First end-to-end Modal run produced model files identical SHA1
  to local pre-train versions because the bundled `/repo/models`
  was overwriting freshly-trained weights post-run. Fixed in
  `ce63402` by excluding `models` from the image bundle.
- Local network glitch (100% packet loss to `api.modal.com` after
  laptop sleep) blocked subsequent retries — neither bug nor
  Modal-side, just ISP/router. Weekly cron will retry on its own.

### 2026-04-26 → 2026-04-27 — v4 frontend redesign + observability + ML perf push

A two-day session producing 18 commits. Frontend redesigned end-to-end,
backend gained 10 new endpoints + observability stack (Logfire + Sentry),
defensive `dynamic_params` schema closes the bug class behind `95569f7`,
Treelite ships a 12× speedup on the live-scanner XGB inference path.
Production scanner / trade resolution paths untouched throughout — every
new feature defaults OFF or is opt-in.

#### Added — Frontend (v4 redesign)
- Cursor-reactive WebGL **mesh-gradient background** via Paper Shaders
  (`MeshBackground`), lazy-loaded, disabled on `/chart` to free GPU for
  lightweight-charts. Grain noise overlay. (`2236dc5`)
- **Cmd+K command palette** (`cmdk`) — pages, symbols, recent trades,
  scanner pause/resume, grid preview/apply, grid rollback, refresh,
  reduced-motion toggle. (`2236dc5`, `9b6d9cd`, `6c292ac`)
- **Bento Dashboard** — 12-col grid with Motion `layoutId` expand-to-modal
  cards. Balance / WinRate / Recent P&L / Open / Macro / Recent signals
  / Scanner all expand to detail views. (`2236dc5`, `71a35a5`)
- **NumberFlow rolling digits** + `FlashOnChange` bull/bear pulse on
  every live numeric. (`2236dc5`, `71a35a5`)
- **AnimatedBeam** voter→ensemble→signal flow on Models page; intensity
  scales with `voter_weight × accuracy`. (`2236dc5`, `71a35a5`)
- **VoterCard expandable** with 72-h forward-move accuracy and per-voter
  retrain commands. (`9b6d9cd`)
- **Equity curve** in `BalanceDetail` (with trades-derived fallback when
  cache empty), USD/JPY 1h × 200-bar chart in MacroDetail, open-positions
  detail with 5 s polling. (`71a35a5`, `63e5bab`)
- Mini-sparklines under WR + Recent P&L bento. Magnetic buttons.
  ScrambleText brand reveal. Aurora bg. WebAudio sound feedback. (`2236dc5`)
- `?` keyboard shortcuts overlay. (`faee71f`)
- Settings widgets: SystemInfo (versions / models / GPU / disk / env /
  git short SHA), RateLimit (credit bucket bar), DbStats (table counts +
  sentinel.db file size). (`faee71f`, `8ffb7fc`, `d5c732f`)
- Cmd+K recent-actions history (last 5 in localStorage). (`30c9fbb`)
- HealthDeepPopover replaces the static live/down pill — click for
  per-subsystem status (DB / models / GPU / scanner / trades).
  (`379fc99`)
- React `ErrorBoundary` around routes — render exceptions show a
  recoverable fallback instead of a blank screen. (this release)

#### Added — Backend endpoints
- `POST /api/scanner/{pause,resume}` + `GET /api/scanner/status` — surface
  the file-flag mechanism. (`71a35a5`)
- `GET /api/models/ensemble-weights` reads voter weights from
  `dynamic_params`. (`71a35a5`)
- `GET /api/portfolio/history` reconstructs from `trades` when cache empty.
  (`71a35a5`)
- `GET /api/params/{usage,drifts}` — live writer/reader counters + drift
  detector for `dynamic_params`. (`e0ccc66`)
- `GET /api/grid/{list,preview,apply,backups,rollback}` — surfaces
  `apply_grid_winner.py` over HTTP, `confirm:true` required for writes,
  path-traversal-safe rollback. (`9b6d9cd`)
- `GET /api/system/{info,db-stats,rate-limit,health/deep}` + `POST
  /api/system/{test-trace,test-error}` for observability smoke tests
  and Settings widgets. (`faee71f`, `8ffb7fc`, `d5c732f`, `30c9fbb`)

#### Added — Observability + defense
- **Logfire** OTEL platform (auto FastAPI + httpx instrumentation, custom
  scanner spans). Soft-disabled without `LOGFIRE_TOKEN`. (`67ecd77`)
- **Sentry** — error capture + slow-tx + cron heartbeat
  (`monitor_slug=bg-scanner`). Soft-disabled without `SENTRY_DSN`.
  (`9b6d9cd`, `6c292ac`)
- **Slow-request middleware** — logs WARN above `SLOW_REQUEST_MS`
  (default 500 ms). (`8ffb7fc`)
- **`dynamic_params` Pydantic-style schema** with auto-mirror
  `target_rr → tp_to_sl_ratio` (closes bug class `95569f7`), 30-min drift
  watchdog, schema-aware `set_param` / `get_param`. (`e0ccc66`, `faee71f`)
- Startup env-vars OK/missing report in `logs/api.log`. (`6c292ac`)

#### Added — ML / performance
- **Treelite-compiled XGB voter** (`tools/compile_xgb_treelite.py`) — ~12×
  speedup on N=1 single-sample inference (the actual scanner case).
  Parity max abs diff 5.96e-08 vs native. Load priority: Treelite →
  ONNX/DirectML → sklearn. (`d972d3f`)
- **DuckDB warehouse reader** (opt-in `QUANT_USE_DUCKDB=1`). Empirical
  bench: pandas wins 2.5× on single files, DuckDB wins 4× on multi-file
  SQL aggregations. 8/8 parity tests. (`e9488c8`)
- **Polars groundwork** — 16/16 features pass parity (≤3.6e-12 EWM, ≤3.3e-16
  elsewhere). `compute_features` itself stays pandas. (`6c292ac`, `faee71f`)
- **Optuna optimizer** (`scripts/run_optuna_optimization.py`) — TPE +
  median pruner, SQLite study storage, `--mock` evaluator. (`6c292ac`)
- **Modal Labs skeleton** for off-loading `train_all.py`. (`6c292ac`)

#### Added — Build
- Migrated to **`pyproject.toml` + `uv.lock`** (199 packages); back-compat
  `pip install -r requirements.txt` still works. `requires-python ≥ 3.12`.
  (`58566f8`)

#### Fixed
- Hero price + KPI digits invisible under `text-display-gradient` /
  `text-gold-gradient` (cascading `-webkit-text-fill-color: transparent`
  bled into NumberFlow). Switched numeric values to solid colors.
  (`5029fdf`)
- `TracedConnectionProxy` breaks `Connection.backup()` — disabled
  Logfire's sqlite3 instrumentation. (`67ecd77`)
- uv `prerelease=allow` (global) picked dev wheels for unrelated packages;
  switched to `if-necessary`. (`e9488c8`)

#### Tests
40 unit tests across three suites:
- `tests/test_dynamic_params_schema.py` — 19 (mirror, drift, edge cases).
- `tests/test_grid_endpoints.py` — 13 (TestClient, path traversal,
  confirm-required, 404 handling).
- `tests/test_warehouse_duckdb_parity.py` — 8 (pandas vs DuckDB parity).

#### Tooling
- `tools/bench_warehouse_reader.py`, `tools/compile_xgb_treelite.py`,
  `tools/polars_features_parity.py`, `tools/modal_train.py`,
  `scripts/run_optuna_optimization.py`.

---

### 2026-04-13 — Autonomous overnight retrain session

**Net production change**: LSTM voter resurrected. Other voters unchanged.

#### Added
- `tune_lstm.py` — Optuna sweep for LSTM with 14-dim search space including
  target redesign axis (`target_type`, `target_horizon`, `target_atr_mult`).
  Two-gate winner selection: `balanced_acc >= 0.52 AND live_stdev >= 0.03`.
- `retrain_deeptrans_loop.py` — strict-gated retrain loop for the deep
  transformer voter (3-class softmax, balanced_accuracy + live_stdev gates).
- Backup safety net: `models/_backup_<TS>/` dir + git tag
  `pre-autonomous-overnight-<TS>` snapshotting all artefacts + DB params
  before any production-touching change.

#### Changed
- `models/lstm.{keras,onnx,scaler.pkl}` **promoted from sweep winner**
  (trial #38: balanced_acc 0.547, live_stdev 0.0336 → 0.4593 post-retrain
  on train+val merge). `ensemble_weight_lstm` restored 0.0 → 0.15
  (conservative; previous self-learned 0.25 was on the flat-output era model).
- `run_production_backtest.py::_reset_backtest_db` — now truncates
  `trades / scanner_signals / ml_predictions` tables instead of unlinking
  the SQLite file. The unlink path raised `WinError 32 'used by another
  process'` while the module-level `src.core.database._conn` held the file
  open, AND closing that conn broke any `NewsDB` instances that had
  cached `self.conn`. Truncate is locally race-free.

#### Tried but not promoted (see `logs/autonomous_morning_report.md`)
- DQN sweep (8 of 60 trials, early-stopped). Trial 8 won val at +14.99%
  but `--apply-winner`'s held-out test reproduced only +0.06%; eval_compare
  vs production confirmed mode collapse (1 trade vs prod's 547).
  Production DQN retained (live attribution showed it as 82%-accuracy
  voter — still the best of the basket).
- DeepTrans retrain (4 iterations). All flat on live (stdev 0.005-0.011),
  best val_bal 0.391 < 0.42 floor. Voter stays disabled
  (`QUANT_ENABLE_TRANSFORMER` unset).

#### Known limitations (acknowledged, not fixed this session)
- `ml_predictions.trade_id` remains historically NULL on most rows. The
  scanner.py:921 UPDATE that links predictions to trades runs inside a
  silent `try/except: pass` and has been failing silently long before
  this session. Worked around by `/api/models/voter-attribution`'s
  timestamp-join. Fix would touch hot live code path — deferred.

### Added — Backtest infrastructure (P0-P8)
- **Production backtest harness** (`run_production_backtest.py`): walk-forward
  through historical data using the REAL scanner pipeline (SMC + ML ensemble +
  risk manager). 3-layer isolation from production DB (`data/backtest.db`,
  env var enforcement, paranoid runtime guards).
- **Historical data provider** (`src/backtest/historical_provider.py`): yfinance
  replay with proper time-slicing, disk cache (6h TTL), SMC cache invalidation
  on each tick.
- **Execution realism** (P6): commission, vol-scaled slippage, overnight swap
  cost, gap detection with worse-fill penalty.
- **Position management**: next-bar-open entry (no look-ahead), trailing stops
  (1R→BE, 1.5R→lock, 2R→trail), optional partial close at 1R (`--partial-close`),
  BREAKEVEN status for trail-to-entry exits.
- **Advanced analytics** (`src/backtest/analytics.py`): Sharpe/Sortino/Calmar,
  expectancy, rolling WR/PF, drawdown recovery time, time-of-day/DOW heatmap,
  P&L skewness/kurtosis.
- **Statistical methodology**: walk-forward windows (`--walk-forward N`),
  Monte Carlo bootstrap (`--monte-carlo N`), buy-and-hold benchmark with
  `alpha_vs_bh_pct`.
- **Tooling**: `--strict` for production-parity thresholds, `--compare`
  side-by-side diff, `--seed` for determinism, `--export-csv`, `--plot-equity`,
  `--resume` checkpoint recovery, `--analytics` full report.
- **Parameter sweep** (`run_backtest_grid.py`): systematic grid over
  min_confidence × sl_atr_mult × target_rr, ranked by Sharpe.
- **Frontend dashboard**: `BacktestResults` component on ModelsPage reads
  `/api/backtest/runs` + `/api/backtest/latest` + `/api/backtest/chart` +
  `/api/backtest/run?name=X` endpoints. Shows metrics card, equity curve PNG,
  Monte Carlo p5/p50/p95 distribution, rejection histogram, compare dialog.
- **Documentation**: `docs/BACKTEST.md` full CLI + metrics interpretation reference.
- **Tests**: 38 new tests (isolation, historical provider, e2e analytics).

### Added — RL training overhaul
- **Prioritized Experience Replay** (SumTree) with bootstrap stratification.
- **Multi-asset training** with `vol_normalize=True` fixing critical
  `balance += pnl × entry_price` bug (forex was invisible, BTC dominated).
- **Validation early stopping** (`VAL_PATIENCE=30`) + best-weight restoration.
- **Noise augmentation** (NOISE_STD=0.001) + checkpoint resume with data hash.
- **Training registry** (`src/ml/training_registry.py`): append-only JSONL
  log with git commit, hyperparams, per-symbol metrics.
- **Eval tooling**: `eval_rl.py` with model comparison, `regenerate_rl_onnx.py`
  standalone helper.
- **New model**: retrained 4-asset basket (GC/EURUSD/ES/CL) with vol_normalize
  → **+14pp OOS improvement** over pre-session gold baseline.

### Added — Observability (Phase 1)
- Scanner health metrics: `scan_duration` histogram, `scan_errors_total`,
  `scan_last_ts`, `data_fetch_failures`, `signals_long/short/wait`.
- Ensemble instrumentation: `ensemble_confidence` histogram + signal counters.
- `/api/health/scanner` endpoint with `healthy/stale/degraded/no_data` status.
- `/api/health/models` endpoint with staleness detection (14-day threshold).
- `/api/training/history` endpoint + `TrainingHistory` frontend widget.
- Database indexes: `idx_ml_pred_timestamp` (COVERING, 4.7k-row table),
  `idx_ml_pred_trade_id`, `idx_rejected_filter`.
- `verify_install.py` post-deploy smoke check (8 automated checks).

### Added — Defense (Phase 2)
- **Event guard**: `@requires_clear_calendar` decorator blocks trades 15 min
  before high-impact USD events (NFP/CPI/Fed).
- **Volatility targeting**: position size scales inversely with ATR
  (baseline/current ratio, clamped [0.4, 1.8]).
- **Volatility-aware slippage**: spread scales with current ATR × session.

### Added — Iteration tools (Phase 3)
- Training registry JSONL (`models/training_history.jsonl`).
- Backtest harness with pluggable strategies (SMA/RSI/ensemble).
- Per-model track record (`model_*_correct/incorrect` counters).
- Ensemble confidence tracking in metrics.

### Added — Code quality (Phase 4)
- Type hints pass on config.py, compute.py, new files.
- ESLint 8 → 9 migration with flat config (`eslint.config.js`).
- Tests: `test_rl_agent.py` (17), `test_event_guard.py` (8),
  `test_backtest_isolation.py` (16), `test_historical_provider.py` (10),
  `test_backtest_e2e.py` (13), `test_backtest_harness.py` (9).

### Changed
- **Scanner cadence 15min → 5min** (4× more trade opportunities, credit
  budget 1.6/min avg of 55/min limit).
- **`@vitejs/plugin-react` 4 → 6**, **`lucide-react` 0.383 → 1.8**,
  **`eslint` 8 → 9**, **`TypeScript` 5.3 → 5.9**, **`tailwindcss` 3 → 4**
  (flat config, `@theme` in CSS, Lightning CSS autoprefix).
- **DQN ensemble weight** 0.20 → 0.12 (conservative default, let
  self-learning adjust based on live track record).
- **Event guard integration** centralized via decorator.

### Fixed
- **Critical**: backtest trades were never resolved — `db.log_trade()` used
  wall-clock `datetime.now()` instead of simulated time.
- **Critical**: SMC cache (60s TTL) not invalidated between backtest ticks,
  making all cycles return identical analysis.
- **Critical**: `TradingEnv.balance += pnl * entry_price` broke multi-asset
  training (BTC at $60k dominated forex at $1.05). Fixed via `vol_normalize`.
- **Critical**: in production, `QUANT_BACKTEST_RELAX` shell-env leak could
  activate relaxed filters. Fixed via double-gate (`MODE + RELAX` both
  required) + production entry points explicitly clearing flags.
- `self_learning.py:113` undefined `stats` (should be `tw_stats`).
- `self_learning.py` session comparison: used capitalized strings against
  DB's lowercase `db.get_session()` output. Now uses same helper.
- `add_wavelet_features`: "buffer source array is read-only" via
  `df['close'].to_numpy(copy=True)`.
- `UnicodeEncodeError` in `DQNAgent.load()` on Windows cp1252 console.
- `calculate_position(td_api_key)` unused parameter marked deprecated,
  defaulted to empty string.
- Implicit Optional in `compute.py` ONNX conversion helpers.
- `macro_data.Myfxbook` login spam downgraded to debug in backtest mode.
- `vite-plugin-pwa` peer-dep workaround via `package.json overrides`
  (removed `.npmrc legacy-peer-deps` hack).

### Removed
- `frontend/.npmrc` (replaced by `package.json overrides`).
- `frontend/postcss.config.js`, `frontend/tailwind.config.js`
  (Tailwind 4 uses CSS `@theme`).
- `frontend/.eslintrc.json`, `frontend/.eslintignore` (ESLint 9 flat config).
- `autoprefixer` dependency (Lightning CSS built-in).

### Security
- Production hardening: `api/main.py` and `src/main.py` explicitly clear
  `QUANT_BACKTEST_MODE` + `QUANT_BACKTEST_RELAX` env vars at startup with
  warning if present.
- Backtest isolation: `BacktestIsolationError` raised if `DATABASE_URL`
  resolves to `data/sentinel.db` at enforce time.

---

## Pre-changelog history

See commits before 2026-04-11 in git log. Major milestones:
- React 18 → 19 upgrade (commit 6f48a30)
- WebSocket → Server-Sent Events migration (commit e409940)
- Flask → FastAPI migration (commit 0d5b910)
- Dark/light theme toggle
- PWA + offline support
- 3-phase frontend roadmap complete (Layout, Mobile, Model Health)
