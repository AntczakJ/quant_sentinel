# Quant Sentinel — Session 2026-05-04 Changelog

**Session length:** ~6 hours of compute, started 2026-05-04 ~09:00 CEDT
**Output:** 33 commits, +900 lines of analytics + tests + fixes
**Tests:** 478 → 510+ passing
**Backtest:** 1-year XAU 5min/15min/30min/1h/4h in flight (PID 7253, 55% complete)

## Real bugs fixed (8)

1. **commit 86ee235** Auth bypasses on `/api/training/`, `/api/portfolio/`, `/api/agent/` POST endpoints — removed from `_PUBLIC_PREFIXES`.
2. **commit 86ee235** Timing-attack vulnerability — `api_key == SECRET` → `secrets.compare_digest`.
3. **commit 86ee235** LLM sentiment cache had no TTL — added 24h TTL.
4. **commit 86ee235** `_streak_pause_check` SQL `ORDER BY id DESC` → `ORDER BY timestamp DESC`.
5. **commit 831cbc5** `regime_adj` was canceling self-learning penalty — capped when `weight<1.0` AND `n_trades>=5`.
6. **commit 009446b** Backtest didn't backfill `setup_grade`/`setup_score` — silent data divergence vs production.
7. **commit 6d0ffb8** Grid optimizer in `run_learning_cycle()` overrode Bayesian when holdout failed → silent overfit.
8. **commit 4c504fc** Same-bar TP+SL priority always picked TP → optimistic backtest. Now uses bar OHLC sequence.
9. **commit 4c504fc** Frontend POST broken since commit 86ee235 (no X-API-Key header) — fixed via `VITE_API_SECRET_KEY`.

## New env-gated features (default OFF, A/B testable)

| Env flag | Purpose | Memory ref |
|---|---|---|
| `QUANT_REGIME_V2=1` | Phase V2 regime routing in scanner | regime_v2_integration_runbook.md |
| `QUANT_BLOCK_CHOCH_OBCOUNT=1` | Toxic pair filter (N=30, WR 16.7%) | toxic_pair_choch_obcount_2026-05-04.md |
| `QUANT_NEWS_LLM=1` (already ON) | gpt-4o-mini news sentiment | session_2026-05-04_continuation.md |
| `ENABLE_GRID=1` | Revive legacy grid optimizer (default off) | session_2026-05-04_full_summary.md |

## New analytics scripts (10)

| Script | Purpose |
|---|---|
| `llm_journal.py` | gpt-4o-mini per-trade post-mortem + theme rollup |
| `factor_predictive_power.py` | Chi-square WR per individual factor |
| `factor_pairs.py` | Pair / triple synergy edges |
| `factor_classifier.py` | ML classifier (LogReg + RandomForest) on factors |
| `factor_classifier_wf.py` | Walk-forward validation (kills random K-fold AUC) |
| `factor_attribution.py` | Dollar P&L per factor (vs WR analysis) |
| `wr_cube.py` | Multidim WR breakdown with Wilson 95% CIs |
| `hourly_heatmap.py` | UTC hour + DoW WR grid |
| `learning_health_check.py` | Bayesian state sanity scanner |
| `why_no_trade.py` | Diagnose "no trades for X hours" |
| `ab_runner.py` | Automated A/B backtest comparison |
| `master_dashboard.py` | Single-command morning report |
| `trade_premortem.py` | LLM predicts before entry (validation: 7.7% acc) |
| `sl_tp_analyzer.py` | SL/TP placement vs outcome |
| `trade_narrative.py` | Chronological equity story (per-week) |

## Memory memos (12 new)

- `session_2026-05-04_full_summary.md` — Master summary
- `audit_2026-05-04_5agent.md` — 5-agent audit, 8 false alarms
- `factor_edge_2026-05-04.md` — bos +21.8pp only significant
- `filter_relaxation_no_go_2026-05-04.md` — overfit traps detected
- `a_plus_grade_bug_2026-05-04.md` — A+ formula scalp threshold 65 too low
- `toxic_pair_choch_obcount_2026-05-04.md` — N=30 WR 16.7%
- `target_rr_finding_2026-05-04.md` — wider TP = more losses
- `ml_classifier_breakthrough_2026-05-04.md` — RF AUC 0.678 → walk-forward 0.452
- `llm_premortem_finding_2026-05-04.md` — 7.7% accuracy = factor model broken
- `regime_v2_integration_runbook.md` — wire-up plan + A/B
- `session_defense_bootstrap_2026-05-04.md` — first 5 trades unfiltered
- `session_2026-05-04_continuation.md` — early session findings

## Scoring/ML wiring shipped

- LLM news sentiment (commit 908212d, 7f1e372) — `gpt-4o-mini` classifies headlines, mapped to {bullish:+1, bearish:-1, neutral:0} signal score.
- SHORT-trained LSTM + Attention (commit 21d4874) — wired as shadow predictors.
- v2 LSTM per-direction (commit 7a9e1d3) — wired as shadow predictor.
- Phase V2 regime routing (commits b86a201, 437b351) — module + 12 tests + scanner integration behind env flag.

## Key data findings

| Finding | Method | N | Confidence |
|---|---|---|---|
| `bos` factor +21.8pp WR | chi-square p=0.051 | 65 | Medium |
| `bos + ob_main` pair edge +$352 | dollar attribution | 69 | Medium |
| Factor combos NO out-of-sample edge | walk-forward AUC 0.452 | 110 | High |
| LLM pre-mortem 7.7% accuracy | actual vs predicted | 13 | Medium |
| London session WR 14.3% | Wilson CI upper 29.7% | 28 | High |
| M15 all directions: 0% WR | Wilson CI upper 24.3% | 12 | Medium |
| B-grade WR 11.1% | Wilson CI upper 32.8% | 18 | Medium |
| `choch + ob_count` toxic pair WR 16.7% | direct count | 30 | Medium |
| WIN avg R:R 2.17, LOSS planned 2.87 | sl_tp_analyzer | 121 | Medium |
| `direction_long` LR coef +0.499 | LogReg controls | 110 | Medium |

## Test coverage delta (estimated)

| File | Before | After | Delta |
|---|---|---|---|
| smc_engine.py | 41% | ~55% | +14pp |
| finance.py | 54% | ~70% | +16pp |
| Phase V2 modules | n/a | 100% | new |

## Pending for next session (when big backtest finishes ~22:00 CEDT)

1. Read `reports/big_backtest_1yr.json` — final PF/WR/MaxDD on 1yr bull regime
2. Re-run `factor_predictive_power.py` on N≈250 (most factor deltas reach p<0.05)
3. Re-run `wr_cube.py` to confirm M15/london/B-grade BLOCK candidates
4. **A/B test queue** (use `ab_runner.py`):
   - `QUANT_REGIME_V2=1` vs unset
   - `QUANT_BLOCK_CHOCH_OBCOUNT=1` vs unset
   - `target_rr` 3.0 → 2.0 for A+ (estimated +5pp WR)
   - A+ scalp threshold 65 → 75
   - session min_trades 5 → 3 (bootstrap leak fix)
5. Restart API to pick up: shadow_short_full + v2_lstm + regime_routing endpoint + frontend X-API-Key
6. Set `VITE_API_SECRET_KEY` in frontend/.env.local

## Don't repeat

- "Find LONG-SHORT asymmetry" agent audits — produces false alarms (math errors).
- Random K-fold CV on time-series — ALWAYS walk-forward.
- Trust LLM premortem output without baseline comparison.
- Treat single-day WIN clusters in rejected_setups as statistical signal.

---

End of changelog. Backtest still running (PID 7253).
