# Walk-forward grid backtest (`run_backtest_grid.py`)

Two-stage parameter search over production strategy knobs —
`min_confidence`, `sl_atr_mult`, `target_rr`, `partial_close`,
`risk_percent` — run against the real scanner pipeline on isolated
historical data. Every cell is scored on walk-forward windows (mean +
stdev across windows) and stress-tested with a Monte Carlo bootstrap;
results are saved per-cell so an interrupted run resumes cheaply.

---

## Why a rewrite?

The previous `run_backtest_grid.py` iterated `sl_atr_mult` and
`target_rr` but only set `QUANT_BACKTEST_MIN_CONF` in the environment
before each run. The production code reads SL / RR from
`dynamic_params` (see `finance.py:98-100`), so those two dimensions
were silently ignored — the old grid effectively varied only
`min_confidence`. The new version writes the relevant keys into
`data/backtest.db`'s `dynamic_params` table before every cell.

## Pipeline

```
Stage A (fast pre-filter)        Stage B (deep evaluation)
  1 window, no MC           -->    N walk-forward windows + Monte Carlo
  96 cells * ~1 min each           top_n from Stage A
  ~ 1.5 h                          ~ 3-5 h
```

Stage A throws out obviously broken configs (no trades, huge DD, PF < 1)
so Stage B only spends walk-forward + Monte Carlo time on candidates
that passed a cheap sanity check. Both stages write per-cell JSONs to
`reports/wf_grid_<name>_<stage>/cell_<hash>.json` and stage summaries to
`stage_<a|b>.json` next to them.

## Search space

| Dim | Values | Default set |
|---|---|---|
| `min_confidence` | 0.40, 0.50, 0.55, 0.60 | 4 |
| `sl_atr_mult` | 1.5, 2.0 | 2 |
| `target_rr` | 2.0, 2.5, 3.0 | 3 |
| `partial_close` | off, on | 2 |
| `risk_percent` | 1.0, 2.0 | 2 |
| **Total cells** | | **96** |

Edit `build_grid` in `run_backtest_grid.py` to add / remove dimensions.

## Commands

```bash
# Smoke check (3 cells, no WF, no MC — ~2-3 minutes, safe next to the RL sweep):
python run_backtest_grid.py --smoke

# Default two-stage run (recommended — wait for the RL sweep to finish first):
python run_backtest_grid.py --days 14 --windows 4 --mc 500

# Only Stage A:
python run_backtest_grid.py --days 7 --stage a

# Only Stage B, using a specific Stage A report:
python run_backtest_grid.py --stage b --top-n 12 \
    --stage-a-report reports/wf_grid_default_A/stage_a.json

# Inspect a finished grid without re-running:
python run_backtest_grid.py --report --name default_B

# Force-rerun (ignore cached cell JSONs):
python run_backtest_grid.py --days 14 --no-resume
```

## Output layout

```
reports/wf_grid_<name>_A/
    cell_<hash>.json        # one per Stage A cell
    stage_a.json            # Stage A summary + top-N order
reports/wf_grid_<name>_B/
    cell_<hash>.json        # one per Stage B cell
    stage_b.json            # Stage B summary + Pareto front
```

Each `cell_*.json` contains: the full parameter dict, every window's
raw stats (return, WR, PF, Sharpe, Sortino, Calmar, expectancy),
aggregated mean + stdev, and the Monte Carlo percentiles.

## How cells are ranked

Two views, both printed by `--report`:

**Composite score (scalar)** — `0.4*Sharpe + 0.3*Calmar + 0.3*PF`, all
on the mean-across-windows numbers. Higher is better. Cells with no
trades or no Sharpe (e.g. `total_trades == 0` under very strict
`min_confidence`) sort to the bottom.

**Pareto front on (Sharpe, -|MaxDD|)** — the set of cells no other cell
strictly dominates. Useful for picking a config at a specific
risk/return appetite: pick a point on the front, not the scalar winner,
if you want to trade return against drawdown.

Marked `*` in the `P` column of the leaderboard.

## Promoting a winner to production

1. Pick a winner from the Stage B leaderboard. Composite = simple; Pareto
   front = visual tradeoff.
2. Compare vs. current live params in `data/sentinel.db`'s
   `dynamic_params` (`sl_atr_multiplier`, `tp_to_sl_ratio`,
   `risk_percent`, and `min_confidence` gate in `ensemble_strategy`).
3. Apply to production DB:
   ```bash
   python -c "from src.core.database import NewsDB; db = NewsDB(); \
       db.set_param('sl_atr_multiplier', 2.0); \
       db.set_param('tp_to_sl_ratio', 2.5); \
       db.set_param('risk_percent', 1.0)"
   ```
4. Update `min_confidence` in the ensemble gate if needed, then restart
   the scanner.

Always run `python verify_install.py` after to catch regressions.

## Safety notes

- Isolation: `src/backtest/isolation.enforce_isolation()` pins
  `DATABASE_URL=data/backtest.db` before any `src.*` import. The
  harness never writes to `data/sentinel.db`.
- Each cell starts with `_reset_backtest_db()` so leaked state from a
  previous cell cannot contaminate the next.
- Resume checks disk, not the DB — deleting a `cell_*.json` forces a
  rerun of just that cell.
- Running alongside the RL sweep: the full grid is CPU-heavy (scanner +
  SMC + ensemble per bar). Prefer waiting for the sweep to finish.
  `--smoke` is safe to run in parallel.

## Estimated wall time

- `--smoke` (3 cells, 3 days): ~2 min
- Stage A (96 cells, 1 window, 7 days): ~1.5 h
- Stage B (top 12, 4 windows × 14 days + MC 500): ~3-5 h
- **Full two-stage (default)**: ~4-6.5 h on a single desktop CPU
