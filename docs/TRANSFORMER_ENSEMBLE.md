# Deep Transformer Voter (`deeptrans`)

A 7th voter for the ML ensemble: a pre-LN deep transformer encoder
designed to complement the existing `attention` (TFT-lite) and
`dpformer` (decomposition fusion) voters. It is **off by default** —
enabled only when `QUANT_ENABLE_TRANSFORMER=1` is set in the
environment, so production behavior is unchanged until an operator
explicitly flips the switch.

---

## Why another transformer?

- `attention_model` is a two-layer TFT-lite with binary sigmoid output.
  Fast, but tends to always commit to a direction — it has no native
  "no opinion" signal.
- `dpformer` decomposes the series first, then fuses components. Great
  for low-vol regimes but struggles on abrupt regime shifts.
- `deeptrans` is **4-6 pre-LN transformer blocks** with positional
  encoding and a **3-class softmax head** (LONG / HOLD / SHORT). The
  HOLD class gives it a first-class way to abstain on noisy windows,
  which lowers ensemble overconfidence during chop.

## Architecture

```
Input(seq_len, n_features)
  -> Dense(d_model)                              # input projection
  -> + sinusoidal positional encoding
  [pre-LN transformer block] x n_blocks
    -> LayerNorm -> MultiHeadAttention -> residual
    -> LayerNorm -> FFN(gelu) -> Dropout -> residual
  -> LayerNorm -> GlobalAveragePooling1D
  -> Dense(64, relu) -> Dropout
  -> Dense(3, softmax)
```

Defaults (`src/ml/transformer_model.py`):
`seq_len=60, n_blocks=4, n_heads=8, d_model=64, ffn_dim=128, dropout=0.15`.

The softmax output is mapped to the ensemble's scalar `value` by:

```
value = P(LONG) + 0.5 * P(HOLD)
confidence = |P(LONG) - P(SHORT)|
```

So pure HOLD lands exactly on the neutral 0.5, and confidence falls as
the model grows uncertain — unlike binary sigmoid voters whose
confidence stays high on 50/50 calls.

## Labels

At training time, each window is labeled by its `horizon`-step forward
return:

| Forward return | Label  |
|---|---|
| `> +threshold_pct` | `LONG`  |
| `< -threshold_pct` | `SHORT` |
| otherwise          | `HOLD`  |

Defaults: `horizon=5` bars, `threshold_pct=0.2` (20 bps). The class
balance is computed on the fly and passed to `model.fit` as
`class_weight`, so HOLD dominance doesn't let the model cheat by always
predicting HOLD.

## Training

```bash
# Default: 2y/1h XAU/USD, 4 transformer blocks, 40 epochs
python train_transformer.py

# Larger / longer:
python train_transformer.py --epochs 80 --n-blocks 6

# Different symbol (EUR/USD forex):
python train_transformer.py --symbol EURUSD=X
```

**Do NOT run this while the Optuna RL sweep is active** — both compete
for TF/CPU and will seriously slow each other. Wait for the sweep to
finish.

Artifacts written to `models/`:

- `deeptrans.keras` — Keras model
- `deeptrans_scaler.pkl` — pickled `{scaler, seq_len, feature_cols, ...}`
- `deeptrans.onnx` — for DirectML GPU inference (auto-regenerated)

Each run is logged to `models/training_history.jsonl` via the training
registry, so the UI's training-history widget picks it up.

## Enabling in production

```bash
# Windows (cmd)
set QUANT_ENABLE_TRANSFORMER=1

# Windows (PowerShell)
$env:QUANT_ENABLE_TRANSFORMER = "1"

# Linux/macOS
export QUANT_ENABLE_TRANSFORMER=1
```

Then restart the scanner. With the flag set and the artifact present,
`deeptrans` starts appearing in `/api/metrics` predictions and in the
model track record. Initial weight is `0.05` (deliberately tiny — let
the self-learning `update_ensemble_weights` earn it up).

## Rolling back

1. Unset `QUANT_ENABLE_TRANSFORMER` (or set it to anything other than
   `1`).
2. Restart the scanner.

That's it. `predict_deeptrans` will short-circuit to `None` and the
ensemble will mark the voter as `unavailable` — exactly the same code
path as any missing-artifact voter, so nothing else changes.

To also reset any self-learned weight drift:

```bash
python -c "from src.core.database import NewsDB; db = NewsDB(); \
    db.set_param('ensemble_weight_deeptrans', 0.05); \
    db.set_param('model_deeptrans_correct', 0); \
    db.set_param('model_deeptrans_incorrect', 0)"
```

## Testing

`tests/test_transformer_model.py` covers 17 cases end-to-end against
synthetic data only — no yfinance, no `compute_features` dependency,
runs in ~18 s. Re-run after touching this module:

```bash
python -m pytest tests/test_transformer_model.py -x -q
```
