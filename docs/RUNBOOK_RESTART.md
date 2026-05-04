# Quant Sentinel — Restart Runbook

Step-by-step procedure for restarting the API + scanner.

## When to restart

- After deploying new scanner / scoring code (commits today like
  `confluence_v2`, IFVG/breaker detectors, V2 regime routing)
- After updating `.env` (new env flags like `QUANT_REGIME_V2=1`)
- After model retrain (`train_all.py`)
- API has been running > 7 days and memory leaks accumulating
- Operator suspects stale state (cache / params)

## Pre-restart checklist

```bash
# 1. Check no open trades
sqlite3 data/sentinel.db "SELECT COUNT(*) FROM trades WHERE status='OPEN'"
# If > 0: WAIT for resolution OR accept brief window where SL/TP hits aren't auto-detected
# (broker still owns the position, won't actually trade — only resolution lag).

# 2. Snapshot DB before restart
cp data/sentinel.db data/backups/sentinel_pre_restart_$(date +%Y%m%d_%H%M%S).db

# 3. Verify backtest process if relevant
ps -ef | grep run_production_backtest | grep -v grep
# Backtest is separate process, restart of API does NOT affect it.

# 4. Smoke test new code in isolation
python -m pytest tests/ -q --tb=line | tail -5
```

## Restart commands

```bash
# Find current API PID
ps -ef | grep "uvicorn api.main" | grep -v grep

# Send SIGTERM (graceful shutdown — 30s drain timeout)
kill <PID>
# Verify it died
ps -ef | grep "uvicorn api.main" | grep -v grep

# Start fresh
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api.log 2>&1 &

# Verify health (give it ~10s for models to load)
sleep 10
curl http://127.0.0.1:8000/api/health
```

## Post-restart verification

```bash
# 1. Health
curl http://127.0.0.1:8000/api/health/deep | jq

# 2. Feature flags (verify env loaded)
curl http://127.0.0.1:8000/api/flags | jq '.session_2026_05_04_flags'

# 3. Watch first scan cycle
tail -f logs/api.log | grep -E "BG Scanner|cycle|Setup Quality"
# Wait until you see "Brak ważnego setupu na żadnym TF" or a trade fires.

# 4. Verify learning state
.venv/Scripts/python.exe scripts/learning_health_check.py | tail -10
# Should report 0 errors.

# 5. Verify trade resolver
sqlite3 data/sentinel.db "SELECT id, status, timestamp FROM trades WHERE status='OPEN'"
# Should match what was open before restart.
```

## Common issues

### Models fail to load
```
[ERROR] Failed to load LSTM: <error>
```
Check `models/feature_cols.json` matches current `FEATURE_COLS` in `src/analysis/compute.py`.
If mismatched after retrain: re-run `train_all.py`.

### Frontend POSTs return 401
Per-2026-05-04 audit: frontend now requires `VITE_API_SECRET_KEY` in
`frontend/.env.local` matching backend `API_SECRET_KEY`.
```bash
cd frontend && cp .env.example .env.local
# Edit .env.local, set VITE_API_SECRET_KEY to value from backend .env
npm run dev
```

### Scanner doesn't fire any trades
Run `python scripts/why_no_trade.py --hours 1` to diagnose.
Check `data/SCANNER_PAUSED` doesn't exist:
```bash
ls data/SCANNER_PAUSED 2>/dev/null && echo "PAUSED — delete to resume"
```

### Stale learning state after retrain
```bash
python scripts/learning_health_check.py
python scripts/walk_forward_validator.py --db both --folds 4
```
If walk-forward alarm fires (-5pp+ drop on recent fold), recent weights
are overfit — revert via `dynamic_params` snapshot or re-run
`run_learning_cycle()` which now includes N<20 safeguard.

## Rollback procedure

```bash
# 1. Stop current API
kill <CURRENT_PID>

# 2. Restore DB snapshot
cp data/backups/sentinel_pre_restart_<TIMESTAMP>.db data/sentinel.db

# 3. Git revert if code change was problematic
git log --oneline -10
git revert <BAD_COMMIT_SHA>

# 4. Restart
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 ...
```

## Restart frequency recommendation

- Daily restart NOT recommended (5 min outage × 365 = 30h/yr lost trading)
- Weekly restart fine (memory cleanup, log rotation)
- Restart after any commit affecting scanner/smc/finance/learning code
- Restart after `.env` change (env vars only loaded at startup)

## Last reviewed
2026-05-04 — added per 6-agent ops audit. Check sticky memo
`session_2026-05-04_full_summary.md` for context.
