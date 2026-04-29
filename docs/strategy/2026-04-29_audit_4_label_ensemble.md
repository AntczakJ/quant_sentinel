# Label / Target / Ensemble Audit — 2026-04-29

## TL;DR
The new triple-barrier label set in `tools/build_triple_barrier_labels.py` is correct and business-aligned, but it is **disconnected from the v1 training pipeline**: every v1 voter (LSTM, XGB, Attention, DPformer, DeepTrans) still trains against the legacy binary `compute_target` (`>0.5 ATR move in 5 bars`) — that target conflates winners with mean-reverters and is exactly the tautological label flagged in `label_baseline_2026-04-26.md`. Worse, the production ensemble math is currently **broken in three places that compound**: (1) `update_ensemble_weights` exists but is never called from the live resolver, so live weights only move when humans/`voter_watchdog.py` mutate them — `smc=0.05` (muted!) in `dynamic_params` right now; (2) `model_calibration.py` Platt scaling has fitted negative `A` for all three voters (LSTM/XGB/DQN), which mathematically **inverts** the raw prediction — strong "buy" raw → strong "sell" calibrated; (3) "walk-forward" via `scripts/run_walk_forward.py` does not retrain models (`train_runner=None`) and the docstring even admits "each window uses CURRENT live models" — these are not walk-forward windows, they are static-strategy backtests at different times. **Pre-training go: NO.** Five blocking issues need fixes before retraining.

## 1. Target audit (legacy + new)

### Legacy `compute_target` (still in production)
**File:** `src/analysis/compute.py:907-917`
**Definition:** Binary up-move detector — 1 if `(future_max - close) / atr > 0.5` AND not `(close - future_min) / atr > 0.5`, lookahead = 5 bars.

**Problems:**
- It's **direction-asymmetric** (favors LONG only) but is fed to BOTH long and short voting paths via the ensemble's "value > 0.5 = LONG, < 0.5 = SHORT" interpretation.
- It conflates a 0.5 ATR upward wiggle with "would have hit my real TP/SL" — these have ~26% empirical correlation per `label_baseline_2026-04-26.md`.
- The condition `up_move & ~down_move` is **broken for chop**: in any volatile bar that goes both up and down 0.5 ATR within 5 bars, label = 0 (LOSS-like), even though we never tried to enter. The training data is biased toward calm bars only.

**Who still uses it (production, hot path):**
- `src/ml/ml_models.py:59` (XGB) — line 59 + 164 (LSTM)
- `src/ml/attention_model.py:78` (Attention voter)
- `src/ml/decompose_model.py:143` (DPformer; weight=0 so dead, but still trained)
- `retrain_lstm_loop.py:122`, `retrain_attention_loop.py:81`, `retrain_dpformer_loop.py:106`
- `src/analysis/backtest.py:145, 196` (still used by analytics)
- `tests/test_compute.py:42`

**Note on retrain_attention/retrain_lstm loops:** these scripts are "loops" that retrain on a schedule and overwrite production weights. They **do not** use any newer label module. Triple-barrier labels are NOT yet plumbed into any production training script.

### New triple-barrier (`tools/build_triple_barrier_labels.py`)
**Verified correct.** Specifically:
- Same-bar TP+SL ambiguity → conservatively resolved to LOSS (line 138-143). Matches "worst-case fill" assumption used in `walk_forward_v2.py:120-122`. Good.
- Wilder ATR formula in `_wilder_atr` (lines 59-75) matches `pandas_ta.atr` (Wilder smoothing) — parity with `compute_features` ATR confirmed.
- LONG/SHORT computed in **one pass** (single `_walk_forward_kernel`) so no duplication risk.
- Labels: WIN=1, LOSS=0, TIMEOUT=2 — but `r_realized` for TIMEOUT is real-valued in units of `sl_atr*ATR` (line 181-186), so the parquet preserves R-multiple info even on timeouts. This is good — enables R-magnitude regression head later.
- Output schema (`long_label`, `long_r`, `long_exit_offset`, `short_label`, …) is per-direction → directly enables per-direction model training.

**3 minor concerns:**
- The numba kernel iterates `for t in range(n - max_holding)` — last `max_holding` rows have label=-1 and are silently dropped by `_print_summary` (line 242). Fine, but downstream training scripts must filter `label >= 0` — currently nothing in `train_v2.py` does this filter for the new file (it uses `r_multiple_labels` from `src/learning/labels/r_multiple.py`, not this parquet).
- TIMEOUT R is computed as `(close[t+max_holding] - close[t]) / (sl_atr * atr[t])` — but `atr[t]` could be tiny on warmup bars (Wilder needs ~14 bars), creating extreme R values. Recommend `atr[t]` warmup mask before label use.
- TP/SL ratios are baked into the file path (`tp2_sl1_max60`). Models trained on `tp2_sl1` are not portable to a `tp1.5_sl1` regime. Document explicitly that retraining must happen on the same TP/SL config that prod uses.

### `src/learning/labels/{binary,triple_barrier,r_multiple}.py`
These three modules exist as **library functions** (not parquet builders). Used only by:
- `r_multiple.py` → `scripts/train_v2.py`, `scripts/train_short_per_regime.py`, `scripts/train_lstm_v2_arch.py`, `scripts/walk_forward_v2.py` (all v2 R-multiple per-direction work).
- `triple_barrier.py` → not called anywhere in production. Defined but orphaned.
- `binary.py` → not called anywhere — exists for parity tests.

**Implication:** the new tool `tools/build_triple_barrier_labels.py` and the library `src/learning/labels/triple_barrier.py` are **duplicate implementations** of the same algorithm with subtly different conventions (label encoding 1/0/2 vs 1/-1/0; same-bar tie-break: LOSS vs LOSS-conservative; horizon name `max_holding` vs `max_horizon_bars`). Pick one.

## 2. Ensemble combination math

### What the live scanner actually predicts against
Trace: `scanner.py:565` → `get_ensemble_prediction()` (`ensemble_models.py:845`) → reads each voter's `predict_*_direction()` → those load `models/lstm.keras|xgb.pkl|attention.keras|rl_agent.keras` etc. → those .keras/.pkl files were trained against `compute_target` (binary 0.5-ATR-in-5-bars).

So **the production scanner's signal is "is there a 0.5 ATR move in 5 bars" weighted-averaged across voters** — NOT "would my TP have hit before SL". This is the central tautology: training target ≠ trading objective.

The **only** voter trained against an R-multiple target is `v2_xgb` (loaded from `models/v2/xau_long_xgb_v2.json` + `xau_short_xgb_v2_per_regime.json` via `predict_v2_xgb_direction`, weight 0.10). It is also the only voter trained on `features_v2` (62 cross-asset features) instead of v1 `FEATURE_COLS` (34 features).

### Voter fusion mechanism
**Lines 1198-1227** — Weighted average:
```
final_score = Σ (pred_value × regime_weight) / Σ regime_weight
```
A voter is *muted* (skipped) if:
- `status` field is set (e.g. "unavailable", "disabled") — common path for DPformer (perma-muted) and DeepTrans (flag-gated).
- `weight < MIN_ACTIVE_WEIGHT = 0.10`. Currently triggers for: smc (0.05), dqn (0.05), lstm (0.05), deeptrans (0.05) — **only 3 voters live: attention 0.20, xgb 0.20, v2_xgb 0.10.**
- `LSTM_BULLISH_ONLY = True` flag mutes LSTM bearish predictions (lines 1196 + 1211). The flag is hardcoded.

### Signal gates (lines 1281-1369)
1. `available_models == 0` → CZEKAJ.
2. `confidence < 0.30` → CZEKAJ.
3. **DQN+SMC compound override** — both vote same direction → bypass agreement/conviction gates. **DEAD because both are muted.** Code reads `dqn_pred` from results dict but `compound_override` requires `dqn_active` (no `status`); since DQN weight is 0.05 < 0.10 and the loop sets `pred["status"] = "muted_low_weight"` BEFORE the override check, the override never fires.
4. **SMC standalone override** — same dead-code condition (SMC at 0.05 → muted → status set → override skipped).
5. `agreement_ratio < 0.45 AND available_models >= 3` → CZEKAJ ("CONFLICTED").
6. `high_conf_count < 1 AND available_models >= 3` → CZEKAJ ("LOW_CONVICTION").
7. `final_score > 0.58` → LONG; `< 0.42` → SHORT; else CZEKAJ.

**Critical observation:** With only 3 live voters (attention/xgb/v2_xgb), the override paths are dead — the only way to get a signal is the agreement_ratio + high_conf_count + score thresholds, which is the simple weighted vote. The "DQN-SMC compound" and "SMC standalone" code blocks are vestigial.

### Voter disagreement handling
There is **no veto mechanism**. If XGB says LONG (0.62) and v2_xgb says SHORT (0.38) and Attention is neutral (0.50), the weighted score might be ~0.50 → CZEKAJ via the agreement_ratio filter. But if XGB+Attention agree LONG and v2_xgb says SHORT, v2_xgb's 0.10 weight is too small to flip the result. So disagreement → either CZEKAJ (good) or "outvoted minority" (the disagreeing voter is silently overridden — **no audit trail at decision time**).

### Confidence formula inconsistency
- `attention`: `min(1.0, abs(p-0.5)*6)` (line 928)
- `xgb`: `min(1.0, abs(p-0.5)*4)` (line 1019)
- `v2_xgb`: `min(1.0, abs(p-0.5)*4)` (line 1039)
- `lstm`: `abs(p-0.5)*2` (line 993) — naive, no clamp, no stretch
- `deeptrans`: `abs(p-0.5)*2` (line 952)
- `dqn`: softmax of Q-values (line 614)
- `smc`: hardcoded 0.8 (line 913)

**This means the *6 / *4 / *2 multipliers are arbitrary per-voter "decisiveness boosts" with no calibration backing.** Two voters with identical predictive power but different output ranges get arbitrarily different ensemble weights via this confidence column.

## 3. Voter weight + calibration

### Live weights (read from production DB this audit)
```
ensemble_weight_attention   0.20
ensemble_weight_deeptrans   0.05  (muted < 0.10)
ensemble_weight_dpformer    0.00  (perma-muted)
ensemble_weight_dqn         0.05  (muted)
ensemble_weight_lstm        0.05  (muted)
ensemble_weight_smc         0.05  (muted)
ensemble_weight_v2_xgb      0.10
ensemble_weight_xgb         0.20
```
Defaults in `_load_dynamic_weights()` (line 640-656) are different (smc 0.25, lstm 0.15, etc.) — DB has been mutated by `voter_watchdog.py` and manual `tools/voter_weight.py defuse` operations. Track records: `model_smc_correct=2` and `model_dqn_incorrect=0` are the **only** track-record rows in DB → confirming `update_ensemble_weights` has effectively never been called for the other voters.

### Weight-update is wired but disconnected (CRITICAL)
**`update_ensemble_weights(correct_models, incorrect_models, learning_rate=0.02)`** (line 703) implements EMA-smoothed updates with reasonable bounds. **It is not called anywhere in `api/main.py` or `src/trading/`.**
```
$ grep -r "update_ensemble_weights" src/ api/   # only the definition + tests
```
The `_auto_resolve_trades` task in `api/main.py:945` resolves trades to WIN/LOSS but never feeds `update_ensemble_weights`. So the only path that moves weights is `voter_watchdog.py --auto-mute` (manual cron) and `tools/voter_weight.py` (manual CLI). The self-learning loop the function was designed for **has no caller**.

### Calibration (`models/calibration_params.pkl`)
Currently fitted:
```python
{'lstm': {'a': -0.1930902, 'b': -0.394512, 'fitted': True},
 'xgb':  {'a': -0.156206,  'b': -0.403573, 'fitted': True},
 'dqn':  {'a': -0.170820,  'b': -0.399190, 'fitted': True}}
```
The Platt mapping in `model_calibration.py:79-84` is `1 / (1 + exp(-(a*p + b)))`. With **a < 0 for ALL three voters**, a higher raw prediction `p` produces a *lower* calibrated probability. This is mathematically equivalent to saying "the live history says these three voters are *anti-signals*" — which matches the `lstm_anti_signal_finding.md` memory note for LSTM but is harder to justify for XGB (which is supposed to be the strongest non-SMC voter).

**Two possible explanations:**
1. The training data hitting `fit_from_history` (line 142) joins `ml_predictions` to `trades` on `DATE(timestamp)` and a 0.02-day window — that match might be wrong (trades fire AFTER scans, so a setup→trade lag of >30 min around midnight pulls the wrong day). If ~half the rows are mismatched, Platt sees noise and can fit any sign.
2. The voters genuinely became anti-signals in the recent window the calibrator saw. The fact all three got the same sign (negative `a`) and similar magnitudes (~-0.16 to -0.19) is suspicious — looks more like a systematic pull-toward-neutral than three independent anti-signals.

Either way, **the calibrator is currently degrading every signal**, and the `model_calibration.py:209` "uncalibrated penalty" path (shrink toward 0.5 by 0.8x) does NOT apply here because all three voters are marked `fitted: True`. v2_xgb, attention, deeptrans, smc — the ones that aren't calibrated — get the 0.8x shrink penalty that's also unjustified.

### Voter list vs CLAUDE.md
CLAUDE.md says "7-voter ensemble". Actual count in `_load_dynamic_weights`:
1. smc, 2. attention, 3. dpformer (always 0), 4. lstm, 5. xgb, 6. dqn, 7. deeptrans, 8. v2_xgb. With dpformer perma-muted and deeptrans flag-gated off, that's 6 active slots; with the current DB weights, only 3 are above the active threshold. **The 7-voter ensemble is currently 3 voters in steady state.**

## 4. Walk-forward correctness

### `scripts/run_walk_forward.py` (read-only walk-forward)
**This is not a walk-forward.** Per `walk_forward.py:160`: `train_runner=None` is the documented default, in which case "skip training (read-only walk-forward using current models)". `run_walk_forward.py` never passes `train_runner`. The walk-forward then does:
1. Generate windows `(train_start, train_end, test_start, test_end)` — train_start/train_end are computed but unused.
2. Call `_default_backtest_runner(test_start, test_end)` which spawns `run_production_backtest.py --start ... --end ... --warehouse`.
3. `run_production_backtest.py` instantiates the LIVE production models from disk for every window.

Result: the same set of model weights is evaluated on N different test windows. This is a **regime-stability test of the current model**, not a walk-forward validation. The window train periods are decorative.

**Concretely:** the 2-year walk-forward currently running uses the legacy-target binary v1 voters across all windows. Whatever it shows is information about model stability under regime drift, not about whether retraining recovers edge.

### `scripts/walk_forward_v2.py` (true OOS for v2 XGB)
This one IS a real OOS test:
- Splits 3-year warehouse parquet into `train_pct=0.85` / `test_pct=0.15` chronologically (line 196-198).
- Trains `train_xgb_simple` on train portion ONLY (no Optuna, no bells).
- Predicts on test portion; simulates trades; reports metrics.
- **Single split, not rolling** — so it's an OOS holdout, not a walk-forward in the literature sense. Vulnerable to "this 15% test window happened to be a bull market" overfitting at the macro level.

The convention fix at line 96-98 (SHORT entry = positive `short_r`) is correctly handled and matches the sign-flip in `r_multiple.py:82,108-109` (`sign = 1 if direction == "long" else -1`, fav_excursion uses `entry - low_j` for short).

**No leak detected** in walk_forward_v2 mechanics. The `--warehouse` parquet has fixed historical data and `compute_features_v2` looks only at past+present bars (rolling windows shift backward). The labels are NaN where the future is unavailable; those rows get dropped. Good.

### Scope leak danger to flag
`compute_features_v2` (not read in this audit but referenced) computes cross-asset features. If those features touch `data_sources.get_provider().get_*()` paths during training (live API), training would peek at present-day price for a historical bar. **Recommend audit:** grep `features_v2.py` for `get_provider`, `get_current_price`, `get_macro_quotes`, `datetime.now`. The 4 sim-time leaks fixed in `backtest_realtime_bugs_2026-04-29.md` were exactly this class.

### `scripts/run_optuna_optimization.py` and `train_v2.py`
`train_v2.py` uses `TimeSeriesSplit(n_splits=5)` from sklearn (line 138) — proper rolling CV with no shuffle. The Optuna objective trains on `train_idx`, evaluates on `val_idx`, returns mean MSE. Selection of `best_params` is on full mean-CV-MSE, then **the final model is fit on ALL data** (line 181) including the validation folds. That's standard but means the saved `xau_long_xgb_v2.json` has *seen* every row that the OOS metric was computed on. As long as nobody publishes the CV MSE as "live OOS performance", this is fine. `_train_summary.json` reports `best_cv_mse` which is honest for that purpose.

## 5. Class imbalance + thresholding

### Class distribution under triple-barrier (theoretical, RR=2:1)
Random walk → P(TP first) ≈ 33% (because the ±2σ bound is twice as far as ±1σ). Empirically `label_baseline_2026-04-26.md` claims 26% TP / 65% SL / 9% TIMEOUT on 5m XAU under those exact params.

### How current training handles it
- **XGB v1** (`ml_models.py:71-72`): `scale_pos_weight = n_neg / n_pos` — correctly compensates the binary skew. Standard, fine.
- **LSTM v1** (`ml_models.py:235`): `class_weight = {0: 1.0, 1: n_neg/n_pos}` — same compensation. Fine.
- **Attention v1** (`attention_model.py:147`): same idiom. Fine.
- **DeepTrans** (`transformer_model.py:228-231`): 3-class inverse-frequency weighting `inv_freq = total / (3 * counts)`. Fine.
- **XGB v2** (`train_v2.py:140-160`): regression problem (MSE), no class weights — `scale_pos_weight` is meaningless for regression. Optuna minimizes mean MSE which equally weights big-R-positive and big-R-negative samples, so the most extreme outliers (rare big winners and big losers) dominate. **Recommend Huber loss** instead of MSE for next retrain — penalizes outliers less.

### Threshold semantics
- v1 voters: **0.5 cutoff** for "LONG vs SHORT direction" coming out of binary classification. The ensemble's gates use 0.55/0.45 for direction and 0.42/0.58 for final_score. Reasonable.
- v2_xgb: **0.3R cutoff** for emitting a vote (`predict_v2_xgb_direction:491-496`) — anything between -0.3R and +0.3R returns 0.5 (neutral). Reasonable.
- For 3-class triple-barrier: there is no current threshold — no production voter takes 3-class output. The DeepTrans 3-class output is converted via `value = P(LONG) + 0.5*P(HOLD)` (line 27 of transformer_model.py docstring) which is a **decision-theoretic mistake**: it's claiming P(HOLD)=0.5 should map to ensemble-neutral 0.5, but P(HOLD) doesn't carry any directional information. A 3-class voter outputting [0.4 LONG, 0.5 HOLD, 0.1 SHORT] becomes 0.65 — looks LONG. But [0.1 LONG, 0.5 HOLD, 0.4 SHORT] becomes 0.35 — SHORT. So far OK. But [0, 1, 0] (perfect HOLD) becomes 0.5 (neutral) — that's correct. The bigger issue is that HOLD probability gets distributed equally between LONG and SHORT in the projection, which inflates voting confidence on uncertain windows. Better mapping: `value = P(LONG) / (P(LONG) + P(SHORT) + 1e-6)`, or just `value = P(LONG) - P(SHORT) + 0.5`.

### When triple-barrier becomes 3-class
Naive `argmax(P(WIN), P(LOSS), P(TIMEOUT))` would sample-weight against TIMEOUT (which is 9% of trainset). Recommend either:
- Drop TIMEOUT entirely from training (treat as "no entry" — model only trained on resolved trades). Risk: model learns SL-near setups score lower because hold-to-timeout is censored.
- Keep 3-class with `class_weight='balanced'`. Add post-hoc threshold tuning: instead of argmax, find the P(WIN) cutoff that maximizes Sharpe in OOS.

## 6. Voter correlation / diversity

I did not run live inference for this audit (the recommendation in your prompt). Recommended script for a future session:

```python
# tools/voter_correlation_audit.py — produce cross-voter correlation matrix
from src.ml.ensemble_models import (
    predict_lstm_direction, predict_xgb_direction,
    predict_v2_xgb_direction, predict_dqn_action,
)
from src.ml.attention_model import predict_attention
from src.analysis.compute import compute_features
import pandas as pd, numpy as np

# Load 60 days of 5m XAU from warehouse
df = pd.read_parquet("data/historical/XAU_USD/5min.parquet").tail(60*24*12)
windows = [df.iloc[i-200:i] for i in range(200, len(df), 12)]  # one sample/hour
out = []
for win in windows:
    row = {
        "lstm": predict_lstm_direction(win),
        "xgb":  predict_xgb_direction(win),
        "v2":   predict_v2_xgb_direction(win),
        "attn": predict_attention(win),
        # dqn: convert to scalar 0.2/0.5/0.8
    }
    out.append(row)
df_out = pd.DataFrame(out).dropna()
print("Pearson:")
print(df_out.corr())
print("\nSpearman:")
print(df_out.corr(method="spearman"))
```

**Predicted outcome based on training-target redundancy:** lstm, xgb, attention all train on `compute_target` over the same `FEATURE_COLS` window — *prior expectation: r > 0.7 across the trio*. The point of the ensemble is reduced if true. v2_xgb and dqn use different targets and feature sets (especially v2_xgb with 62 cross-asset features) — those should be the diversity carriers.

**Concrete prediction to verify:** if the correlation matrix shows `(lstm, xgb, attention)` cluster at r > 0.7 and `(v2_xgb, dqn)` at r < 0.3 with the cluster, the practical voter count is "2 plus a triplet of one" — much less diverse than the 7-vote count suggests.

## 7. Migration plan: binary → triple-barrier

### Pre-migration checklist (BLOCKING for retrain)
1. **Pick ONE triple-barrier impl.** Either keep `tools/build_triple_barrier_labels.py` (parquet-based, fast) and drop `src/learning/labels/triple_barrier.py`, or vice versa. Standardize label encoding (recommend 1=WIN/0=LOSS/2=TIMEOUT for parity with `build_triple_barrier_labels.py`).
2. **Add a trainable label adapter** — an `r_adapted_target(features, mode)` function that returns:
   - `mode='binary_legacy'`: existing `compute_target` (back-compat).
   - `mode='triple_barrier_class'`: 0/1/2 class labels.
   - `mode='r_multiple_long'`, `'r_multiple_short'`: continuous R-mag regression target.
   Wire ALL training scripts (`ml_models.py`, `attention_model.py`, `decompose_model.py`, `retrain_*_loop.py`) through this adapter so changes are surgical.
3. **Decide on the inference contract.** v1 ensemble expects each voter to return a scalar ∈ [0, 1] interpreted as P(LONG). For 3-class output, the projection `P(LONG) + 0.5*P(HOLD)` is broken (see §5). Standardize on `value = 0.5 + 0.5 * (P(WIN_long) - P(WIN_short))` if training BOTH directions in one model, or `value = P(WIN)` for a per-direction model run twice (long head + short head).

### Migration steps (in order)
1. **Don't rip out `compute_target`.** It's still wired in 9 scripts. Keep it as the deprecation target; add new code alongside.
2. Build per-direction triple-barrier head: `train_v3_ensemble.py` that wraps `r_multiple_labels(direction='long')` and `direction='short'` separately. Train one XGB and one LSTM per direction. (We already have `models/v2/xau_*_xgb_v2.json` from train_v2 — reuse pattern.)
3. **Recalibrate.** Wipe `models/calibration_params.pkl`, rerun `ModelCalibrator.fit_all()` ONLY after at least 50 new resolved trades have flowed through `_persist_prediction()` with the new target. Until then, the uncalibrated 0.8x shrink is the right behavior.
4. **Wire `update_ensemble_weights`.** Add a hook in `_auto_resolve_trades` (api/main.py:945) that, on every WIN/LOSS resolution, queries the matching `ml_predictions` row, computes which voters were correct, and calls `update_ensemble_weights(correct, incorrect)`. Without this, weights only move when humans intervene.
5. **Honest walk-forward.** Add `--retrain-per-window` flag to `scripts/run_walk_forward.py` that passes a `train_runner=lambda s,e: subprocess.run(['train_v3_ensemble.py', '--start', s, '--end', e])`. This is what walk-forward actually means.
6. **Per-direction at inference.** The current ensemble outputs ONE final_score that's interpreted as LONG vs SHORT bias. Per-direction models would output `(p_long_wins, p_short_wins)` separately. Decision: trade LONG iff `p_long_wins > 0.55 AND p_short_wins < 0.45`. Avoids the double-counting where a "P(LONG move) = 0.7" prediction also implies "P(SHORT move) = 0.3" — that conflation is what makes binary-target models unreliable on chop.
7. **Drop the `confidence × 6 / × 4 / × 2` arbitrary multipliers.** Replace with isotonic-regression calibration per voter: each voter outputs raw P(WIN); calibrator maps it to true probability; ensemble averages calibrated probabilities.

### Specific to triple-barrier R-multiple integration
- Triple-barrier file already has `long_r` and `short_r` columns (line 232+236 of `build_triple_barrier_labels.py`) — these are R-multiples ready to plug into the `r_multiple_labels` regression head.
- The `_lot_sizing_rebuild_design.md` memo wants R-multiple-predicting models for sizing; current `predict_v2_xgb_direction:484-485` already returns continuous R predictions. Wire those through to a sizing function (instead of converting to a 0-1 LONG bias and discarding magnitude) for the lot rebuild.

## Pre-training go/no-go

- [ ] **(BLOCK)** Decide single triple-barrier source-of-truth (parquet file or library function) — duplicate impls will drift.
- [ ] **(BLOCK)** Audit `compute_features_v2` for live-API leaks (datetime.now, get_provider, persistent_cache) — same bug class as the four 2026-04-29 sim-time leaks. v2_xgb is the cleanest voter we have; if its training pulled live data for historical bars, we're optimizing on a contaminated label set.
- [ ] **(BLOCK)** Wipe and rebuild `models/calibration_params.pkl` after retrain — current negative `A` values invert signals.
- [ ] **(BLOCK)** Add `update_ensemble_weights` call to `_auto_resolve_trades` so weights respond to outcomes. Without this, retraining doesn't change live behavior — voter weights are frozen at whatever the DB happens to have today (mostly 0.05 muted, 0.20 attn/xgb).
- [ ] **(BLOCK)** Replace the `* 6 / * 4 / * 2` confidence multipliers with a single calibrated-probability scheme. Otherwise the per-voter arbitrary weights distort the ensemble even with new labels.
- [ ] **(SHOULD)** Wire `tools/voter_correlation_audit.py` (sketch in §6) and run it on a 60-day held-out window. If lstm-xgb-attention triplet has r > 0.85, accept that the "ensemble" is one model in a trenchcoat and shrink to per-direction (xgb_long, xgb_short, v2_xgb_long, v2_xgb_short, smc) before retraining.
- [ ] **(SHOULD)** Switch `train_v2.py` (and any v3) regression head from MSE to Huber loss — limits outlier dominance. This is a 1-line change (`objective='reg:pseudohubererror'` for XGB).
- [ ] **(NICE)** Make `scripts/run_walk_forward.py` opt-in retrain via flag. Document loudly in the docstring that the no-flag default is **regime-stability test**, NOT walk-forward validation. Currently the docstring already half-admits this; the rename should be explicit (`run_regime_stability.py` is more honest).
- [ ] **(NICE)** Drop `src/ml/decompose_model.py` from training schedule entirely. dpformer weight=0 + suspected leak (CLAUDE.md notes 78% val_acc). It still trains every cycle; that compute is wasted.

**Verdict: NO-GO** until the 5 BLOCK items are addressed. The biggest single risk is the calibrator: even after we retrain on triple-barrier, the inverted Platt parameters will silently flip every voter's signal. Rebuild order: (1) drop calibration_params.pkl, (2) wire weight updates, (3) train v3 on triple-barrier labels, (4) re-audit correlation post-retrain.

## File path index (for the parent agent)
- `C:\quant_sentinel\src\analysis\compute.py` — legacy `compute_target` definition
- `C:\quant_sentinel\tools\build_triple_barrier_labels.py` — new TB parquet builder
- `C:\quant_sentinel\src\learning\labels\triple_barrier.py` — duplicate TB library
- `C:\quant_sentinel\src\learning\labels\r_multiple.py` — R-multiple labels (only path used by v2)
- `C:\quant_sentinel\src\ml\ensemble_models.py` — fusion math, weight loader, weight updater (orphan)
- `C:\quant_sentinel\src\ml\model_calibration.py` — Platt scaler with negative-A live params
- `C:\quant_sentinel\models\calibration_params.pkl` — currently inverting LSTM/XGB/DQN
- `C:\quant_sentinel\src\backtest\walk_forward.py` — implements walk-forward but defaults to no-retrain
- `C:\quant_sentinel\scripts\run_walk_forward.py` — never passes `train_runner` (regime-stability test, not WF)
- `C:\quant_sentinel\scripts\walk_forward_v2.py` — single OOS holdout for v2_xgb (real, narrow)
- `C:\quant_sentinel\scripts\train_v2.py` — proper TimeSeriesSplit, MSE loss
- `C:\quant_sentinel\api\main.py:945` `_auto_resolve_trades` — missing call to `update_ensemble_weights`
- `C:\quant_sentinel\data\sentinel.db` `dynamic_params` — live weights (3 active voters, 5 muted)
