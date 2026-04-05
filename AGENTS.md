# AGENTS.md

## Big picture
- `run.py` is the preferred entrypoint for the Telegram bot workflow: it installs `requirements.txt`, sends a startup Telegram dashboard, then calls `src.main.run_bot()`.
- `src/main.py` is the bot orchestrator. It wires Telegram commands/UI, starts a small Flask webhook on port `5000`, loads `NewsDB`, optionally loads RL, and schedules recurring jobs from `src/scanner.py` plus self-learning.
- `api/main.py` is a separate FastAPI service for the web UI. Routers in `api/routers/*.py` are intentionally thin and delegate to `src/*` modules such as `src.smc_engine`, `src.finance`, `src.data_sources`, and `src.database`.
- `frontend/src/api/client.ts` talks to the FastAPI backend under `/api/*`; the UI is polling-oriented, not true real-time today. `api/websocket/manager.py` exists, but `/ws/prices` and `/ws/signals` currently just keep connections alive with ping broadcasts.

## Data flow and integrations
- Market data flows through `src/data_sources.py` (`get_provider()`), usually Twelve Data with rate limiting + persistent caching; `api/routers/market.py` falls back to stable mock data when the provider is unavailable or rate-limited. Preserve that fallback behavior.
- Trade decisions are layered: SMC analysis in `src/smc_engine.py` -> AI/context assembly in `src/main.py` or `api/routers/analysis.py` -> risk/position sizing in `src/finance.py` -> persistence/stat updates in `src/database.py` and `src/scanner.py`.
- `src/database.py` switches between local SQLite and remote Turso/libsql based on `DATABASE_URL`. The current `.env` uses remote libsql/Turso, so many tests and scripts can mutate a shared database unless you override `DATABASE_URL` locally.
- Secrets live in `.env` and are loaded by `src/config.py`. Never print, copy, or commit `.env` values.

## Developer workflows that are actually useful here
- Install backend deps first; the current workspace interpreter did **not** import `fastapi` successfully until dependencies are installed.
- Prefer running from repo root:
  - API: `python api/main.py` (or `uvicorn api.main:app --reload` if your env already has Uvicorn)
  - Telegram bot + scanner jobs: `python run.py`
  - Quick backend regression: `python tests/run_quick_tests.py`
  - Full Python suite: `python tests/run_all_tests.py`
  - Frontend: `cd frontend && npm install && npm run dev`
  - Frontend checks: `npm run type-check`, `npm run lint`
- Be careful with `start.bat` and `start_backend.bat`: both hardcode `C:\Users\Jan\PycharmProjects\quant_sentinel`, so they are not portable as-is in this workspace.
- Do **not** assume frontend test commands exist just because `frontend/tests/README.md` documents them; `frontend/package.json` currently exposes `dev`, `build`, `preview`, `lint`, `lint:fix`, `type-check`, and `format` only.

## Project-specific coding patterns
- Keep API routers thin and reuse core logic from `src/*` instead of re-implementing trading rules in `api/routers/*`.
- Preserve fallback-first behavior around external APIs. Example: `api/routers/market.py` returns mock candles/ticker data instead of failing hard, and exposes `is_mock` in `/api/market/status`.
- `src/config.py` contains mutable in-memory session state (`USER_PREFS`, `LAST_STATUS`) alongside env config. Changes to `USER_PREFS` are runtime-only; persistent user/trade state belongs in `NewsDB`.
- `NewsDB` performs schema creation/migration/index creation on initialization. Instantiating it has side effects; avoid creating many throwaway instances in loops/tests unless needed.
- The codebase mixes English module names with Polish comments/logs/user-facing messages. Match the surrounding file’s language and tone rather than normalizing everything.
- Frontend state is split deliberately: Zustand in `frontend/src/store/tradingStore.ts` for shared live state, `useCachedFetch` in `frontend/src/hooks/useApiCache.ts` for aggressive TTL caching, and React Query configured in `frontend/src/App.tsx`. Respect existing polling/cache intervals before adding more network traffic.

## When changing behavior
- If you touch signal generation, inspect both `src/main.py` and `src/scanner.py`; bot-triggered analysis and scheduled scanner/resolver logic are related but not identical.
- If you touch portfolio/trade persistence, inspect both `trades` and `scanner_signals` usage in `src/database.py` and API consumers such as `api/routers/analysis.py` and `api/routers/portfolio.py`.
- If you add frontend features, verify the backend route already exists in `api/main.py` and `api/routers/*`, then add the corresponding client wrapper in `frontend/src/api/client.ts`.
- Prefer minimal, surgical edits. This repo has many import-time side effects and external integrations, so small validated changes are safer than wide refactors.



