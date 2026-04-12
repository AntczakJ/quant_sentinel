# RL Hyperparameter Tuning (Optuna sweep)

`tune_rl.py` runs a population-based search over the DQN agent's
hyperparameters — learning rate, network shape, reward geometry, data
window, and more — to attack the ~20pp train/OOS overfit gap documented
in the training insights memo. It uses Optuna with TPE sampling and a
median pruner so that unpromising trials are killed early, making an
overnight sweep actually cover ground.

---

## What it does

Three-way split per symbol:

```
|----- 60% train -----|-- 20% val --|-- 20% test --|
         (trial training)   (trial scoring + pruning)  (held out; only seen by the winner)
```

- Every trial samples a fresh point in hyperparameter space, trains a
  DQN on the train slice, and reports mean val return at each checkpoint.
- Optuna prunes trials that are below the running median at the same
  checkpoint step, so bad configs don't burn compute.
- After the study, the best trial is retrained on `train + val` merged
  and scored on the **held-out test** slice. That number is the honest
  generalization estimate — not the in-sweep val number.
- The winner model is saved to `models/rl_sweep_winner.keras` (+ ONNX +
  params pickle). Your production `models/rl_agent.keras` is not touched
  until you promote it manually.

## Search space

| Param | Range / Choices | Notes |
|---|---|---|
| `lr` | 1e-4 – 3e-3 (log) | Adam LR |
| `gamma` | 0.90 – 0.995 | discount factor |
| `epsilon_decay` | 0.990 – 0.9995 | exploration annealing |
| `epsilon_min` | 0.005 – 0.05 | floor for epsilon |
| `tau` | 0.001 – 0.02 (log) | Polyak target update |
| `n_step` | {1, 2, 3, 5} | n-step returns |
| `batch_size` | {32, 64, 128} | replay batch |
| `net_width` | {32, 64, 128} | hidden units |
| `net_depth` | 2 – 4 | hidden layers |
| `dropout` | 0.0 – 0.3 | regularization |
| `noise_std` | 0.0 – 0.005 | price-augment noise |
| `sl_atr_mult` | 1.0 – 2.5 | SL distance |
| `target_rr` | 1.5 – 3.5 | TP:SL ratio |
| `per_alpha` | 0.4 – 0.8 | PER priority exponent |
| `data_config` | `2y_1h` / `1y_1h` / `5y_1d` / `2y_4h_synth` | data window |

## Runbook

```bash
# Smoke test (~1 minute) — always run this first after code changes:
python tune_rl.py --smoke

# Full overnight sweep (60 trials x 150 eps, expect 6–12h on a GTX 1070):
python tune_rl.py --n-trials 60 --episodes 150 --study-name rl_sweep_v1

# Resume an interrupted run — state lives in SQLite:
python tune_rl.py --resume --study-name rl_sweep_v1 --n-trials 60 --episodes 150

# Inspect a study without re-running anything:
python tune_rl.py --report --study-name rl_sweep_v1

# Retrain-and-save the winner explicitly (also runs automatically at end):
python tune_rl.py --apply-winner --study-name rl_sweep_v1
```

### Live progress

While the sweep runs, these files update:

| Path | What |
|---|---|
| `data/optuna_rl.db` | SQLite study storage (Optuna managed). |
| `data/sweep_heartbeat.json` | Per-trial progress snapshot, rewritten at every val checkpoint. |
| `reports/sweep_<study>.json` | Final leaderboard + best params + test metrics. |
| `models/rl_sweep_winner.*` | Retrained winner (keras + params + onnx). |

The heartbeat file matches the shape of `data/training_heartbeat.json`
so a future UI widget can visualize sweep progress the same way the
training widget does.

## Promoting the winner to production

After `--apply-winner` writes `models/rl_sweep_winner.keras`, compare
it to the current production model:

```bash
python eval_rl.py --compare models/rl_agent.keras models/rl_sweep_winner.keras
```

If the winner is materially better on the held-out basket, promote it:

```bash
# Back up current production:
cp models/rl_agent.keras models/rl_agent.pre_sweep.keras
cp models/rl_agent.keras.params models/rl_agent.pre_sweep.keras.params
cp models/rl_agent.onnx models/rl_agent.pre_sweep.onnx

# Promote:
cp models/rl_sweep_winner.keras models/rl_agent.keras
cp models/rl_sweep_winner.keras.params models/rl_agent.keras.params
cp models/rl_sweep_winner.onnx models/rl_agent.onnx
```

Restart the scanner so it picks up the new weights:
`python verify_install.py` to confirm everything still loads.

## Interpreting the leaderboard

The `val_return` reported during the sweep is on the val slice only.
The `test_return` in the final report is the honest number — that's the
one to trust. A healthy winner looks like:

- `test_return` within 5–8pp of `val_return` (not the 20pp gap we started with)
- `per_symbol_test` — positive on at least 2 of 3 symbols
- Winning `n_step >= 2` and `net_depth >= 3` usually generalizes better

If every trial converges to the same `data_config`, that's a signal the
data window matters more than the architecture — consider expanding the
data set before tuning further.

## Disk + compute budget

- Disk: ~200 MB (SQLite + parquet cache + model artifacts).
- CPU/GPU: each trial ≈ 3–7 minutes on a GTX 1070, less with pruning.
- Full 60-trial sweep at 150 episodes: ~6–10 h wall clock with pruning
  killing the bottom half around episode 30.
