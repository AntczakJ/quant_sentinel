# Quant Sentinel — Disaster Recovery Runbook

What to do when bad things happen. Companion to `RUNBOOK_RESTART.md`.

## Severity classification

| Level | Symptom | Response time |
|---|---|---|
| **P0** | Live trading offline; broker open positions unmanaged | < 15 min |
| **P1** | Scanner offline but no open positions; data loss; corrupted DB | < 1h |
| **P2** | Backtest stuck; analytics broken; LLM down | < 24h |
| **P3** | Frontend bug; non-trading API endpoint 500 | next session |

## P0 — Live trading offline / broker exposed

### Symptoms
- API process crashed (`ps -ef | grep uvicorn` empty)
- Broker has open position but resolver isn't running
- Streak auto-pause activated and you don't know why

### Response

```bash
# 1. Identify open positions
sqlite3 data/sentinel.db \
  "SELECT id, direction, entry, sl, tp, timestamp FROM trades WHERE status='OPEN'"

# 2. Restart API IMMEDIATELY (if process dead)
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 \
  --log-level info > logs/api.log 2>&1 &

# 3. Wait for resolver startup (~10s)
sleep 10
curl http://127.0.0.1:8000/api/health/deep | jq '.checks.scanner'

# 4. Manually verify broker positions match DB OPEN trades
# (use broker terminal — broker side is source of truth for position existence)

# 5. If positions mismatched: BROKER WINS. Update DB with correct status.
# WARNING: only do this after confirming with the broker that the trade is
# closed/open as you expect.
```

### Streak auto-pause recovery

```bash
# Check pause flag
ls -la data/SCANNER_PAUSED

# Read reason via /api/scanner/status
curl http://127.0.0.1:8000/api/scanner/status

# If reason is acceptable (e.g., 8L streak), wait it out OR resume manually:
rm data/SCANNER_PAUSED

# If you want to investigate first, run trade explainer on recent losses:
.venv/Scripts/python.exe scripts/trade_explainer.py --n 10 --status LOSS
```

## P1 — Data loss / corrupted DB

### Symptoms
- `sqlite3 data/sentinel.db ".schema"` returns errors
- Mass deletion / accidental DROP TABLE
- DB file size suddenly 0 bytes or impossibly small

### Response

```bash
# 1. Stop ALL processes touching the DB
ps -ef | grep -E "uvicorn|run_production_backtest|python.*scripts/" | grep -v grep
# Kill them: kill <PID1> <PID2> ...

# 2. Identify newest valid backup
ls -lt data/backups/*.db | head -5

# 3. Replace corrupt DB with backup
mv data/sentinel.db data/sentinel.db.corrupt.$(date +%Y%m%d_%H%M%S)
cp data/backups/sentinel_<TIMESTAMP>.db data/sentinel.db

# 4. Verify integrity
sqlite3 data/sentinel.db "PRAGMA integrity_check"

# 5. Restart API
.venv/Scripts/python.exe -m uvicorn api.main:app ...

# 6. Reconcile: any trades that closed AFTER backup time — manually backfill
# from broker terminal export.
```

### Backup recency check

Daily backups live in `data/backups/sentinel_<timestamp>.db`. The
`_daily_db_backup` async task creates one per 24h, keeping 14 most
recent. Hourly WAL checkpoint prevents WAL bloat between backups.

If you need MORE granular RPO than 24h, configure backup task cadence
in `api/main.py:_daily_db_backup` (currently `await asyncio.sleep(86400)`).

## P1 — Model files corrupted / mass-deleted

```bash
# 1. Check git-tracked model files
git status models/ | head -20

# 2. If model file (.keras / .onnx / .pkl) deleted: revert from git
git checkout HEAD -- models/<filename>

# 3. If corrupted but in git: same revert. Untracked corruption needs retrain:
.venv/Scripts/python.exe train_all.py --target triple_barrier --target-direction long

# 4. Verify after restart:
.venv/Scripts/python.exe scripts/learning_health_check.py
```

## P2 — Backtest stuck / runaway

### Symptoms
- `run_production_backtest.py` process running > 12h
- Memory growth above 4GB
- Output log file > 1GB

### Response

```bash
# Identify
ps -ef | grep run_production_backtest | grep -v grep
# Note PID + memory (RSS column)

# Kill cleanly
kill <PID>

# If unresponsive:
kill -9 <PID>

# DB integrity (backtest writes to backtest.db only)
sqlite3 data/backtest.db "PRAGMA integrity_check"
```

## Recovery from Turso loss

Per 2026-05-04 audit, Turso has NO local backup (libsql:// URLs are
skipped in `db_backup.py`). If Turso loses our cloud DB:

1. **Local SQLite is primary.** Reads always go to local. Loss of Turso
   = no immediate impact.
2. Set `QUANT_DISABLE_TURSO=1` in .env to stop dual-write.
3. If you need Turso back: re-run `scripts/migrate_to_turso.py --execute`
   to push current local state up.

**Recommendation:** drop Turso entirely (planned for next session).
Local SQLite + WAL + 14-day backup retention is sufficient for
single-PC deployment.

## Recovery from API key compromise

### Symptoms
- Sentry → unexpected calls from unfamiliar IPs
- OpenAI bill spike
- TwelveData credit budget hits 0

### Response

```bash
# 1. Rotate immediately at provider's dashboard:
#    - OpenAI: platform.openai.com/api-keys → revoke + create new
#    - TwelveData: twelvedata.com/account/api-keys
#    - Finnhub: finnhub.io/dashboard/api
#    - Turso: turso.tech/app/databases → revoke token

# 2. Update .env with new key
# CRITICAL: don't commit .env (gitignored already, but verify)

# 3. Update API_SECRET_KEY too if exposed:
# Generate new secret:
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste into .env API_SECRET_KEY=<NEW>
# AND frontend .env.local VITE_API_SECRET_KEY=<NEW>

# 4. Restart API
kill <UVICORN_PID>
.venv/Scripts/python.exe -m uvicorn api.main:app ...

# 5. Verify by checking provider's recent usage logs.
```

## Telegram alerting setup (operator notification)

Sentry → Telegram bridge for level=fatal (shipped 2026-05-04 commit
ae00a52). Verify wired:

```bash
# Trigger test fatal event (in Python REPL on running API):
import sentry_sdk
sentry_sdk.capture_message("DR test fatal", level="fatal")
# Check Telegram inbox; should see "🚨 CRITICAL: DR test fatal"
```

If Telegram bot is dead (per CLAUDE.md "Telegram bot deleted 2026-04-17"
note): create new bot via @BotFather, update TELEGRAM_BOT_TOKEN +
TELEGRAM_CHAT_ID in .env.

## Escalation contacts

(Janek-only single-operator deployment)
- Owner: Janek (tomasz.antczak@dcnart.com)
- Provider escalations: provider's support per service

## Last reviewed
2026-05-04 — initial DR runbook per highend audit.
