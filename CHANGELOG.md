# Changelog

All notable changes to Quant Sentinel. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
