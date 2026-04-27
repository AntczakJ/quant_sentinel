# Per-direction model split — C deferred (2026-04-27)

Status: **deferred — not appropriate for tonight's session.**
Original ask was "do A → D → B → then C". A, D, B all done.
This doc explains why C needs more time than this session has, and
what would unblock it.

## What "C" was supposed to be

Train two separate XGBoost classifiers — `xgb_long` and `xgb_short` —
each predicting WIN/LOSS for setups in its own direction. The
intuition: per `memory/asymmetry_flip_2026-04-26.md`, direction
asymmetry is real (LONG-side and SHORT-side have very different
WR profiles in the current XAU bull regime), so a single model is
likely to learn the average and miss both edges.

Replace `predict_xgb_direction(...)` in `src/ml/ensemble_models.py`
with a router that picks the right model based on the setup's
direction, and let each model specialize.

## Why we can't just do it now

### 1. Live-trade sample is far too small

```
LONG  WIN: 4     LONG  LOSS: 16   →  n=20, WR 20%
SHORT WIN: 5     SHORT LOSS: 16   →  n=21, WR 24%
```

Per-direction XGB on 20-21 examples will memorize the training set,
produce overfitted weights, and validate at the level of the noise
floor. There is no honest way to train on this and have anything
useful come out.

### 2. The warehouse path is the proper source

`data/historical/XAU_USD/5min.parquet` has **231,464 bars** —
~3 years of XAU 5m data. With triple-barrier labels (memory:
`label_baseline_2026-04-26.md`) we can derive ~11k+ proper
direction-specific labels by filtering to bars where the scanner
WOULD have considered a setup. That's a workable training set.

But triple-barrier labeling is **Phase 2** of the
`2026-04-25_max_winrate_master_plan.md` master plan — it requires:

1. Bar-by-bar forward simulation (does price hit +R*ATR before
   -R*ATR within hold_cap?)
2. Filter to "scanner-eligible" entry bars
3. Compute features per row using the same `compute_features()`
   pipeline the live scanner uses
4. Time-series-respecting train/val split (walk-forward style)
5. Train both XGB_LONG and XGB_SHORT
6. ONNX + Treelite compile each (production-grade inference latency)
7. `ensemble_models.py` loader update with router + fallback
8. Walk-forward validation showing the per-direction split actually
   beats single-model baseline on holdout windows
9. Shadow logging in production for 1-2 weeks before live rollout

This is **multi-day work**, not 2-3 hours. Rushing it gives us
either a broken model in production or a fancy-looking but
overfitted artifact. Neither is "porządnie".

## What would unblock it

A clean Phase 2 implementation of triple-barrier labeling. There's
some scaffolding (`tools/triple_barrier_*` per the master plan
discussion) but no productionized labeled-warehouse output. If the
next session focuses on:

1. `tools/build_triple_barrier_labels.py` — write a parquet of
   `(timestamp, features, label_long, label_short, hold_bars,
   exit_reason)` to `data/historical/XAU_USD/labels_triple_barrier_5m.parquet`
2. Verify label balance + per-regime stratification
3. Then per-direction XGB training is a one-day job on top.

## Tonight's bound on C

We're not training a per-direction model on n=21. We're not building
triple-barrier in 30 minutes. We're documenting why both are wrong
and protecting future-Janek from being tempted to do either when the
memory of "we tried in April" feels more recent than it is.

## Related memory

- `memory/asymmetry_flip_2026-04-26.md` — confirms direction
  asymmetry is real
- `memory/label_baseline_2026-04-26.md` — triple-barrier TP rate
  is 26% baseline; binary labels are tautological
- `docs/strategy/2026-04-25_max_winrate_master_plan.md` — Phase 2
  (labels) and Phase 3 (per-direction) sequencing
- `docs/strategy/2026-04-27_lot_sizing_rebuild_design.md` — same
  "decision-gate-blocked-on-data" pattern; this is its sibling

## Earliest revisit

After Phase 2 (triple-barrier labels) ships. Independent of live
data growth — this is a pre-trained model, doesn't depend on the
live cohort getting bigger.
