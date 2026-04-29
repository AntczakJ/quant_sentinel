# Pre-Training Master Audit — 2026-04-29

**Verdict across 4 independent audits: NO-GO on retraining.**

This document synthesizes:
- `2026-04-29_audit_1_data_leaks.md`
- `2026-04-29_audit_2_architecture.md`
- `2026-04-29_audit_3_reprodeploy.md`
- `2026-04-29_audit_4_label_ensemble.md`

Each agent reached an independent NO-GO verdict. Findings converge — the
system is currently running on out-of-distribution training data, with
mathematically-inverted calibration, frozen voter weights, multiple
data-leak paths, and zero reproducibility. Retraining now would lock in
all of this and require another full re-do.

## Executive summary

The live ensemble is **not** what its design says. What's actually happening:

1. **Three of seven voters effectively disabled.** SMC, LSTM, DQN, DeepTrans
   all sit at weight 0.05, below the 0.10 active-floor → muted in fusion.
   Only XGB (0.20) + Attention (0.20) + v2_xgb (0.10) actually contribute.
2. **The 3 calibrated voters output a near-constant 0.36-0.40 regardless
   of input.** Verified by loading `models/calibration_params.pkl`:
   - `lstm: a=-0.193, b=-0.395`
   - `xgb:  a=-0.156, b=-0.404`
   - `dqn:  a=-0.171, b=-0.399`
   With negative `a`, higher raw → lower calibrated. `lstm_pred` line 988
   gets REPLACED by the calibrated value, then used to set `direction`
   on line 992. So **LSTM/XGB/DQN currently vote SHORT on every signal**.
3. **Training data ≠ inference data.** `train_all.py:117-127` pulls
   yfinance `GC=F` (Gold Futures); live inference uses TwelveData `XAU/USD`
   (Spot Gold). $65-75 price gap (CLAUDE.md). Every live prediction is
   on out-of-distribution data. The 3-year TwelveData warehouse at
   `data/historical/XAU_USD/` is ignored by the trainer.
4. **Just-shipped triple-barrier labels are not wired anywhere.** Five v1
   voters still train against the legacy `compute_target` (binary
   "≥0.5 ATR in 5 bars" — flagged tautological).
5. **Multiple data-leak paths.** Centered convolution in Decompose
   (`np.convolve mode='same'`), scaler fit-on-full-set before walk-forward
   in all 4 neural voters, multi-TF ffill leaking +30 min future bars
   into v2_xgb (which is LIVE at weight 0.10).
6. **Zero determinism.** No seeds anywhere in `train_all.py`, no
   `enable_op_determinism()`, mixed-precision unconditional. Same code +
   same data ≠ same weights.
7. **`update_ensemble_weights` defined but never called.** Voter weights
   are frozen at hand-mutated values forever.

Live cohort 33 trades, WR 46.7%, PF 0.83, return -1.08% — consistent
with the system trading near-random off SMC patterns, with ML mostly a
veto and calibration biasing the 3 calibrated voters toward SHORT.

## Severity-ranked deduplicated findings

### 🚨 P0 — LIVE TRADING IS AFFECTED RIGHT NOW

| # | Finding | Source | Location | Impact |
|---|---|---|---|---|
| P0.1 | Calibration mathematically inverts signals (3 calibrated voters) | A4 | `models/calibration_params.pkl`, `ensemble_models.py:988,1009,1071` | LSTM/XGB/DQN vote SHORT regardless of raw model output. Live since calibration was last fit. |
| P0.2 | Training data is yfinance GC=F (futures); inference is TwelveData XAU/USD (spot) | A3, A2 | `train_all.py:117-127`, `data_sources.py:499` | Every live prediction is on out-of-distribution data. $65-75 price gap. |
| P0.3 | v2_xgb (live @0.10 weight) consumes multi-TF ffill features that leak +30 min future bars | A1 | `features_v2.py` (multi-TF ffill, USDJPY ffill) | v2_xgb's "PF 2.24 OOS" backtest finding is contaminated. |

These three are **active bugs in production**. Until P0.1 is fixed, every
trade decision the calibrated voters touch is direction-flipped or
near-constant. P0.2 means the ML edge measured offline doesn't transfer.
P0.3 means our newest, "best OOS" voter is leaking.

### ⚠️ P1 — BLOCKERS for retraining

| # | Finding | Source | Location | Why blocker |
|---|---|---|---|---|
| P1.1 | Centered convolution leak in Decompose (`np.convolve mode='same'`) | A1, A2 | `decompose_model.py:48` | Symmetric kernel pulls 10 future bars into trend at bar t. Explains 78-80% val_acc anomaly. |
| P1.2 | Scaler fit on full training set before walk-forward folds | A1 | `ml_models.py:172`, `attention_model.py:93`, `transformer_model.py:212`, `decompose_model.py:158` | Fold 1 trains on data normalized by fold 5 statistics. Inflates every reported walk-forward accuracy by unknown X. Affects 4 neural voters. |
| P1.3 | Triple-barrier labels not wired to any production training | A4, A2 | `ml_models.py:59,164`, `attention_model.py:78`, `retrain_*_loop.py` | Five v1 voters still train against legacy `compute_target`. The labels we shipped today are dead weight. |
| P1.4 | TWO duplicate triple-barrier implementations | A4 | `tools/build_triple_barrier_labels.py` (mine) + `src/learning/labels/triple_barrier.py` (older) | Different label encodings. Standardize on one before any consumer is built. |
| P1.5 | `update_ensemble_weights` defined but never called | A4 | `ensemble_models.py` (def) + `api/main.py:945` (`_auto_resolve_trades` doesn't trigger it) | Voter weights frozen at hand-mutated values. Self-learning is dead. |
| P1.6 | DATE-based join in `fit_from_history` fan-outs (1 prediction → many trades) | A4 | `model_calibration.py:147` | Calibration is fit on garbage data even ignoring the inversion bug. |
| P1.7 | Calibration label is trade WIN/LOSS, raw is P(LONG wins). Mixing LONG+SHORT gives meaningless correlation | A4 | `model_calibration.py:163` | Even with the join fixed, the math doesn't fit Platt's assumptions. Need per-direction calibration or different framing. |
| P1.8 | No determinism seeds in `train_all.py` | A3 | `train_all.py` (no `tf.random.set_seed`, no `enable_op_determinism`) | Same code + same data ≠ same weights. Reproduce-bug-fix-test cycle is broken. `scripts/train_v2.py:44-48` has the right block — copy it. |
| P1.9 | No stale-dll detection for Treelite XGB | A3 | `_load_xgb` only checks pkl_path/onnx_path mtime, not .dll | Retrain XGB without recompile → silent serving of stale weights. |
| P1.10 | "7-voter ensemble" is actually 3 voters | A2, A4 | DB voter weights | Live diversity is XGB + Attention + v2_xgb. The other four are floor-quarantined. Plan must address this. |
| P1.11 | All ML voters read the same 34-feature vector | A2 | `compute_features` shared by XGB/LSTM/Attention/Decompose | Different inductive biases on identical info don't decorrelate well. |
| P1.12 | Walk-forward harness doesn't actually retrain | A4 | `run_walk_forward.py` calls walk_forward with `train_runner=None` | What we call "walk-forward" is a regime-stability test of a static model. Document this; don't claim it as walk-forward proper. |

### 🟡 P2 — should fix in same retraining PR

| # | Finding | Source | Location |
|---|---|---|---|
| P2.1 | No `feature_cols` list pinning at training time | A1 | training scripts |
| P2.2 | No purge/embargo in walk-forward (label-leak between adjacent folds) | A1 | `walk_forward.py` |
| P2.3 | v2 R-multiple regression uses MSE, dominated by outliers | A4 | v2_xgb training | Use Huber. |
| P2.4 | Confidence multipliers (×6 attention, ×4 xgb, ×2 lstm) are arbitrary | A4 | `ensemble_models.py` | Replace with calibrated probabilities once P0.1+P1.6+P1.7 done. |
| P2.5 | DPformer / Decompose still wired in code/schema/training despite weight=0 | A2, A4 | multiple | Drop completely OR fix the leak — current state is dead weight. |
| P2.6 | DeepTrans val_acc 0.405 on 3 classes — barely above class-weighted random | A2 | training output | Drop or shrink dramatically. |
| P2.7 | `LSTM_BULLISH_ONLY` flag — derived from since-stale finding | A2 | `ensemble_models.py` | Remove or re-validate against current data. |

### 🟢 P3 — research / nice-to-have

- Add per-direction model split (long-only / short-only training).
- Voter correlation matrix on held-out window (will likely show r > 0.85 for XGB↔Attention, justifying P1.11 finding empirically).
- Class imbalance handling (`scale_pos_weight`, `class_weight`) — triple-barrier is ~30/60/10 imbalanced.
- Replace MSE with Huber for R-multiple regression head.

## Live-trading impact + immediate action

**Currently live:** scanner running (PID api), B7 SHORT-block in zielony
regime, MAX_LOT_CAP=0.01, DISABLE_TRAILING=1, scanner producing ~3-4
attempts per day rejected by various filters.

**P0 affects every active trade decision.** Specifically:
- LSTM/XGB/DQN calibrated values are stuck in 0.36-0.40 → vote SHORT
- B7 blocks most SHORTs in current zielous regime
- Net result: scanner mostly idles, occasional setups go through on SMC
  scoring + Attention + v2_xgb + frozen-weight votes

**Recommended action TODAY (P0 hotfix only):**

1. **Disable Platt calibration** by writing a `calibration_params.pkl`
   with all `fitted: False`. The fallback at `model_calibration.py:82`
   (`if not self.fitted: return prediction`) will return the raw signal
   unchanged. This is a 10-line script; reversible by restoring backup.
2. **Restart API** to load the unfitted calibration.
3. **No retraining today.** The data-source mismatch (P0.2) and the
   training-pipeline rewrite (P1.3, P1.4) require a multi-day
   plumbing project before we can responsibly hit "fit".

**Do NOT today:**
- Retrain any voter
- "Re-fit" the calibration with the same buggy `fit_from_history`
- Touch `train_all.py` until we agree on a single triple-barrier impl

## Recommended fix order (ship as ordered batches)

### Batch A — TODAY: Halt the bleed

1. P0.1 — neutralize `calibration_params.pkl` (fitted=False on all entries)
2. Restart API
3. Smoke-verify: `lstm_pred` and raw equal in `/api/scanner/peek` output
4. CHANGELOG + memory entry
5. Stop scanner if Janek wants — pause flag is one-line

### Batch B — Tomorrow: Training-pipeline rewrite (multi-day)

1. P0.2 — `train_all.py` reads `data/historical/XAU_USD/*.parquet`
   instead of yfinance `GC=F`
2. P1.3 — switch `compute_target` consumers to read triple-barrier parquet
3. P1.4 — pick canonical triple-barrier impl (mine in `tools/`, theirs
   in `src/learning/labels/`); migrate the loser; delete it
4. P1.8 — add determinism block from `scripts/train_v2.py:44-48`
5. P2.1 — pin `FEATURE_COLS` list at training time, save next to model
6. P1.9 — `_invalidate_if_stale` watches `xgb_treelite.dll` mtime too;
   refuse to load stale .dll
7. Run smoke training of XGB on triple-barrier 5min labels — verify
   in/out-of-sample numbers are sane

### Batch C — After Batch B: Leak fixes

1. P1.1 — replace `np.convolve(mode='same')` with backward-only rolling
   mean in Decompose (or drop Decompose entirely per P2.5)
2. P1.2 — refactor scaler fit to inside walk-forward fold (4 voters)
3. P0.3 — audit `features_v2` for ALL ffill/multi-TF/USDJPY future-leak
   paths; fix or document each one
4. P2.2 — add purge/embargo to walk-forward folds

### Batch D — After Batch C: Ensemble logic

1. P1.5 — wire `update_ensemble_weights` from `_auto_resolve_trades`
   resolve event in `api/main.py`
2. P1.6, P1.7 — redesign calibration: per-direction, per-model, fit
   with proper join (prediction.id → trade.id, not date-based)
3. P1.10, P1.11 — voter correlation measurement; drop redundant voters
4. P2.4 — replace arbitrary confidence multipliers with calibrated probs
5. P2.6 — DeepTrans drop or shrink decision
6. P2.7 — `LSTM_BULLISH_ONLY` keep or remove decision

### Batch E — After Batch D: Retrain on clean substrate

1. Retrain XGB v3 on triple-barrier 5min, walk-forward purged, scaler
   per-fold, features_v2 leaks closed
2. Retrain neural voters one-at-a-time, same protocol
3. Refit per-direction calibration on retained predictions vs
   per-direction trade outcomes
4. Validate ensemble PF on held-out 6-month window before any weight
   adjustment in DB
5. Walk-forward proper (with retraining per window) — only then claim
   "regime-stable strategy"

## Pre-training go/no-go

**The system goes green for retraining when ALL of these tick:**

- [ ] Calibration neutralized OR redesigned (P0.1, P1.6, P1.7)
- [ ] Training reads warehouse parquet, not yfinance (P0.2)
- [ ] Training consumes triple-barrier labels, single canonical impl (P1.3, P1.4)
- [ ] Determinism seeds in place (P1.8)
- [ ] Decompose centered-convolution fixed OR Decompose dropped (P1.1)
- [ ] Scaler fit per fold (P1.2)
- [ ] features_v2 multi-TF/macro ffill audited and fixed (P0.3)
- [ ] FEATURE_COLS pinning at train time (P2.1)
- [ ] Treelite stale-dll detection live (P1.9)
- [ ] `update_ensemble_weights` wired (P1.5)
- [ ] Walk-forward harness proven to retrain per window (P1.12 upgrade)
- [ ] Smoke training of single voter on the new pipeline produces sane in/out-of-sample numbers
- [ ] Voter correlation matrix taken on a held-out window (input to P1.10/P1.11 decision)

**Until then: NO RETRAINING.** Every retrain on the current pipeline
locks in all the bugs above and will need to be redone.

## Files committed today (audit set)

- `docs/strategy/2026-04-29_audit_1_data_leaks.md`
- `docs/strategy/2026-04-29_audit_2_architecture.md`
- `docs/strategy/2026-04-29_audit_3_reprodeploy.md`
- `docs/strategy/2026-04-29_audit_4_label_ensemble.md`
- `docs/strategy/2026-04-29_pretraining_master.md` (this doc)
