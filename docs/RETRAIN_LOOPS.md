# Strict-Gated Retrain Loops

Each ML voter has a dedicated retrain script that hammers the model with
random-seeded hyperparameter perturbation, scores against held-out test,
and **refuses to promote** unless the result clears two independent
sanity gates. Designed for "I think this voter has gone stale, find a
better one in 30 minutes" workflows — the slower Optuna sweeps
(`tune_rl.py`, `tune_lstm.py`) are for full searches.

## Why two gates

Half the catastrophic LSTM/DeepTrans winners we discovered would have
shipped if we'd only checked val accuracy. They scored well by always
predicting the dominant class on a class-imbalanced test split. The
two-gate filter catches that:

| Gate | What it tests | Failure mode it catches |
|---|---|---|
| `balanced_accuracy_score >= floor` | Per-class hit rate | Class imbalance cheating |
| `live_stdev >= floor` (10 windows on fresh yfinance) | Output variance on real bars | "Always neutral" / "always SHORT" mode collapse |

Specific floors per script — see each `--target` and `--min-live-stdev`
defaults.

## Loops

### `retrain_lstm_loop.py`
- 8 default iterations, target `balanced_acc >= 0.55`, `live_stdev >= 0.05`
- Search: `seq_len, hidden, dropout, lr, batch_size, epochs, scaler` (RobustScaler / MinMax)
- Architecture: 3 stacked LSTM with config base widths
- Used 2026-04-13 to find a winner: trial 38 (seq=30, hidden=256, robust, lr=1.07e-3)
  cleared gates and was promoted to production (`models/lstm.keras`)

### `retrain_attention_loop.py`
- 5 default iterations, target `balanced_acc >= 0.55`, `live_stdev >= 0.03`
- Search: `seq_len, n_heads, key_dim, n_blocks, dropout, lr, batch, epochs, scaler`
- Architecture: 1-3 multi-head attention blocks + LayerNorm + dense head
- Used 2026-04-13 to find a winner: balanced_acc 0.521 (marginal but real edge,
  `live_stdev` 0.048) — promoted

### `retrain_deeptrans_loop.py`
- 6 default iterations, target `balanced_acc >= 0.45`, `live_stdev >= 0.05`
- Search: `seq_len, n_blocks, n_heads, d_model, ffn_dim, dropout, lr, batch,
  epochs, horizon, threshold_pct, scaler`
- Architecture: pre-LN deep transformer (mirror `transformer_model.build_deep_transformer`)
- Used 2026-04-13: 4 iterations all flat on live, no winner promoted.
  DeepTrans stays disabled (`QUANT_ENABLE_TRANSFORMER` unset).

## Common pattern (if writing a new one)

1. `fetch_ohlcv(symbol, window)` — yfinance with cache
2. `prepare(df, hp)` — features → labels → 3-way time-ordered split, scaler fit on train only
3. Sample hparams, train, evaluate
4. `live_stdev_check()` — fetch fresh 2 months of yfinance and compute prediction std
   over 10 rolling windows
5. Two-gate decision; if winner viable: atomic `models/<voter>.keras` write +
   ONNX regen + `log_training_run` entry

## When NOT to use these

- For full hyperparameter exploration → use the Optuna sweeps instead
  (`tune_rl.py`, `tune_lstm.py`). They search 30+ trials with TPE +
  MedianPruner and are MUCH more thorough.
- For "verification" only (is the voter still working?) → just call the
  voter's `predict_*` from a Python repl on live data and inspect the
  std/range. We did this for DPformer 2026-04-13 in 1 minute.

## Promotion safety

Each loop writes the winner directly to the production model path
(`models/<voter>.keras`) using atomic `.tmp` + `os.replace`. There is
NO separate `_winner.keras` step like the Optuna sweeps use. So:

- Take a backup before running these loops if you care about the current
  artefact: `cp models/<voter>.keras models/<voter>.pre_<ts>.keras`
- Scanner picks up the new model on the next inference call (no cache,
  see `_load_*` functions in `ensemble_models.py`).
