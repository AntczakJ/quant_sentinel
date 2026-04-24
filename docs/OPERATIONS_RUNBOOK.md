# Quant Sentinel — Operations Runbook

Common operational tasks for running, maintaining, and debugging the system.
Assumes you're in the repo root (`C:\quant_sentinel`) with `.venv` activated
or using the full path `.venv/Scripts/python.exe`.

---

## Start / restart / stop API

**Start (background, default port 8000):**
```bash
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api.log 2>&1 &
disown
```

**Restart (kill + start):**
```bash
PIDS=$(ps -ef | grep -iE "uvicorn api\.main" | grep -v grep | awk '{print $2}')
for P in $PIDS; do kill -9 "$P" 2>/dev/null; done
sleep 2
.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info > logs/api.log 2>&1 &
disown
```

**Health check:**
```bash
curl -s http://127.0.0.1:8000/health
# Expect: {"status":"healthy","models_loaded":true,"uptime_seconds":...}
```

**Wait for models:**
```bash
until curl -s http://127.0.0.1:8000/health | grep -q '"models_loaded":true'; do sleep 3; done
```

**WARNING**: prefer not to restart while trades are OPEN (CLAUDE.md rule).
Check first:
```bash
curl -s http://127.0.0.1:8000/api/system-health | python -c "import sys,json; print(json.load(sys.stdin)['trades']['open'])"
```

---

## Pause / unpause scanner

**Manual pause** (scanner keeps cycling, skips entries):
```bash
echo "manual pause: $(date -u)" > data/SCANNER_PAUSED
```

**Unpause:**
```bash
rm data/SCANNER_PAUSED
```

**Auto-pause triggers** (implemented 2026-04-22):
- 5 consecutive LOSS within 6h → creates flag automatically + Telegram alert
- Streak with oldest LOSS > 6h is considered "stale" and does NOT trigger
- See `src/trading/scanner.py::_background_scanner` recency gate

**To diagnose auto-pause reason:**
```bash
cat data/SCANNER_PAUSED   # shows trade IDs and age
```

---

## Kelly reset (break feedback loop)

After a contaminated trade history (e.g. streak of losses caused by a
model bug), Kelly sizing can get stuck in low-risk mode indefinitely.
Reset drops old data from Kelly's WR computation:

```bash
.venv/Scripts/python.exe -c "
import sqlite3, datetime
c = sqlite3.connect('data/sentinel.db')
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
c.execute('INSERT OR REPLACE INTO dynamic_params (param_name, param_value, last_updated, param_text) VALUES (?, NULL, ?, ?)',
          ('kelly_reset_ts', now, now))
c.commit()
print(f'Kelly reset to: {now}')
"
```

After reset, Kelly uses `default_risk=1.0%` until KELLY_MIN_TRADES (20)
post-reset trades accumulate. See `src/trading/risk_manager.py::compute_kelly_risk_percent`.

---

## Data resets

**Clear stale `news_sentiment`** (empty if no recent news pipeline output):
```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
c.execute('DELETE FROM news_sentiment')
c.commit()
"
```

**Clear stale `loss_patterns`** (pre-scalp-first era, obsolete):
```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
c.execute('DELETE FROM loss_patterns WHERE last_seen < \"2026-04-15\"')
c.commit()
"
```

**Rebuild `pattern_stats` from trades** (if contaminated by streaks):
```bash
# There is no script yet — this is a todo. Manual SQL:
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
c.execute('DELETE FROM pattern_stats')
# Then aggregate from trades where id > cutoff, grouping by pattern
# TODO: script this as scripts/rebuild_pattern_stats.py
"
```

---

## Retraining

**Full ensemble retrain (skip DQN — healthy):**
```bash
# Backup current models
BACKUP="data/backups/pre_retrain_$(date +%Y%m%d_%H%M)"
mkdir -p "$BACKUP"
cp models/*.keras models/*.pkl "$BACKUP/"

# Train (UTF-8 env is mandatory on Windows, emoji in output otherwise crash)
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe train_all.py \
    --skip-rl --skip-backtest --skip-bayes \
    > logs/retrain_$(date +%Y%m%d).log 2>&1 &
disown
```

**Check progress** (background command logs):
```bash
tail -f logs/retrain_$(date +%Y%m%d).log | grep -E "TRENING|Walk-forward|accuracy|PODSUMOWANIE|Error|Traceback"
```

**After retrain finishes — MUST restart API** (uvicorn holds old models
in memory, new models on disk only take effect post-restart):
```bash
# See "Restart API" above
```

**Rollback** if new models are worse:
```bash
BACKUP=data/backups/pre_retrain_YYYYMMDD_HHMM   # pick latest
cp "$BACKUP"/*.keras "$BACKUP"/*.pkl models/
# Restart API
```

---

## Voter weight tuning

**Read current weights:**
```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
for r in c.execute('SELECT param_name, param_value FROM dynamic_params WHERE param_name LIKE \"ensemble_weight_%\"'):
    print(f'{r[0]}: {r[1]}')
"
```

**Change a weight** (e.g. bump LSTM 0.05 → 0.15 after validating retrain):
```bash
.venv/Scripts/python.exe -c "
import sqlite3, datetime
c = sqlite3.connect('data/sentinel.db')
c.execute('UPDATE dynamic_params SET param_value=?, last_updated=? WHERE param_name=?',
          (0.15, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'ensemble_weight_lstm'))
c.commit()
"
```

Weights take effect on next scanner cycle. No restart required (DB read
per cycle).

---

## Watchdog + voter accuracy tracking

`scripts/voter_watchdog.py` runs every 6h via Task Scheduler. Writes to
`data/voter_accuracy_log.jsonl`.

**Check latest watchdog entry:**
```bash
tail -1 data/voter_accuracy_log.jsonl | python -m json.tool
```

**Status interpretation:**
- `good`: acc ≥55% with bull+bear both reasonable
- `weak`: acc 45-55% or one direction dominant
- `anti_signal`: acc <45% OR bull/bear asymmetry (e.g. bull<35%)
- `insufficient`: n<10 samples

Voter at `anti_signal` for 24+ hours → consider muting (set weight 0.05)
or retraining. LSTM muting happened 2026-04-18 after this exact condition.

---

## Drift alerts

Stored in `model_alerts` table. Schedule gap: **no automation — last
alerts from 2026-04-17**. Current audit workflow:

**Check existing alerts:**
```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
rows = c.execute('SELECT model_name, severity, psi_value, resolved, timestamp FROM model_alerts WHERE resolved = 0 ORDER BY id DESC LIMIT 20').fetchall()
for r in rows: print(r)
"
```

**Resolve stale alert** (after retrain):
```bash
.venv/Scripts/python.exe -c "
import sqlite3
c = sqlite3.connect('data/sentinel.db')
c.execute('UPDATE model_alerts SET resolved = 1 WHERE model_name = ? AND resolved = 0', ('lstm',))
c.commit()
"
```

**Manual drift check** (runs the monitor on-demand):
```bash
curl -s http://127.0.0.1:8000/api/models/monitoring
```

---

## Scanner insight (why no trades?)

**API endpoint:**
```bash
curl -s 'http://127.0.0.1:8000/api/scanner/insight?hours=24' | python -m json.tool
```

**Fields:**
- `rejections.top[]` — which filters blocked how many setups in window
- `toxic_patterns[]` — per-pattern win rate vs block threshold
- `streak.consecutive_losses` vs 5 threshold + oldest age vs 6h recency
- `kelly.post_reset_trades` vs min_sample (20)
- `paused` + `pause_reason`

**Typical interpretations:**
- High `confluence` rejections = market too quiet (missing SMC factors)
- High `toxic_pattern` rejections = known bad-WR pattern being blocked
- High `setup_quality_scalp` rejections = B-grade noise (low factor count)
- High `rsi_extreme` = overbought/oversold, correctly not chasing

---

## Macro context (USDJPY regime)

**API endpoint:**
```bash
curl -s http://127.0.0.1:8000/api/macro/context | python -m json.tool
```

**Fields:**
- `usdjpy_zscore` — USD strength (>+1 = strong → bearish XAU; <-1 = weak → bullish XAU)
- `xau_usdjpy_corr` — regime health (<-0.2 = healthy inverse; >+0.2 = broken)
- `macro_regime` — zielony/czerwony/neutralny (aggregates UUP/TLT/VIXY/USDJPY)
- `market_regime` — squeeze/trending_high_vol/trending_low_vol/ranging (BBW+ADX+ATR)

---

## Frontend dev

**Dev server:**
```bash
cd frontend && npm run dev
# localhost:5173, proxies /api/* to 127.0.0.1:8000
```

**Build production:**
```bash
cd frontend && npm run build
# outputs to frontend/dist/ — served by FastAPI automatically
```

**Layout cache**: layouts stored in localStorage per page. If you bump
default layout in DraggableGrid, increment `LAYOUT_VERSION` to invalidate
users' cached layouts.

---

## Troubleshooting

### API returns 200 but `models_loaded: false`
Models still loading on startup (~30-60s). Wait. If persists:
```bash
grep -E "error|failed|exception" logs/api.log | tail
```

### Scanner runs but 0 trades for days
Check `/api/scanner/insight`. Common causes:
1. Many `toxic_pattern` rejections → pattern_stats contamination; consider
   raising n threshold or wiping stats
2. Many `confluence` rejections → market quiet, genuinely no edge
3. `paused=true` → check pause_reason + address or unpause

### XAU USDJPY fetch fails during training
USDJPY (JPY=X) historical via yfinance is usually reliable. On failure,
training continues with macro features = 0 (see `fetch_usdjpy_aligned`).
Inference also gracefully degrades via `_fetch_live_usdjpy`.

### Keras `.tmp` save error
Fixed 2026-04-24 commit `f4ef78a`. Atomic write path now uses
`.tmp.keras` extension. If you see it again, Keras version likely changed
its validation — check `src/ml/ml_models.py::train_lstm` save path.

### "ONNX DirectML device suspended"
Per `memory/onnx_force_cpu_workaround.md`. Set in `.env`:
```
ONNX_FORCE_CPU=1
```

---

## Commonly read memory files

Check these at session start for quick orientation:
- `memory/MEMORY.md` — index
- `memory/loss_streak_2026-04-22_diagnosis.md` — recent streak findings
- `memory/system_state_2026-04-17.md` — pre-streak baseline
- `docs/research/2026-04-24_SYNTHESIS_audit_report.md` — strategy audit
- `docs/strategy/2026-04-24_new_strategy_plan.md` — roadmap

---

## Emergency stop (live trading halt)

If something is actively bleeding money:

1. **Pause scanner immediately:**
   ```bash
   echo "EMERGENCY: reason" > data/SCANNER_PAUSED
   ```

2. **Halt risk manager** (blocks new trades even outside scanner):
   ```bash
   curl -X POST http://127.0.0.1:8000/api/risk/halt?reason=EMERGENCY
   ```

3. **Close open trades manually** in your broker. System state (broker
   positions) is authoritative — it won't auto-reconcile on scanner restart.

4. **Post-mortem**:
   - Rejection timeline: `/api/scanner/insight?hours=48`
   - Trade detail: `SELECT * FROM trades ORDER BY id DESC LIMIT 20`
   - Voter state at trade time: `ml_predictions` table joined on trade_id
