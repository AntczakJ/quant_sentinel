# Operations Playbook

What to do, when to do it, which commands to run, and what to wait for.
Treat this as a decision tree: find the situation matching what you're
seeing, do the step.

---

## 1. Daily check (2 minutes)

Every evening or morning:

```bash
# Is the scanner alive and scanning?
curl -s http://localhost:8000/api/health/scanner | python -m json.tool
```

Expected:
- `scans_total` increasing since yesterday (~96/day on 15-min cadence or ~288/day on 5-min)
- `error_rate` < 0.05
- `last_run_seconds_ago` < 600

If `scans_total: 0` or `last_run_seconds_ago > 900`:
→ **scanner is dead** — restart API (section 9).

Open UI → ModelsPage, look at:
- **Per-Voter Accuracy** widget — any voter < 40%? See section 4.
- **Training Progress Live** widget — any sweep running? Wait or stop.
- **Sweep Leaderboard** — historical record.

---

## 2. "Why zero trades today?"

Check ensemble decision distribution:

```bash
python -c "from src.core.database import NewsDB; from collections import Counter; \
db=NewsDB(); \
rows=db._query(\"SELECT ensemble_signal FROM ml_predictions WHERE timestamp > datetime('now','-12 hours')\"); \
print(Counter(r[0] for r in rows))"
```

Expected output: mix like `{'CZEKAJ': 70, 'LONG': 5, 'SHORT': 3}`.

If **100% CZEKAJ** for 12h+ → ensemble is blocking. Diagnose:

```bash
python tools/voter_weight.py status   # all voters active?

# What's each voter saying on latest signal?
python -c "from src.core.database import NewsDB; import json; \
db=NewsDB(); \
row=db._query_one('SELECT predictions_json FROM ml_predictions ORDER BY id DESC LIMIT 1'); \
data=json.loads(row[0]); \
[print(f'{v:<12} value={info.get(\"value\")} dir={info.get(\"direction\")} status={info.get(\"status\",\"ok\")}') \
 for v, info in data.get('predictions', {}).items()]"
```

Look for an outlier voter disagreeing with majority (`value` far from the others). If found:
```bash
python tools/voter_weight.py defuse <voter> --reason "blocked ensemble 2026-MM-DD"
```

→ scanner picks up new weights in ≤ 5 min (no restart needed).

---

## 3. "Trades are closing — what now?"

After **5+ closed trades** (WIN/LOSS status):

```bash
python tools/voter_forensics.py
```

Reads each trade + matching `ml_predictions`, reports per-voter accuracy.

**Decision tree** based on per-voter accuracy on ≥ 10 votes:

| Voter accuracy | Action |
|---|---|
| ≥ 55% | Healthy. Consider bumping weight by 0.02: `python tools/voter_weight.py set <voter> 0.17` |
| 45% - 55% | Neutral. Leave alone. |
| 35% - 45% | Weak. Watch another 10 trades. Don't act yet. |
| < 35% on ≥ 15 votes | Broken. Defuse: `python tools/voter_weight.py defuse <voter>`. Then retrain (section 5). |

**For DPformer specifically** (currently defused):
- If ensemble-without-dpformer WINS most trades → dpformer was miscalibrated → retrain
- If ensemble-without-dpformer LOSES most trades → dpformer was seeing real risk →
  `python tools/voter_weight.py restore dpformer`

---

## 4. "Voter X accuracy dropped — retrain it"

Depending on voter, use the matching loop. Always back up first:

```bash
cp models/<voter>.keras models/<voter>.pre_retrain.keras
```

| Voter | Script | Typical duration |
|---|---|---|
| lstm | `python retrain_lstm_loop.py --iterations 8 --target 0.55` | 15-25 min |
| attention | `python retrain_attention_loop.py --iterations 5 --target 0.55` | 10-20 min |
| dpformer | `python retrain_dpformer_loop.py --iterations 6 --target-bal 0.52 --max-bias 0.15` | 30-45 min |
| deeptrans | `python retrain_deeptrans_loop.py --iterations 6 --target 0.45` | 20-35 min |

**What to watch for**:
- Loop prints "** new best **" when a candidate passes gates.
- Loop prints `[WARN]` + exits non-zero if no candidate passed — artefact NOT updated.
- On success: writes `models/<voter>.keras` atomically, registers in `models/training_history.jsonl`.

**After retrain finishes**:
1. Smoke-check new voter predicts varied output on live data — check ModelsPage UI or:
   ```bash
   python -c "from src.ml.ensemble_models import predict_lstm_direction; import yfinance as yf, contextlib, io; \
   f=yf.Ticker('GC=F').history(period='1mo',interval='1h').reset_index(); f.columns=[c.lower() for c in f.columns]; \
   import statistics; vals=[predict_lstm_direction(f.iloc[:i]) for i in range(-30,-1,3)]; vals=[v for v in vals if v]; \
   print(f'n={len(vals)} mean={statistics.mean(vals):.3f} stdev={statistics.stdev(vals):.4f}')"
   ```
   Stdev > 0.05 = real signal. Stdev < 0.02 = dead model, rollback.

2. Restore weight if needed:
   ```bash
   python tools/voter_weight.py restore <voter>
   ```

---

## 5. "Sweep something big" (hyperparameter search)

When retrain loop can't find a winner after 2 attempts, escalate to Optuna sweep.

```bash
# LSTM full search (3-5 h):
python tune_lstm.py --n-trials 40 --study-name lstm_sweep_v2 --resume > logs/tune_lstm_v2.log 2>&1 &

# RL sweep (6-12 h; don't run while trading):
python tune_rl.py --n-trials 60 --study-name rl_sweep_v2 --resume > logs/tune_rl_v2.log 2>&1 &
```

**Monitor**:
```bash
python tune_lstm.py --report --study-name lstm_sweep_v2    # leaderboard
cat data/lstm_sweep_heartbeat.json                          # live progress
tail -f logs/tune_lstm_v2.log
```

**After sweep completes** — promote winner if viability gates pass:
```bash
python tune_lstm.py --apply-winner --study-name lstm_sweep_v2
# Check the test_return in output. Auto-promotion only if balanced_acc ≥ 0.52
# AND live_stdev ≥ 0.03. Otherwise production unchanged.
```

---

## 6. "Weekly — Sunday evening before market open"

```bash
# Full retrain of LSTM + XGB + Attention + DPformer + DQN (~45-60 min):
python train_all.py --epochs 50

# Commit fresh artefacts:
git add models/
git commit -m "chore: weekly retrain $(date +%F)"
```

Then restart API to make sure caches are clean.

---

## 7. "Monthly — first Sunday of the month"

Grid backtest to verify production parameters still optimal:

```bash
# 24-cell focused grid, ~7h overnight:
python run_backtest_grid.py --reduced --days 14 --windows 4 --mc 500 > logs/grid_monthly.log 2>&1 &
```

Next morning:

```bash
python run_backtest_grid.py --report --name default_B
```

If winning cell composite score > 10% better than current live params:
- Note winning `min_confidence`, `sl_atr_mult`, `target_rr`
- Apply to `dynamic_params`:
  ```bash
  python -c "from src.core.database import NewsDB; db=NewsDB(); \
  db.set_param('sl_atr_multiplier', 2.0); \
  db.set_param('tp_to_sl_ratio', 2.5)"
  ```
- Scanner picks up on next cycle (no restart).

---

## 8. "Something is broken — rollback"

**Symptoms**: live trades losing streak > 5, P&L dropping fast, voter accuracy collapse.

**Full rollback to 2026-04-13 backup** (last known healthy state):

```bash
# 1. Stop scanner — kill API
taskkill /F /PID <uvicorn pid>
# or on bash: kill $(lsof -ti:8000)

# 2. Code
git reset --hard pre-autonomous-overnight-20260413T013630

# 3. Model files (13 MB snapshot from 2026-04-13 01:36):
cp models/_backup_20260413T013619/*.keras models/
cp models/_backup_20260413T013619/*.onnx models/
cp models/_backup_20260413T013619/*.pkl models/
cp models/_backup_20260413T013619/*.params models/

# 4. DB params (102 keys incl. ensemble weights):
python -c "import json, sqlite3; \
d=json.load(open('models/_backup_20260413T013619/dynamic_params.json'))['dynamic_params']; \
conn=sqlite3.connect('data/sentinel.db'); cur=conn.cursor(); \
[cur.execute('UPDATE dynamic_params SET param_value=?, param_text=NULL WHERE param_name=?', (v, k)) \
 if isinstance(v, (int, float)) \
 else cur.execute('UPDATE dynamic_params SET param_value=NULL, param_text=? WHERE param_name=?', (str(v), k)) \
 for k, v in d.items()]; conn.commit()"

# 5. Restart API
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

**Partial rollback — single voter only**:
```bash
# Restore just LSTM from that backup:
cp models/_backup_20260413T013619/lstm.* models/
python tools/voter_weight.py restore lstm
```

---

## 9. "Restart the API cleanly"

```bash
# Find uvicorn process
powershell -c "Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess"

# Kill it
taskkill /F /PID <that pid>

# Start
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level info
```

Background scanner starts ~45s after API boot.

---

## 10. "Before leaving computer for 8+ hours (sleep/work)"

```bash
# Option A: nothing — just leave API running, trades continue.

# Option B: launch overnight sweep and stop API
taskkill /F /PID <uvicorn pid>
python tune_lstm.py --n-trials 40 --study-name lstm_sweep_$(date +%Y%m%d) --resume \
  > logs/tune_lstm_$(date +%Y%m%d).log 2>&1 &

# Option C: monthly grid backtest
python run_backtest_grid.py --reduced --days 14 --windows 4 --mc 500 \
  > logs/grid_$(date +%Y%m%d).log 2>&1 &
```

---

## 11. "On the schedule — upcoming known dates"

| Date | Event |
|---|---|
| 2026-04-19 | Return checklist review per `memory/return_checklist.md` (data-driven next-step decisions after 1 week live) |
| weekly (Sunday) | `train_all.py --epochs 50` |
| monthly (1st Sunday) | grid backtest + possibly apply winning params |

---

## 12. Triggers — automatic "this happened, do that"

| Trigger | Action |
|---|---|
| Scanner silent for 20+ min | Restart API (section 9) |
| Zero trades for 6+ hours, market open | Section 2 |
| New voter showing flat output (stdev < 0.02 on 10 windows) | Retrain (section 4) |
| Voter accuracy < 35% on 15+ votes | Defuse + retrain (section 4) |
| Voter staleness badge > 14 days in UI | `train_all.py` or targeted `retrain_<voter>_loop.py` |
| Losing streak > 5 trades | Full forensics + consider rollback (section 8) |
| Weekly Sunday | Section 6 |
| Monthly 1st Sunday | Section 7 |

---

## 13. Never do

- Commit `data/sentinel.db` manually mid-session (might race with live scanner writes)
- Kill scanner mid-trade-opening (wait for cycle to complete)
- Promote a voter from training-time `val_acc` alone — always require live_stdev ≥ 0.03
- Remove `models/_backup_*` directories (they're the rollback safety net; gitignored but NEVER delete)
- Set ensemble weight > 0.30 for any voter (breaks the ensemble agreement-based filter)

---

## 14. Contact points in code

- Ensemble fusion logic: `src/ml/ensemble_models.py::get_ensemble_prediction` (line ~549)
- Agreement threshold: `src/ml/ensemble_models.py:931` (hardcoded `< 0.60`)
- Weight loader: `src/ml/ensemble_models.py::_load_dynamic_weights` (line 410)
- Background scanner: `api/main.py::_background_scanner` (line 209)
- Scanner interval: `api/main.py:231` (`_SCAN_INTERVAL_SEC = 300`)
- Kill switches: `risk_killswitch_active`, `trading_paused`, `global_kill_switch` in `dynamic_params` (all NOT_SET = off)
