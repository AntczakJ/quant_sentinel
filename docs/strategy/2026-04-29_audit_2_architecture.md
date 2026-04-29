# Architecture Audit — 2026-04-29

Read-only audit of every voter in the Quant Sentinel ensemble plus the
training pipeline that produces them. Goal: certify (or block) the
upcoming triple-barrier retrain.

## TL;DR
The ensemble has **two structurally healthy voters (XGBoost + DQN)**, **two
defensible-but-overparameterized voters (LSTM, Attention)**, **one
hardwired-off voter that still drains 100ms per scan (Decompose)**, **one
flag-gated voter that has never been promoted live (DeepTrans)**, and one
**pure rule-based voter (SMC)**. The biggest pre-train concerns are
(1) the **shared-feature problem** — XGB / LSTM / Attention / Decompose
all read the same 34-column feature vector with no diversity injection,
so "7 voters" is closer to "1 feature view × 4 model heads + RL + rules";
(2) **LSTM and Attention are 5–10× over capacity for the data** they see
in walk-forward folds (50–100k samples, ~100k–250k params); (3) the
**training pipeline still pulls 1h yfinance data, not the 5m parquet
warehouse** — so triple-barrier labels at 5m will not actually be trained
on if `train_all.py` is invoked unmodified. Two of those three are
go/no-go blockers.

**Recommendation:** Conditional GO — do not run `train_all.py` in its
current form; modify it to consume the 5m warehouse + triple-barrier
labels first, drop or fully strip Decompose, and shrink LSTM. Then
retrain.

---

## Per-voter scorecard

| Voter | Architecture | Params | Cap/Data | Regularization | Live weight (DB) | Verdict |
|---|---|---|---:|---|---:|---|
| **XGB (v1)** | 200 trees, depth 6, scale_pos_weight | ~80 K nodes | OK (gradient-boosted is robust) | reg_alpha 0.1, reg_lambda 1.0, min_child_weight 3, subsample 0.8, colsample 0.7 | 0.20 | **KEEP** |
| **XGB (v2 / per-direction)** | XGBRegressor, R-multiple targets, per-direction + per-regime | similar | OK | inherits xgboost defaults | 0.10 | **KEEP** (highest OOS Sharpe) |
| **LSTM** | 3 stacked LSTM (128→64→32) + 2 Dense | ~120 K | **TIGHT** for 50–100 K samples × 60-bar windows | dropout 0.3/0.25/0.2, EarlyStopping patience 15 | 0.05 (penalised, ex-0.25) | **REWORK** (shrink + retrain or drop) |
| **Attention (TFT-lite)** | 2× MultiHeadAttention (4h, key_dim 16) + 2 Dense | ~30 K | OK (right size for 50 K samples) | dropout 0.1/0.3/0.2, EarlyStopping patience 12 | 0.20 | **KEEP** |
| **Decompose (DPformer-lite)** | 3-branch (LSTM trend / Attn seasonal / Dense residual) | ~70 K | **OVER** + naïve SMA decomposition | dropout 0.2-0.3, EarlyStopping | 0.0 (HARD-DISABLED) | **DROP** (cosmetic, still emits NEUTRAL row) |
| **DeepTrans** | 4-block pre-LN transformer, 3-class head, 8-head attn, d_model 64 | ~250 K | **OVER** (5× capacity for ~50 K labelled windows) | dropout 0.15, EarlyStopping patience 8 | 0.05 (flag-gated, val_acc 0.41) | **REWORK or DROP** (val_acc < random for 3-class) |
| **DQN (Double-DQN, PER, n-step)** | 3 Dense (64-64-32) → 3 actions | ~7 K | very low cap (good) | Huber loss, soft target tau=0.005, IS-weighted PER | 0.05 (penalised, ex-0.25) | **KEEP** (only RL voter, distinct inductive bias) |
| **SMC** | rule-based (no params) | 0 | n/a | — | 0.05 (penalised) | **KEEP** (different inductive bias, 74% live acc per memory) |
| **v2_xgb_short_per_regime** | regime-conditional XGBRegressor sibling | ~50 K | OK | xgboost defaults | (loaded under v2_xgb) | **KEEP** |

> Live weights above come from `dynamic_params` snapshot taken at audit
> time (2026-04-29). LSTM/DQN/SMC are sitting at the floor (`_WEIGHT_MIN
> = 0.05`) because self-learning has been penalising them; the
> `MIN_ACTIVE_WEIGHT = 0.10` quarantine in `ensemble_models.py:1179`
> means **LSTM, DQN, and SMC are currently muted in the live fusion**.
> Only XGB (0.20) + Attention (0.20) + v2_xgb (0.10) actually vote. That
> is a 3-voter ensemble, not 7.

---

## Per-voter detail

### 1. XGBoost v1 (`src/ml/ml_models.py:49-131`)
**Architecture:** 200 trees, max_depth 6, lr 0.05, scale_pos_weight from
class imbalance.
**Param count:** ~80 K decision nodes (200 × 2^6 leaves max, sparse).
**Cap/data ratio:** Healthy. Tree models scale gracefully with n.
**Regularization stack:** L1 (reg_alpha 0.1), L2 (reg_lambda 1.0),
min_child_weight 3, row subsample 0.8, col subsample 0.7. Solid.
**Optimizer/LR/schedule:** XGBoost native — gradient boosting, no LR
schedule needed.
**Loss:** Binary logistic on `compute_target` (>0.5 ATR move in next 5
bars). Class weights via `scale_pos_weight=n_neg/n_pos` — addresses
~30% positive baseline correctly.
**Sequence/lookback:** Uses last bar's 34 features, no sequence (right
for tree models).
**Training budget:** 200 estimators, no explicit early stopping despite
having `eval_set`. Verbose=0 means we never see validation loss curves.
**Val split:** **Walk-forward 5-fold expanding window** (`ml_models.py:79-100`).
Correct for time series. Then refits on all data for final.
**Inductive bias:** Non-linear feature interactions, axis-aligned splits.
**Known weakness:** Cannot model temporal dependencies (tree splits are
state-free across bars). Compensated by the LSTM/Attention voters.

**Walk-forward accuracy from DB:** 0.575 (XGB last accuracy). MCC not
persisted — accuracy alone hides class imbalance distortion.

**Verdict:** **KEEP, retrain.** Treelite compile already ~12× faster on
single-sample inference. No architecture changes needed for triple-barrier
retrain — just point at the new labels.

### 2. XGBoost v2 / per-direction (`src/ml/ensemble_models.py:404-500`)
**Architecture:** Two XGBRegressors (long, short) + a per-regime short
variant. Predicts continuous R-multiples instead of binary.
**Why this is interesting:** This is the only voter that **predicts what
we actually trade** (R outcome, not next-bar direction). OOS PF 2.24 / WR
53.6% per the 2026-04-25 master plan. Live weight 0.10 is conservative —
makes sense until we see live data, but the live shadow run after the
warehouse-driven retrain will be the deciding signal.
**Inductive bias:** Same as XGB v1 but different label, different feature
set (`features_v2.py`, 62 features including cross-asset).
**Verdict:** **KEEP**, ensure the 5m retrain refreshes both v1 and v2.

### 3. LSTM (`src/ml/ml_models.py:150-274`)
**Architecture:** 3 stacked LSTMs (128 → 64 → 32) + Dense 32 + Dense 16 +
sigmoid. seq_len=60.
**Param count:** Roughly:
- LSTM(128, return_seq=True) over 34 features: 4·(34·128 + 128·128 + 128) = ~83 K
- LSTM(64): 4·(128·64 + 64·64 + 64) = ~49 K
- LSTM(32): 4·(64·32 + 32·32 + 32) = ~12 K
- Dense heads: ~1.5 K
**Total: ~145 K params.**
**Cap/data ratio:** With 2 years of 1h data (~12 K bars) and seq_len 60,
the model sees ~12 K windows but most are heavily overlapping (autocorrelated
labels). Effective independent samples ≈ 200–300. **145 K params on
~250 effective independent labels is ~600× over capacity.** Even at the
weakest interpretation (every 60-bar window counts, n=12 K, 60% positive
class), it is still 12 samples per parameter — below the standard heuristic
of ≥20.
**Regularization stack:** dropout 0.3/0.25/0.2, EarlyStopping patience 15
on val_loss, class_weight from imbalance. No L2/weight-decay. No
gradient clipping. No batch norm.
**Optimizer/LR/schedule:** Adam(lr=0.0005), no schedule. epochs=80,
batch_size from `get_tf_batch_size` (128 GPU / 32 CPU). Patience 15 means
early stop almost certainly fires before epoch 80.
**Loss:** binary_crossentropy on the same target as XGB.
**Sequence/lookback:** seq_len 60. On 1h data that's 60h ≈ 2.5 days.
On 5m data (post-warehouse) that's 5h. Both reasonable.
**Val split:** Walk-forward 5-fold + final 80/20 chronological split.
Correct.
**Inductive bias:** Sequential dependencies, gated memory. In theory
distinct from XGB; in practice with the same 34 features the model
"sees the same world" and converges toward similar shortcut features
(returns, volatility, RSI, MACD).
**Known weakness:** History speaks for itself —
`memory/lstm_anti_signal_finding.md`: previous sweep winner was 21%
directional accuracy, 9% on SHORT calls. The bullish-only mute
(`LSTM_BULLISH_ONLY = True` at `ensemble_models.py:1196`) is still in
the code; means even after retrain we are accepting only half the
voter's output until manually re-enabled. **Walk-forward acc 0.625 in
DB, last_accuracy 0.527 — gap suggests distribution drift.**

**Verdict:** **REWORK or drop.** Concrete options before retrain:
1. Shrink to 64→32 (≈40 K params), or single layer 64.
2. Add weight_decay 1e-4 / L2 1e-4.
3. Add ReduceLROnPlateau(patience=5, factor=0.5).
4. Remove the `LSTM_BULLISH_ONLY` hack OR make it data-driven (per-direction
   accuracy from `voter_attribution`).
If shrunk LSTM still trails Attention in walk-forward, drop it — Attention
is its strict superset (no recurrence forgetting + global pool).

### 4. Attention / TFT-lite (`src/ml/attention_model.py:21-58`)
**Architecture:** 2 stacked MultiHeadAttention blocks (heads 4/2, key_dim
16/8) with residual + LayerNorm, then last-step + global-avg merge,
then 64→32→1 sigmoid.
**Param count:** Each MHA(4 heads, key_dim 16) ≈ 4·(34·64 + 34·16) = ~10 K.
Two blocks ~ 20 K. Heads 6–8 K. **Total ~30 K params.**
**Cap/data ratio:** ~30 K params on 12 K windows ≈ 2.5 sample/param. Tight,
but transformer-style models are explicitly designed to handle this with
dropout and pre-LN.
**Regularization:** attention dropout 0.1, head dropout 0.3/0.2,
EarlyStopping patience 12.
**Optimizer/LR:** Adam(0.0005), epochs 80.
**Loss:** binary_crossentropy.
**Sequence/lookback:** seq_len 60 (same as LSTM, makes shapes comparable).
**Val split:** 3-fold walk-forward + final 80/20.
**Inductive bias:** Attends to ALL bars in the window simultaneously.
This IS structurally different from LSTM (no left-to-right gated
forgetting). It's the cleanest non-tree voter.
**Known weakness:** Attention dropout 0.1 is mild for a model this size
on noisy intraday data. Empirical output range 0.35–0.63 suggests it
rarely forms strong opinions. Confidence stretched ×6 in `ensemble_models.py:928`
to make it clear gates — that is a code smell, not a real fix.
**DB metrics:** `attention_walkforward_accuracy = 0.604`, last 0.495 —
overfit gap is real.

**Verdict:** **KEEP, retrain on warehouse 5m.** Drop the ×6 stretch and
just tune the model so its native conviction is meaningful.

### 5. Decompose / DPformer-lite (`src/ml/decompose_model.py:67-117`)
**Architecture:** 3-branch (LSTM trend / Attention seasonal / Dense
residual) over a naïve SMA-based decomposition (NOT real STL/LOESS).
**Param count:** ~70 K (LSTM 64→32, MHA 4 heads + Dense heads).
**Cap/data ratio:** Over.
**Status in production:**
- Live weight 0.0 in `dynamic_params`.
- Hard-coded NEUTRAL response in `ensemble_models.py:971-974` —
  `predict_decompose` is **never actually called from the live path**.
- `train_all.py:631` skips training (memory says "suspected data leak,
  weight=0").
- DB walk-forward acc 0.769 — suspicious outlier, very likely leak.
- Code path still exists everywhere (file, tests, frontend column).

**Why the leak suspicion is plausible:** `_decompose_features` uses
`np.convolve(mode='same')` on the entire series at once, then edge-fixes
with future values (`t[-(period//2):] = t[-(period//2)-1]`). That looks
backward-pointing, but `convolve(mode='same')` is symmetric and DOES
mix future values into the trend at every bar. Combined with the
shift(-lookahead) target, this is enough to leak future close into the
trend feature seen at training time. **High confidence the 0.769 acc is
an artifact.**

**Verdict:** **DROP** (file, test, frontend column, ensemble entry). It
has been "off" for 5 days but the audit trail in `ml_predictions` still
gets a column written to it. Removing also kills 100 ms per scan in
`get_ensemble_prediction` if anything ever flips it back on.

### 6. DeepTrans (`src/ml/transformer_model.py:1-403`)
**Architecture:** 4-block pre-LN transformer, 8 heads, d_model 64, ffn_dim
128, sinusoidal PE, GAP, 64-dim head, 3-class softmax (LONG/HOLD/SHORT).
**Param count:** Per block: 4 attn weight mats × (64·64) + 2 FFN (64·128 +
128·64) ≈ 33 K. 4 blocks → ~130 K. Plus input proj (34→64) + head: ~10 K.
**Total ~140 K, plus optimizer state.** [Original docstring claims it's
heavier than Attention; actual count is ~5× Attention.]
**Cap/data ratio:** With ~50 K labelled windows after the HOLD threshold
filter, ~3 samples/param. **Transformer-typical pretrained models train
on 10⁹+ tokens** — this is a tiny-data transformer with no pretraining.
**Regularization:** dropout 0.15 across attn + ffn + head, EarlyStopping
patience 8.
**Optimizer/LR:** Adam(3e-4), epochs default 40, batch 32. **No warmup,
no LR schedule.** Pre-LN tolerates this better than post-LN, but
deep transformers without warmup are still a known instability source.
**Loss:** sparse_categorical_crossentropy, class-weighted (HOLD usually
dominates).
**Sequence/lookback:** seq_len 60.
**Val split:** time-ordered 80/20 (no walk-forward — different from
every other voter, inconsistency).
**Inductive bias:** Same as Attention but deeper. **Marginal differentiation
from Attention.**
**Known weakness:** **DB val_accuracy = 0.405. For 3 classes that's
slightly worse than uniform random (0.333) only after class weighting
balances HOLD-domination — the raw signal is weak.** Flag-gated
(`QUANT_ENABLE_TRANSFORMER`), so it doesn't currently vote live.

**Verdict:** **REWORK or DROP.** It justifies its ensemble slot only if
(a) the 3-class abstain signal is materially different from a thresholded
binary (b) shrinking to 2 blocks brings val_acc above the binary attention
voter. Otherwise it's parallel to Attention with 5× the parameters.

### 7. DQN (`src/ml/rl_agent.py:434-708`)
**Architecture:** Double DQN. Online + target nets, both 3-layer MLP
[64, 64, 32] → 3 actions (HOLD/BUY/SELL). State = 22 dims (20 normalized
returns + balance + position).
**Param count:** ~7 K.
**Cap/data ratio:** Tiny — strong inductive bias toward simple decision
boundary. Good for tabular state.
**Regularization stack:** **Prioritized Experience Replay (PER)**, **n-step
returns (n=3)**, **soft Polyak target update (tau=0.005)**, **Huber loss**
(robust to TD-error outliers), **cosine LR annealing**, **noise augmentation
(0.1% on prices per episode)**, **importance-sampling weights to correct
PER bias**. Most thorough regularization stack of any voter.
**Optimizer/LR/schedule:** Adam, cosine annealing lr → 10% over training.
**Loss:** Huber.
**Sequence/lookback:** 20-bar return window. State is precisely what TradingEnv
serializes, so train/inference parity is enforced by code.
**Val split:** train_rl.py runs **80/20 per-symbol with `evaluate_agent`
called every 20 episodes for early stopping** (patience 30). Multi-asset
(GC=F + EURUSD=X + CL=F) for OOS generalization.
**Inductive bias:** **Sequential decision-making, not 1-shot prediction.**
The only voter that learns "given my current position and balance, what
should I do?" instead of "is the next bar up?". This IS the diversity slot.
**Known weakness:** State is just 20 normalized returns + 2 portfolio
features — does not see RSI/ATR/MACD/USDJPY at all. Lives in a different
feature space than everything else, which is good for diversity but
means it cannot benefit from the new triple-barrier labels (its labels
ARE the env reward, derived from price). Multi-asset training was
removed for ES=F (chronic loser), kept for GC/EURUSD/CL.
**DB metric:** `rl_best_reward` not directly comparable.

**Verdict:** **KEEP.** Best-engineered voter in the stack. Don't touch
on the triple-barrier retrain (its target is already R-shape via
TradingEnv reward).

### 8. SMC (rule-based, in scanner)
Not a learned model. Pure rule-based grading. Per memory: 74% live
directional accuracy on 50 decisive samples. Listed for completeness.
**KEEP.**

---

## Cross-cutting findings

### [CRITICAL] Training pipeline does not consume the 5m warehouse or triple-barrier labels
**Issue:** `train_all.py:105-174` pulls **1h yfinance** data (and falls
back to 15m or 1d). Triple-barrier labels were just shipped against the
5m XAU parquet warehouse. Running `train_all.py` unmodified will
retrain the models on 1h binary `compute_target` labels (>0.5 ATR move
in next 5 bars), **NOT** triple-barrier labels on 5m. The retrain will
be a no-op for the labelling improvement.

**Fix (before retrain):** Wire `train_all.py` to:
1. Read the 5m warehouse parquet (`HistoricalProvider.from_warehouse()`).
2. Use the new triple-barrier labels (`tools/build_triple_barrier_labels.py`
   output) as the y instead of `compute_target`.
3. Update LSTM/Attention/Decompose to accept the new label encoding (likely
   binary {WIN, LOSS} or 3-class {WIN, LOSS, TIMEOUT} — match
   transformer's 3-class structure for consistency).
4. Re-export ONNX (already wired post-training in step 7 of
   `train_all.py:660-686`).

### [CRITICAL] LSTM and Attention are not as diverse as their slot count suggests
**Issue:** LSTM, Attention, Decompose, DeepTrans all read **the same
34-feature vector** from `compute_features`, on **the same 60-bar
window**, with **the same scaler**. Their inductive biases differ
(recurrent vs attention vs decompose), but the input information set is
identical. In practice they will converge on correlated mistakes
exactly when we need them to disagree (regime changes). XGB also
shares the feature vector, just doesn't share the temporal window.
**Fix:** Two paths, pick one:
- **Reduce voter count.** Keep XGB v1, XGB v2, Attention, DQN, SMC. Drop
  LSTM (Attention superset), Decompose (off + leaky), DeepTrans (under-trained).
  5 voters with 4 distinct inductive biases.
- **Add real diversity.** Give LSTM a wavelet-decomposed view (different
  features), give Attention a multi-TF stack (5m+15m+1h windows), keep
  DeepTrans on 3-class abstain only (no overlap with binary voters).
  Higher complexity, but defensible.

### [IMPORTANT] LSTM "BULLISH_ONLY" hack still active in production
**Issue:** `ensemble_models.py:1196 LSTM_BULLISH_ONLY = True` mutes every
bearish LSTM call as "bearish 0-14% live accuracy". This was a
2026-04-16 patch over the anti-signal sweep winner. **Even after a
clean retrain, the flag is still True in code** — meaning we'd start a
new model artificially handicapped on half its outputs.
**Fix:** Add a TODO: after triple-barrier retrain finishes, run
`voter_forensics` for ≥30 LSTM calls and decide whether to remove the
flag. Don't ship the retrain with the flag still hard-on.

### [IMPORTANT] DeepTrans val_acc 0.405 on 3-class is not better than chance + class weights
**Issue:** With class weights inverting HOLD dominance, "uniform 1/3"
should land near 0.333 in raw acc. 0.405 is 7pp over uniform, but
weighted accuracy in a class-weighted training run typically inflates
above raw uniform — meaning we don't actually know whether the model
learned anything. Persisted metric is `_val_accuracy` not
`_val_accuracy_weighted` so the comparison is muddled.
**Fix:** Before next retrain, change `transformer_model.py:251` to log
**balanced_accuracy_score** + per-class precision/recall instead of raw
`val_accuracy`. If balanced acc <0.40, the voter has no signal — drop it
or restructure (smaller, pretrain on bigger dataset, etc.).

### [IMPORTANT] Decompose feature pipeline leaks the future
**Issue:** `_decompose_features` in `decompose_model.py:42-64` uses
`np.convolve(mode='same')` which is symmetric — at index `i`, the
trend includes prices from `i+period/2`. Edge-fix `t[-(period//2):] =
t[-(period//2)-1]` doesn't undo the leak; it just hides it at the right
edge. This explains the 0.769 walk-forward "accuracy".
**Fix:** Either drop the model entirely, OR rewrite with
`mode='valid'` + left-pad with NaN, OR use proper STL with `extrapolate=False`.
Easier to drop.

### [IMPORTANT] Self-learning has driven 3 high-bias voters to the floor
**Issue:** DB shows ensemble_weight_lstm=0.05, ensemble_weight_dqn=0.05,
ensemble_weight_smc=0.05. With `MIN_ACTIVE_WEIGHT=0.10`, all three
are **muted in live fusion**. The live ensemble is effectively 3 voters
(XGB 0.20 + Attention 0.20 + v2_xgb 0.10). Yet memory file
`asymmetry_flip_2026-04-26.md` claims SMC has 74% live acc and DQN was
"healthy at 66-80%". Either:
- Self-learning's EMA target is too aggressive and is mispenalising winners,
- Or live behavior actually shifted and the memory is stale.
**Fix:** Run `tools/voter_forensics.py` on the last 50 trades, compare
per-voter accuracy at decision time vs DB ensemble_weights. If
attribution disagrees with weights, the self-learner is broken.

### [NICE] No L2/weight-decay anywhere in Keras voters
**Issue:** Adam with no weight_decay → no L2 effect. Dropout alone is
the regularizer. On small data + heavy seq_len, AdamW(weight_decay=1e-4)
buys ~1pp generalization for free.
**Fix:** One-line change in compile() of LSTM, Attention, DeepTrans.

### [NICE] No ReduceLROnPlateau callback
**Issue:** Every Keras voter uses fixed LR + EarlyStopping. Even the
DeepTrans (deep transformer, generally very LR-sensitive) has no schedule.
**Fix:** Add `ReduceLROnPlateau(monitor='val_loss', factor=0.5,
patience=5, min_lr=1e-6)` to all four. Free convergence improvement.

### [NICE] Calibration uses "uncalibrated penalty" (0.8 shrinkage)
**Issue:** `model_calibration.py:208-212` shrinks any uncalibrated raw
prediction 20% toward 0.5. Combined with the ×4 / ×6 confidence
stretching in `ensemble_models.py:928,1019`, the "confidence" reported
to the gates is several manual transformations away from any actual
probabilistic semantics.
**Fix (post-retrain):** Train Platt scaler on ≥50 fresh post-retrain
trades and remove the shrinkage. The current scheme cancels itself out
on a calibrated voter and over-penalizes new voters.

### [NICE] DeepTrans training uses 80/20 split, every other voter uses walk-forward
**Issue:** Inconsistency. WF is the right answer for time-series; 80/20
chronological is its weaker cousin.
**Fix:** Move DeepTrans to 3-fold WF before next retrain.

### [NICE] No saved loss curves
**Issue:** Every Keras voter uses `verbose=0`. `history` is captured
but not persisted. Cannot eyeball whether early stopping fired at epoch
5 or epoch 80, cannot see val_loss vs train_loss gap.
**Fix:** Dump `history.history` to `models/<voter>_train_history.json`
on every retrain. One-line change.

### [NICE] yfinance is the data source for training, but live uses TwelveData
**Issue:** Per memory `data_source_reality.md`, yfinance and TwelveData
have a $65–75 absolute price gap on XAU. We train on yfinance (free,
broad history), infer on TwelveData. Features are scale-invariant
mostly (RSI, %returns), but **MinMaxScaler is fit on yfinance min/max,
applied to TwelveData min/max**. Mild distribution shift baked in at
inference time.
**Fix:** Train on warehouse parquet (which is TwelveData-derived per
strategy docs). Closes this gap once the warehouse migration lands.

---

## Pre-training go/no-go checklist

Before invoking the next retrain, verify:

- [ ] `train_all.py` reads from `data/historical/XAU_USD/5m/*.parquet`
      (warehouse), not yfinance.
- [ ] `train_all.py` consumes the **triple-barrier labels** built by
      `tools/build_triple_barrier_labels.py`, not `compute_target`.
- [ ] Decision made on **LSTM**: shrink to 64→32 + L2, or drop entirely.
- [ ] Decision made on **Decompose**: dropped from training pipeline,
      ensemble dict entry, frontend column, and ml_predictions
      schema (or kept hardwired-NEUTRAL but excluded from training).
- [ ] Decision made on **DeepTrans**: stays flag-gated until balanced
      accuracy clears 0.45 on the new 5m triple-barrier 3-class labels;
      otherwise dropped.
- [ ] **`LSTM_BULLISH_ONLY` flag** removal is in the same PR as the
      retrain — or explicitly deferred with a TODO + ticket.
- [ ] **Self-learning loop is paused** during the first 24 h post-retrain
      so it doesn't immediately penalize a fresh model on transient noise
      (set `kelly_reset_ts` and pause `update_ensemble_weights` calls).
- [ ] Add **per-voter loss curve dump** to all training scripts (one-liner).
- [ ] Run a **single-fold dry run** with `--epochs 2` to confirm the
      full pipeline works end-to-end with new labels before the long run.
- [ ] After retrain: run `tools/voter_forensics.py` on the holdout
      slice and compare per-voter accuracy vs current DB weights.
      Reset weights if discrepancy >15pp.
- [ ] Recompile **Treelite** for XGB after retrain (`tools/compile_xgb_treelite.py`)
      — `.dll` is gitignored and stale `.dll` vs new `.pkl` is a real bug
      surface.
- [ ] Re-export **ONNX** (already automatic in `train_all.py:660-686`).
- [ ] Confirm **scaler is saved** for every voter (LSTM, Attention,
      Decompose-if-kept, DeepTrans) and that ensemble inference uses
      the same scaler instance.

If any item above is unchecked, the retrain is a NO-GO.
