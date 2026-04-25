# v2 Runbook — How to use the new master plan tooling

**Cel dokumentu:** szybkie reference dla wszystkich nowych skryptów / modułów wprowadzonych 2026-04-25.

---

## 1. Sprawdź gdzie jesteś

```bash
.venv/Scripts/python.exe scripts/status_v2.py
```

Pokazuje:
- Jakie symbole i TFs są w warehouse (last fetch dates)
- Jakie modele v2 są wytrenowane (cv metrics, train date)
- Ile shadow predictions jest zalogowanych
- Sugerowane następne akcje

---

## 2. Refresh data warehouse

```bash
# Pełny fetch — wszystkie symbole, 3 lata, ~13 min
.venv/Scripts/python.exe scripts/data_collection/build_data_warehouse.py --years 3

# Resume (incremental — tylko brakujące dane od last_fetched)
.venv/Scripts/python.exe scripts/data_collection/build_data_warehouse.py --resume

# Tylko jeden symbol/TF
.venv/Scripts/python.exe scripts/data_collection/build_data_warehouse.py --symbols XAU/USD --tfs 5min --years 1
```

**Output:** `data/historical/{symbol}/{interval}.parquet` + `data/historical/manifest.json`

**Rate limit:** 55 calls/min, własny token bucket — bez ryzyka przekroczenia.

---

## 3. Trenuj v2 modele

```bash
# Pełny trening (50 trials Optuna + LSTM, both dirs) — ~2-3h
.venv/Scripts/python.exe scripts/train_v2.py --years 3

# Quick (20 trials + 10 epochs LSTM) — szybka walidacja pipeline ~30 min
.venv/Scripts/python.exe scripts/train_v2.py --quick

# Tylko XGB (skip LSTM) — ~10-20 min
.venv/Scripts/python.exe scripts/train_v2.py --xgb-only

# Tylko jeden kierunek
.venv/Scripts/python.exe scripts/train_v2.py --directions long --xgb-only
```

**Output:** `models/v2/xau_{long,short}_{xgb,lstm}_v2.{json,keras}` + meta JSON

**Co się trenuje:**
- 4 modele: per-direction × per-architecture
- Target: R-multiple regression (continuous, NIE binary 0/1)
- Features: features_v2 (~62 cols, multi-asset + multi-TF)
- CV: TimeSeriesSplit (proper walk-forward)

---

## 4. Sprawdź model behavior

```bash
.venv/Scripts/python.exe scripts/evaluate_v2_models.py --years 1
```

Raport:
- MSE / R² per kierunek na 1y out-of-sample
- Pred mean/std vs actual mean/std (calibration)
- Co model przewiduje przy high-confidence (pred > 0.5R) — czy actual też dobry?
- Top 10 features by importance

---

## 5. Walk-forward backtest

```bash
# Default: train 90d / test 7d / step 7d na okresie 2024-01-01 -> 2026-04-01
.venv/Scripts/python.exe scripts/run_walk_forward.py

# Quick: 30d/7d/14d (dwukrotnie szybsze)
.venv/Scripts/python.exe scripts/run_walk_forward.py --quick

# Custom
.venv/Scripts/python.exe scripts/run_walk_forward.py --start 2025-01-01 --end 2026-04-01 --train 60 --test 7 --step 7
```

**Output:** `docs/walk_forward_results.json` + console summary (WR, PF, DD per window + aggregate)

**UWAGA:** każdy window odpala pełny `run_production_backtest.py` — czyli jeśli jest 100 windows, run zajmie ~100 × 30 min = 50h. Default 7d windows na 2 lata = ~104 windows. Quick mode redukuje przez bigger steps.

W praktyce: zacznij z `--quick`, jeśli wyniki obiecujące → pełen przebieg.

---

## 6. Shadow mode (v2 obok v1)

**Auto-aktywne:** background task `_shadow_scanner` w `api/main.py` startuje przy każdym restarcie API. Dormant dopóki `models/v2/` nie istnieje.

**Co robi:** co 5 min fetch XAU 5min, pred v2 ensemble, log do `data/shadow_predictions.jsonl`. NIE handluje.

**Verify shadow działa:**
```bash
ls data/shadow_predictions.jsonl
tail data/shadow_predictions.jsonl | head -2
```

**Po 2-4 tygodniach shadow data:**
```bash
.venv/Scripts/python.exe scripts/compare_v1_v2_shadow.py
.venv/Scripts/python.exe scripts/compare_v1_v2_shadow.py --horizon-bars 24
.venv/Scripts/python.exe scripts/compare_v1_v2_shadow.py --since 2026-05-01
```

Raport pokazuje:
- Ile predictions, ile actionable (LONG/SHORT vs WAIT)
- Avg realised R, WR, PnL
- Per-direction breakdown
- Statistical significance vs zero (t-test, p-value)

**Decision rule:** rollout v2 → v1 jeśli `p_value < 0.10` ORAZ `avg_realised_r > 0`.

---

## 7. Triple-barrier / R-multiple labels (dla custom training)

```python
from src.learning.labels import triple_barrier_labels, r_multiple_labels

# Triple-barrier: -1/0/1 label
tb = triple_barrier_labels(
    df,                  # OHLCV df with 'atr' column
    direction="long",    # or "short" or "both"
    tp_atr=2.0,         # TP at +2 ATR
    sl_atr=1.0,         # SL at -1 ATR
    max_horizon_bars=48,
)
# tb["label"] -> -1 (SL hit), 0 (timeout), 1 (TP hit)
# tb["bars_to_exit"], tb["exit_price"]

# R-multiple: continuous regression target
rm = r_multiple_labels(df, direction="long", sl_atr=1.0, max_horizon_bars=48)
# rm["r_realized"], rm["r_mfe"] (max favorable), rm["r_mae"] (max adverse)
```

---

## 8. Determinism (PRZED jakimkolwiek backtest experiment)

`run_production_backtest.py` ma teraz seed setup PRZED imports.

**Verify:**
```bash
.venv/Scripts/python.exe -m pytest tests/test_determinism.py -v
```

Powinno przejść 3/3. Jeśli failuje → ktoś usunął/przesunął seed setup.

**Test rzeczywistego determinism:**
```bash
# Run twice
.venv/Scripts/python.exe run_production_backtest.py --reset --days 7 > /tmp/bt1.log 2>&1
.venv/Scripts/python.exe run_production_backtest.py --reset --days 7 > /tmp/bt2.log 2>&1
diff <(grep "FINAL RESULTS" -A 20 /tmp/bt1.log) <(grep "FINAL RESULTS" -A 20 /tmp/bt2.log)
# Empty output = identical results = TRULY deterministic
```

---

## 9. features_v2 (dla v1↔v2 comparison)

```python
from src.analysis.features_v2 import compute_features_v2

# Auto-load cross-asset + higher-TF data from warehouse
features = compute_features_v2(df_xau_5m)

# Or pass explicitly (testing, mock)
features = compute_features_v2(
    df_xau_5m,
    higher_tf_dfs={"1h": df_xau_1h_with_features, "4h": df_xau_4h_with_features},
    cross_asset_dfs={"XAG/USD": df_xag, "TLT": df_tlt, ...},
)
```

**Backwards-compat:** stara `compute_features` z `src.analysis.compute` UNCHANGED. Production v1 nadal używa starej.

---

## 10. Common workflows

### Cotygodniowy refresh (poniedziałek rano)
```bash
.venv/Scripts/python.exe scripts/data_collection/build_data_warehouse.py --resume
.venv/Scripts/python.exe scripts/status_v2.py
```

### Re-train v2 modele (gdy nowe macro features lub większy zbiór)
```bash
.venv/Scripts/python.exe scripts/data_collection/build_data_warehouse.py --resume
.venv/Scripts/python.exe scripts/train_v2.py --years 3  # ~2-3h
.venv/Scripts/python.exe scripts/evaluate_v2_models.py
```

### Pre-rollout decision
```bash
# Sprawdź shadow accumulation
.venv/Scripts/python.exe scripts/status_v2.py

# Compare v1 vs v2 (po 2 tyg shadow data)
.venv/Scripts/python.exe scripts/compare_v1_v2_shadow.py

# Walk-forward jako sanity check
.venv/Scripts/python.exe scripts/run_walk_forward.py --quick

# Decyzja: jeśli oba pokazują v2 > v1 → rollout
```

---

## Troubleshooting

**"Warehouse miss: data/historical/X/Y.parquet"**
- Symbol nie został pobrany. Run `build_data_warehouse.py --symbols X --tfs Y`
- VIX/DXY: TwelveData ich nie ma. Skip lub use VIXY ETF jako proxy.

**"Shadow log not appearing"**
- API musi być restartowany po wytrenowaniu modeli żeby `_shadow_scanner` zauważył pliki w `models/v2/`
- Sprawdź `logs/api.log` na "[Shadow Scanner] starting"

**"Backtest still non-deterministic"**
- Verify `tests/test_determinism.py` passes
- Sprawdź czy nikt nie zmienił `run_production_backtest.py` żeby usunąć/przesunąć seed setup
- Note: `BACKTEST_DISABLE_TRAILING` i `BACKTEST_DISABLE_COOLDOWN` env vars NIE wpływają na determinism

**"Training failed with OOM"**
- LSTM na 161k samples z seq_length=32 zajmuje ~2 GB RAM
- Use `--xgb-only` jeśli RAM constrained
- Lub: `--years 1` (zmniejsza dataset 3x)

**"Optuna hangs"**
- Timeout per trial defaults nie są ustawione
- Jeśli TF infinite-loop: kill proces, restart, set `--quick` żeby zmniejszyć trials
