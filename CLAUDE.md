# CLAUDE.md — Quant Sentinel

Context for Claude Code sessions working in this repo.

## What this is
Autonomous XAU/USD (gold) trading system. 7-voter ML ensemble + SMC
scanner + live execution via Telegram/FastAPI. Single developer,
single-operator. **Live money at stake** — behavior changes need care.

## Stack
- **Backend:** Python 3.13, FastAPI, Keras/TensorFlow, ONNX Runtime
  DirectML, XGBoost, Numba JIT, SQLite (+ Turso cloud sync)
- **Frontend:** React 18 + TypeScript, Vite, lightweight-charts,
  react-grid-layout (draggable dashboard)
- **Data:** TwelveData primary, yfinance/AlphaVantage fallback,
  FRED/Finnhub for macro
- **Runtime:** Windows 11, GTX 1070 (ONNX DirectML; TF falls back to
  CPU because TF-Windows GPU support dropped after 2.11)

## Process model (IMPORTANT)
**Only ONE process runs live production scanning: the FastAPI `uvicorn`
process.** `_background_scanner` in `api/main.py:206` runs the 5-min
cascade. `src/main.py` is a legacy Telegram bot scheduler — **not
currently wired**. Check `memory/dual_impl_drift_pattern.md` before
touching trading logic.

Start: `.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api.log 2>&1 &`

## Scanner cascade (scalp-first, as of 2026-04-16)
`SCAN_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h"]` (scanner.py:26).
Breaks on first TF with valid setup. Low TFs (5m/15m/30m) have:
- `confluence=1` threshold (vs `3` on H1+)
- `Stable` structure allowed (vs hard-block on H1+)

H1/4h remain strict — require liquidity grab / MSS / DBR-RBD.

HTF trend confirmation at scanner.py:621 — lower TF rejects trades
against explicit HTF trend (neutral HTF = pass).

## Key param storage gotcha
`finance.py:119` reads `tp_to_sl_ratio` from `dynamic_params` for live
sizing. `self_learning.py` optimizes `target_rr` — these must be
mirrored (fix landed 2026-04-16, commit 95569f7). Don't add new
learning targets without same mirror check.

## Backtest isolation
`data/backtest.db` separate from `data/sentinel.db`. `src/backtest/
isolation.py:enforce_isolation()` swaps DATABASE_URL before any
`src.*` import. **Grid and backtest scripts must call
enforce_isolation() FIRST** or they'll write to production DB.

## Recent state (as of 2026-04-26 — sweep + lot-sizing rebuild + frontend v3)

### Tonight's findings + commits (bbf8702, c217ad9, fcc412d)
- **Asymmetry FLIPPED**: with B1-B5 active, LONG is now neutral and SHORT
  bleeds in current XAU bull regime. Old asymmetry memo is stale.
- **B1 softened** −15→−7 (macro+ichi_bull LONG)
- **B4 softened** −25→−10 (asian LONG)
- **B7 added** −20 (SHORT in macro=zielony — symmetric inverse)
- **Per-grade `risk_percent × 1.5/0.7` REMOVED** in finance.py (was inverse-EV)
- **DISABLE_TRAILING env flag** in api/main.py resolver (active in .env)
- **MAX_LOT_CAP=0.01** in .env hard-caps lot until lot rebuild validates
- **Streak threshold 5 → 8** to tolerate normal variance
- **Phase 1 warehouse provider**: `HistoricalProvider.from_warehouse()` reads
  3 years XAU 5m/15m/1h/4h parquet directly, no API calls.
  `run_production_backtest.py --warehouse` flag.
- **Frontend rebuilt from scratch** as v3 (commit fcc412d). Tailwind, Apple/
  Revolut/Outfit aesthetic. Old preserved at `frontend_v1/`.

### Best backtest variant (30-day window)
`flat_risk_combo` (Phase B + DISABLE_TRAILING + MAX_LOT_CAP):
PF **2.14**, return **+7.43%**, max DD **-3.02%**, 54 trades, WR 47%.
First profitable variant.

### Lot-sizing bug (CRITICAL — partial fix tonight)
Backtest revealed lot was inverse-correlated with outcome:
- Winners avg lot 0.026
- Losers avg lot 0.084 (3.2x bigger)
A+ grade `risk_percent × 1.5` bumped lot when setup looked confident, but
those setups lose more often. MAX_LOT_CAP=0.01 + per-grade-mult removal
tonight is the safety net. Full rebuild = next session.

## Pre-2026-04-26 state (as of 2026-04-24 — after loss streak #165-186 audit)

### Live trading defense stack (added 2026-04-22 → 24)
- **Pause flag kill-switch**: create `data/SCANNER_PAUSED` file → BG scanner
  skips cycles without killing API. Delete to resume.
- **Streak auto-pause**: 5 consecutive LOSS within 6h → auto-create pause
  flag + Telegram alert. Stale streaks (oldest > 6h) are ignored.
- **Toxic pattern filter**: queries `pattern_stats` for the real
  `[tf] Trend Bull|Bear + FVG` key. Blocks when `n≥20 AND WR<30%`.
  Currently `[M5] Trend Bull + FVG` at 3W/12L=20% but only n=15 — not
  yet triggering (needs 5 more trades to re-evaluate).
- **B-grade scalp soften**: B (score 25-44) allowed on 5m/15m/30m only
  when `≥5 non-penalty factors AND score ≥35`. Otherwise blocked.
- **SMT magnitude threshold**: USDJPY divergence only fires when
  |10-bar change| ≥ 0.15%. Removes 167×/session noise vetos.
- **Spread-aware vol-spike filter**: block when ATR expansion > 2×
  20-bar baseline (catches unscheduled flash moves; scheduled news
  already handled by event_guard).
- **Tier-aware event guard**:
  - Tier 1 (NFP/CPI/FOMC/PCE) → hard block ±15 min
  - Tier 2 (PPI/ADP/Retail/Jobless/GDP) → halve risk scalp / block HTF ±10 min
  - Tier 3 (Fed speakers, ECB/BoJ) → normal + warning log
- **Kelly feedback break**: `kelly_reset_ts` param in `dynamic_params`;
  Kelly sizing ignores pre-reset trades. When fewer than KELLY_MIN_TRADES
  post-reset, returns default_risk (1.0%) instead of extrapolating from
  contaminated streak.

### Macro feature integration (Phase B — 2026-04-24)
- **ML ensemble now macro-aware**: FEATURE_COLS extended 31→34 with
  `usdjpy_zscore_20`, `usdjpy_ret_5`, `xau_usdjpy_corr_20`.
- `compute_features(df, usdjpy_df=None)` — pass USDJPY alongside XAU for
  inference. Graceful degrade: macro features default to 0 if fetch fails.
- Training pipeline (`train_all.py`) fetches yfinance USDJPY JPY=X
  parallel to XAU, passes to compute_features + all voter training.
- Inference: `ensemble_models._fetch_live_usdjpy()` pulls USD/JPY via
  existing TwelveData provider.
- **No DXY access** — USDJPY is our primary USD-strength proxy. UUP/TLT/
  VIXY polled live for `macro_regime` flag (zielony/czerwony/neutralny)
  but not in ML feature set (TwelveData has no good intraday history
  for them).
- Feature importance post-macro: xau_usdjpy_corr_20 ranks #13/34 (top
  third) in XGB, usdjpy_ret_5 #20, usdjpy_zscore_20 #22.

### Regime classifier (V1 — 2026-04-24)
- `src/analysis/regime.py::classify_regime()` returns one of
  `squeeze | trending_high_vol | trending_low_vol | ranging`
  from BBW compression + ADX + ATR ratio.
- Exposed via `/api/macro/context` and `MacroContext` widget.
- **Not yet routing strategy per-regime** — V1 is classification only.
  Phase V2 will gate voter weighting / MR vs trend-follow per regime.

### Asia Session ORB voter (2026-04-24)
- `src/trading/asia_orb.py::detect_orb_signal()` — marks Asia range
  (00:00-07:00 UTC) and detects break of H/L in first 2h post-London-open
  (07:00-09:00 UTC). Requires 200-EMA HTF filter to agree.
- Wired into `smc_engine.score_setup_quality` as +15 bonus when ORB
  direction matches setup direction (`factors_detail['asia_orb']`).
- Research: +411%/yr backtested on gold futures (TradeThatSwing).

### Dead code cleanup (2026-04-24)
- Regex sentiment (`_detect_sentiment`/`BULLISH_WORDS`) — stubbed to
  return neutral. Research-debunked; will be replaced by LLM-based
  classification in future phase.
- Inert pattern_weight filter (scanner.py:276) — removed. Name mismatch
  made it a no-op.
- dpformer/decompose model — training and inference disabled (weight=0
  already, but training burned 12 min per cycle; suspected data leak at
  78.8% val acc).
- Stale tables wiped: `news_sentiment` (3 rows from 04-16),
  `loss_patterns` (3 rows from 04-09).

### Frontend additions (2026-04-24)
- **ScannerInsight** panel — rejection breakdown, toxic pattern watch,
  streak counter, Kelly state. Answers "why no trades?"
- **MacroContext** strip — USDJPY z-score + XAU-USDJPY correlation +
  macro regime + market regime (BBW/ADX).
- **WeekendBanner** — auto-shows when XAU is closed (Fri 21:00 UTC →
  Sun 21:00 UTC).

### Known strategic gaps (planned)
- Regime-based voter weight routing (Phase V2).
- News calendar: keyword-based tier mapping (OK for V1) but no
  second-rotation trading logic yet.
- VWAP + anchored VWAP family — research-backed edge, not implemented.
- GPR (Geopolitical Risk) index for multi-day bias tilt.
- Models page frontend consolidation — 20+ widgets on one page, ripe
  for tabbed view refactor.

### Earlier context (2026-04-16 baseline, still relevant)
- Grid backtest (Stage A+B) produced 15-decimal-precision Bayesian
  params in `dynamic_params` (min_score, risk_percent, target_rr,
  tp_to_sl_ratio, sl_atr_multiplier). CLAUDE.md flagged "top configs
  NOT applied (Sharpe unstable)" but timestamps show they ARE applied
  — suspect of overfitting; rollback to round numbers deferred until
  after Phase B+C stabilizes (don't rerun grid on broken foundation).
- LSTM sweep winner was muted to 0.05 weight after anti-signal
  detection (bull acc 32%, bear 67%). Retrain 04-22 with macro
  features did NOT flip bull asymmetry in watchdog yet — observe 48h.
- DQN weight 0.25, healthy at 66-80% live accuracy. Only voter not
  retrained today (--skip-rl).
- Scalp-first cascade 5m→15m→30m→1h→4h, time-exit 4h, Fri 19:30 UTC
  pre-weekend close.
- Telegram bot deleted 2026-04-17; only API is live.
- `data/voter_accuracy_log.jsonl` updated by scripts/voter_watchdog.py
  every 6h. model_monitor is NOT scheduled (only runs on-demand via
  /api/models/monitoring endpoint) — known gap.

## Rejection reasons in `rejected_setups` table
`"structure=Stable (no grab/mss)"` (was "chop" — misleading). Stable
means no SMC event this tick, NOT market flat.

## Memory system
`C:\Users\janek\.claude\projects\C--quant-sentinel\memory\` contains
persistent memos. `MEMORY.md` is the index. Always check there before
assuming state.

## Don't
- Restart scanner/API during open trades unless necessary (brief scan
  gap; open positions unaffected — broker-side state).
- Write to `data/sentinel.db` directly from scripts — use NewsDB.
- Add new `dynamic_params` keys without checking who reads them.
  Previous bugs: `target_rr` written, never read by production.
- Commit `.env` or `data/sentinel.db`. `.gitignore` guards both.
  Repo history was cleaned via `git-filter-repo` on 2026-04-15 —
  avoid reintroducing.

## Do
- Use `scripts/apply_grid_winner.py` for param updates (has backup +
  rollback).
- Run `pytest tests/` before committing trading-logic changes.
- Check both `api/main.py` and `src/trading/scanner.py` when changing
  trading behavior — dual-impl risk.
- For UI changes: `cd frontend && npm run dev`, hard-refresh browser.
  Frontend was rebuilt 2026-04-26 (commit fcc412d) — Tailwind + minimalist
  design (Apple/Revolut/Outfit-inspired). Old dashboard preserved at
  `frontend_v1/`. New frontend uses react-query (no Zustand store) and
  has 5 pages: Dashboard, Chart, Trades, Models, Settings.
