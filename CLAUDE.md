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

## Recent state (as of 2026-04-16)
- Grid backtest complete (Stage A+B). **Top configs NOT applied** —
  Sharpe stdev > mean across all top-5, unstable. See
  `memory/grid_backtest_verdict.md`.
- LSTM sweep winner **muted** (weight=0.05, below MIN_ACTIVE_WEIGHT).
  Code-level `LSTM_BULLISH_ONLY` filter as defense-in-depth. Bearish
  predictions 0-14% accuracy, bullish 100% at 1h+ horizons.
  Rollback backup at `models/_backup_20260413T013619/`.
- DQN weight boosted 0.12 → 0.25 (78% live accuracy, 81% bullish).
  DQN+SMC compound signal fires when both agree on direction.
- Scalp-first cascade with time-exit (4h max hold) + pre-weekend
  auto-close (Friday 19:30 UTC). 30m TF producing live trades.
- Telegram bot (`src/main.py`) deleted 2026-04-17. Only API is live.
  Legacy `scan_market_task` / `resolve_trades_task` removed from
  scanner.py. Dual-impl drift risk eliminated.
- Balance milestone alerts: Telegram at ±5%, ±10%, ±20%.
- Voter accuracy tracking: `data/voter_accuracy_log.jsonl` per
  watchdog run. Task Scheduler: daily digest 08:00 + watchdog 6h.

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
  Layout cached in localStorage; bump `LAYOUT_VERSION` in
  `DraggableGrid.tsx` if defaults change.
