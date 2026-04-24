# Quant Sentinel — New Strategy Plan (2026-04-24)

**Cel:** wyjść z 25% WR reżimu, zbudować macro-aware + regime-aware system + clean retraining pipeline. Żyjemy z tym że **nie mamy bezpośredniego dostępu do DXY** — zastępujemy przez UUP ETF + USDJPY.

## Przegląd decyzji (TL;DR)

| Kategoria | Co | Status |
|---|---|---|
| **USUŃ** | Regex sentiment (BULLISH_WORDS), inert pattern_weight filter, stale tables | ✅ SHIPPED `77adadd` |
| **USUŃ** | dpformer voter references, decompose model (leak) | Phase C2 |
| **ZATRZYMAJ** | DQN (zdrowy), SMC scoring core, streak auto-pause, B-soften, SMT magnitude, toxic n≥20, time-exit, RSI extreme, pre-event block | ✅ |
| **DODAJ (CORE)** | Macro features w FEATURE_COLS: UUP + TLT + VIXY + USDJPY + regime flag | Phase B |
| **DODAJ (CORE)** | Regime classifier (BBW + ADX rule-based V1) | Phase B |
| **DODAJ** | Asia Session ORB voter | Phase C |
| **DODAJ** | News calendar API (Finnhub/FF) replacing keyword regex | Phase C |
| **DODAJ** | Second-rotation post-news trading logic | Phase C |
| **DODAJ** | VWAP family (session, anchored) | Phase D |
| **DODAJ** | Spread-aware rejection | Phase D |

---

## 1. Dostępne macro features — REVIZJA

Wcześniejszy audit zakładał "brak macro". Błędnie — mamy:

| Ticker | Rola | Gdzie już się pojawia |
|---|---|---|
| **UUP** (Invesco USD Bull ETF) | DXY proxy (~0.95 correlation z DXY) | `get_macro_regime()` w smc_engine.py |
| **TLT** (iShares 20+Y Treasury) | Inverse 10Y yield proxy | `get_macro_regime()` |
| **VIXY** (ProShares VIX Futures) | Vol/fear proxy | `get_macro_regime()` |
| **USDJPY** | USD proxy + yield proxy (via JP 10Y) | `xau_usdjpy_corr` w feature_engineering.py |

**Problem**: te dane są używane TYLKO przez `macro_regime` flag (zielony/czerwony/neutralny binary) → SMC scoring i finance.py hard block. **ML ensemble (LSTM/XGB/Attention) NIE dostaje tych feature'ów** w training/inference.

**Gap = wąskie gardło.** ML widzi tylko OHLC gold → learns patterns bez macro context → LSTM bull 28% acc live.

---

## 2. Plan implementacji (fazowy)

### Faza A — Cleanup (✅ SHIPPED today 2026-04-24)

Commit `77adadd`:
- Deleted regex sentiment from `news.py` (stub returns neutral/low)
- Removed inert pattern_weight filter at scanner.py:276
- Wiped `news_sentiment` (3 stale rows) + `loss_patterns` (3 stale rows)
- Added `kelly_reset_ts` param → Kelly ignores pre-reset trades → breaks feedback loop
- Defaults to risk=1.0% until n≥20 post-reset trades accumulate

**Impact**: odblokowuje sizing (0.18% → 1.0% default), czyści dead code i statystyki.

### Faza B — Macro feature integration + retrain (CORE, ~1 dzień pracy)

**Krok B1**: Rozszerzyć `compute_features(df, macro_data=None)` w `src/analysis/compute.py`:

```python
def compute_features(df, macro_data=None, use_cache=True):
    # ... existing features ...
    
    # NEW: Macro features (if macro_data provided)
    if macro_data:
        usdjpy_df = macro_data.get('usdjpy')  # 200-bar df matching tf
        uup_price = macro_data.get('uup')     # current quote
        tlt_price = macro_data.get('tlt')
        vixy_price = macro_data.get('vixy')
        
        if usdjpy_df is not None and len(usdjpy_df) >= 20:
            # USD strength Z-score
            uj_close = usdjpy_df['close'].values
            uj_mean = uj_close[-20:].mean()
            uj_std = uj_close[-20:].std()
            df['usdjpy_zscore'] = (uj_close[-1] - uj_mean) / (uj_std + 1e-10)
            # XAU-USDJPY rolling correlation (20-bar)
            df['xau_usdjpy_corr_20'] = df['close'].rolling(20).corr(pd.Series(uj_close, index=df.index[-len(uj_close):]))
            # USDJPY momentum
            df['usdjpy_ret_5'] = pd.Series(uj_close).pct_change(5).iloc[-len(df):].values
    
    # Static macro quotes — constant across the tf window (updated live)
    if uup_price:
        df['uup_zscore'] = _compute_uup_zscore(uup_price)  # vs 100-bar rolling mean
    if tlt_price:
        df['tlt_zscore'] = _compute_tlt_zscore(tlt_price)
    if vixy_price:
        df['vixy_level'] = min(max((vixy_price - 20) / 40, -1), 1)  # normalize 20-60 → -1..1
    
    # Fill with 0 if macro unavailable (graceful degradation)
    for col in ['usdjpy_zscore','xau_usdjpy_corr_20','usdjpy_ret_5','uup_zscore','tlt_zscore','vixy_level']:
        if col not in df.columns:
            df[col] = 0.0
```

**Krok B2**: Rozszerzyć `FEATURE_COLS` o 6 nowych kolumn:
```python
FEATURE_COLS = [
    # ... existing 30 ...
    # MACRO (2026-04-24)
    'usdjpy_zscore', 'xau_usdjpy_corr_20', 'usdjpy_ret_5',
    'uup_zscore', 'tlt_zscore', 'vixy_level',
]
```
→ 36 features total.

**Krok B3**: Update callers:
- `ml_models.py::train_xgb`, `train_lstm` — fetch macro_data before compute_features
- `ensemble_models.py::predict_*` — same
- Cache key includes macro timestamp

**Krok B4**: Retrain pipeline:
```bash
# Backup current models first
mkdir -p data/backups/pre_macro_retrain_$(date +%Y%m%d_%H%M)
cp models/*.keras models/*.pkl data/backups/...

# Retrain with extended features
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe train_all.py \
    --skip-rl --skip-backtest --skip-bayes
```

**Expected**: LSTM bull acc z 28% → 45-55% (gains macro causal anchor), XGB stable ~57%, Attention może wreszcie zacząć fire (n>0).

**Krok B5**: Watchdog validation:
- Obserwuj voter_accuracy_log.jsonl przez 48h
- Bull/bear asymmetry powinna się zmniejszyć
- Jeśli LSTM bull acc ≥45% → bump weight 0.05 → 0.15

### Faza C — Regime classifier + news overhaul (~2-3 dni)

**Krok C1**: Rule-based regime classifier (plik: `src/analysis/regime.py` — nowy):

```python
def classify_regime(df: pd.DataFrame) -> str:
    """Return: 'trending_high_vol' | 'trending_low_vol' | 'ranging' | 'squeeze'"""
    # Indicators
    bb = compute_bollinger_bandwidth(df, 20)  # BBW = (upper-lower)/middle
    bbw_current = bb[-1]
    bbw_ma50 = bb[-50:].mean()
    compression = bbw_current / bbw_ma50  # <0.6 = squeeze, >1.5 = expansion
    
    adx = df['adx'].iloc[-1]  # 0-1 normalized
    atr_ratio = df['atr'].iloc[-1] / df['atr'].iloc[-20:].mean()
    
    if compression < 0.6:
        return 'squeeze'
    if adx > 0.35 and atr_ratio > 1.3:
        return 'trending_high_vol'
    if adx > 0.35 and atr_ratio <= 1.3:
        return 'trending_low_vol'
    return 'ranging'
```

**Użycie**: dodaj jako feature `regime_encoded` (one-hot 4 kolumny) + per-regime gating w scanner:
- `trending_high_vol` → trust trend-follow voters (LSTM, DQN bull signals)
- `trending_low_vol` → trust SMC + retracement plays
- `ranging` → trust MR voters, liquidity sweeps, fade PDH/PDL
- `squeeze` → BLOCK entries (awaiting break)

**Krok C2**: News calendar API (zastąpienie regex):

Plan:
1. Użyj Finnhub API (darmowy tier z economic calendar) — klucz już prawdopodobnie w `.env`
2. Zastąp `get_economic_calendar()` w `news.py` żeby używała real calendar
3. Mapuj eventy → Tier 1 (NFP/CPI/FOMC/PCE) / Tier 2 (PPI/ADP/retail) / Tier 3 (Fed speakers)
4. W scanner `event_guard`:
   - Tier 1: flat ±15 min
   - Tier 2: halve risk ±10 min
   - Tier 3: normal, log ostrzeżenie

**Krok C3**: Second-rotation post-news trading (nowa feature):

```python
# W scanner, after 15 min post-event:
def check_post_news_setup(event_time, tf, analysis):
    minutes_since = (now - event_time).minutes
    if 15 <= minutes_since <= 60:
        # Check: did 15m candle close beyond pre-news range?
        pre_news_range = get_range_before_event(event_time, 60)
        current_15m = get_last_completed_15m_candle()
        if current_15m['close'] > pre_news_range['high']:
            return {'direction': 'LONG', 'confirmation': 'post_news_breakout'}
        if current_15m['close'] < pre_news_range['low']:
            return {'direction': 'SHORT', 'confirmation': 'post_news_breakdown'}
    return None
```

Wymaganie: volume >1.5× 20-bar median dla confirmation.

### Faza D — Advanced edges (~tydzień później, po walidacji C)

- **Asia Session ORB voter** — mark Asia H/L at 07:00 GMT, breakout trigger na London open z 200 EMA trend filter
- **VWAP family** — session VWAP + anchored VWAP (z NFP print, session open). SMC OB/FVG scored tylko gdy w ATR od VWAP
- **Spread-aware rejection** — `current_spread > 1.5 × rolling_20d_median` → skip entry
- **LBMA fix times** (10:30 / 15:00 GMT) — reference levels dla MR plays
- **GPR index** — Geopolitical Risk daily Z-score, bias multi-day

---

## 3. Co ZATRZYMUJEMY (lista)

**Trading logic (keep):**
- Pre-event hard block T-5min / soft halve T-15min (consensus best practice)
- Friday 19:30 UTC pre-weekend close
- Time-exit 4h na scalp (limits exposure)
- HTF trend confirmation (blocks counter-trend)
- Streak auto-pause (5L w 6h) — safety net
- Toxic pattern filter (n≥20)
- RSI extreme hard block (>75/<25)
- B-block softened (5+ factors AND score≥35)
- SMT divergence magnitude threshold (0.15%)

**Voters (keep, adjust):**
- **DQN** (weight 0.25) — single healthy voter, don't touch
- **XGB** (weight 0.20) — retrain z macro, keep
- **LSTM** (weight 0.05) — retrain z macro, bump do 0.15 po validacji

**Infrastructure (keep):**
- `dynamic_params` architecture — good observability
- `pattern_stats` table — good self-learning raw
- `rejected_setups` table — crucial for audit
- Scanner cascade 5m → 15m → 30m → 1h → 4h
- Kelly sizing (z nowym reset)

---

## 4. Co USUWAMY

**✅ Shipped already (commit 77adadd):**
- `BULLISH_WORDS`/`BEARISH_WORDS` regex sentiment — research-debunked
- Inert `pattern_weight` filter — naming mismatch made it a no-op
- `news_sentiment` + `loss_patterns` stale rows

**Phase C2/D cleanup (planned):**
- `decompose` model — 78.8% acc suspicious of leakage, not in ensemble weights, pure maintenance burden
- `dpformer` references — defused 04-13, zero live usage
- Old `loss_pattern_check` logic in self_learning — superseded by toxic_pattern filter
- Bayesian 15-decimal params → rollback do round numbers AFTER Phase B+C stabilizes (rerun grid with stability constraint later)

**Feature candidates to cut** (po Phase B retrain, ocena feature_importance):
- `ichimoku_signal`, `williams_r`, `cci` — often redundant with RSI/MACD/ADX
- Decision: cut if importance <0.01 in retrained XGB

---

## 5. Retraining plan (detailed)

### Dane

**Trening corpus**:
- XAU/USD historical: bierzemy to co już używa train_all.py (TwelveData API, tested up to ~2 miesięcy wstecz)
- **NOWE**: joint fetch USDJPY/UUP/TLT/VIXY aligned na te same timestampy
- Split: 70% train / 15% val / 15% holdout — chronologiczny (nie random!)

**Dane contamination flag**:
- Mark trades #122-186 as "pre-reset cohort" (pre-scalp-first + LSTM anti-signal era)
- Use for training? → TAK dla general pattern learning, ALE:
  - Pattern stats liczymy tylko post-reset
  - WR calculations post-kelly_reset_ts only

### Model-by-model

**XGB (najpierw — najszybciej, <1 min)**:
- Features 30 → 36 (add macro)
- Target: same (next-N-bar direction)
- Walk-forward validation (już jest), ma mieć ≥57% WF acc (baseline new XGB bez macro)
- **Success criterion**: acc ≥60% WF z macro features

**LSTM (drugi, ~10 min)**:
- Same feature expansion
- 50 epochs (current default)
- **Success criterion**: bull acc ≥45% on holdout (was 28% live)
- Jeśli MCC=0 ponownie → degenerate model, rollback do current

**Attention (~10 min)**:
- Same feature expansion
- **Cel**: zacznie fire w live (n>0 w watchdog)

**Decompose**:
- SKIP retrain — to sprawdzimy dopiero po redesigne (78.8% podejrzane o leakage)

**DQN**:
- **NIE trenować** w tej rundzie — zdrowy voter, nie psujemy

### Walidacja

**Post-retrain checklist**:
1. Syntax OK wszystkie pliki (ast.parse)
2. Test predict-single na jednym próbnym bar (assert no nan, output w 0-1)
3. Backup modeli before deployment
4. Restart API, observe 24h watchdog
5. Bull/bear acc asymmetry check → jeśli LSTM dalej ≤35% bull → niepotrzebny weight bump

### Regime-conditional training (future, after single model works)

Później rozważyć oddzielne modele per-regime:
- `lstm_trending.keras` (trained on trending sessions only)
- `lstm_ranging.keras` (trained on ranging only)
- Scanner router wybiera model wg aktualnego regime

**Nie w tej rundzie** — najpierw sprawdźmy czy single model z macro features rozwiązuje problem.

---

## 6. Data reset — executed + plan

### ✅ Już zrobione (Phase A):
- `news_sentiment` — 3 stale rows → 0
- `loss_patterns` — 3 stale rows → 0
- `kelly_reset_ts = 2026-04-24 18:27:04` — Kelly reads only post-reset trades

### Do zrobienia po Phase B retrain:
- `last_backtest_results` param — containsja wyniki ze starego modelu, update po retrain
- `lstm_last_accuracy` / `xgb_last_accuracy` etc. — auto-updated przez train_all.py po retrain
- `pattern_stats` — **rozważ wipe [M5] Trend Bull + FVG** (streak-contaminated). Albo zostaw i czekaj aż n>=20 triggeruje re-check. Obecnie priorytet: niższy, bo toxic_pattern filter z n≥20 już tego pilnuje.

### Consider later:
- `model_alerts` — 53 rows, ostatnie 04-17, model_monitor nie scheduled. Either schedule monitoring OR wipe table. Low priority.
- Bayesian params rollback to round numbers — tylko po Phase B+C, bo rerun grid z nowymi features będzie mieć inny optimum

---

## 7. Learning loop (system uczy się z błędów)

User podkreślił: "**to ma być program który uczy się na błędach i za każdym razem stara się zwiększyć winrate**".

### Obecny learning loop (co jest)
- `update_pattern_weight()` → `pattern_stats` table aktualizuje WR per pattern
- `get_pattern_adjustment()` → używa time-weighted WR (30-day decay)
- `optimize_parameters()` → Bayesian run periodycznie (risk/RR)
- `auto_tune_pattern_weights()` → writes pattern_weight_* do dynamic_params

### Problemy obecnego loopu
1. **Pattern naming mismatch** — scanner używa innego klucza niż trades, więc `get_pattern_adjustment` returns default 1.0 (fix: ujednolicić naming lub zostawić aktywne tylko toxic_pattern)
2. **Nie uczy się REGIME** — pattern_stats są agregatami bez regime breakdown
3. **Bayesian overfit** — 15-decimal precision na małym sample

### Proposed improved loop

**Per-regime pattern stats** (nowe):
```sql
CREATE TABLE pattern_stats_v2 (
    pattern TEXT,
    regime TEXT,  -- 'trending_high_vol' | 'ranging' | ...
    count INT,
    wins INT,
    losses INT,
    win_rate REAL,
    avg_profit REAL,
    last_updated TIMESTAMP,
    PRIMARY KEY (pattern, regime)
);
```

Trade resolver writes regime_at_entry (zaczerpnięte ze snapshot). Self-learner aktualizuje per-pattern+per-regime. `get_pattern_adjustment(pattern, current_regime)` zwraca dynamiczny adjustment.

**Result**: "[M5] Trend Bull + FVG w trending_high_vol" może być 65% WR, w "ranging" 20% WR. Filter blokuje pattern tylko w złym regime.

**Shadow-log evaluation** (pattern już użyty):
- Log każdy odrzucony setup z "what would have happened" (track by MFE/MAE after N bars)
- Po 2 tygodniach: które filtry odrzucały WINNERS? Loosen/remove those.
- CLAUDE.md już wspomina o `directional_alignment` shadow-log (2026-05-04 checkpoint)

**Auto-Bayesian retuning** — tylko po fundamentalnej zmianie systemu (nowe features, nowy regime classifier). Nie częściej niż co 4 tygodnie.

---

## 8. News pipeline — docelowy design

```
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1: EVENT CALENDAR (real-time Finnhub/FF API)                  │
│ ├─ Tier 1 (NFP/CPI/FOMC/PCE): flat ±15min, trade 2nd rotation       │
│ ├─ Tier 2 (PPI/ADP/retail): risk halve ±10min                       │
│ └─ Tier 3 (Fed speakers): normal, log warning                       │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 2: POST-EVENT TRADING LOGIC                                   │
│ ├─ 15m candle close beyond pre-news range required                  │
│ ├─ Volume >1.5× 20-bar median required                              │
│ └─ Sentiment direction aligned with HTF trend required              │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 3: SENTIMENT (LLM-based, replacing regex)                     │
│ ├─ Role: CONDITIONER, not GENERATOR                                 │
│ ├─ Bullish + HTF bull + 15m close above → TP ×1.2                   │
│ └─ Decay: 60-90 min post-release                                    │
├─────────────────────────────────────────────────────────────────────┤
│ LAYER 4: GEOPOLITICAL REGIME (GPR index)                            │
│ ├─ Daily Z-score                                                    │
│ └─ GPR Z >1 → bias long XAU for 1-5 days                            │
└─────────────────────────────────────────────────────────────────────┘
```

**Phase C1 delivers Layer 1+2. Layer 3+4 — Phase D+.**

---

## 9. Success metrics

**Phase B done** (macro features wired + retrained):
- LSTM bull acc >= 40% (z 28%)
- XGB WF acc maintained >= 57%
- Attention fires (n>0 in watchdog)
- No regression w scanner cycle time (<5 sec)

**Phase C done** (regime + news):
- Scanner takes trades in right regime (manual spot check)
- News calendar fires correctly on T-15/T-5
- Second-rotation logic generates at least 1 signal per week

**System healthy** (30-day target):
- WR post-reset >= 45% (na n≥30 trejdów)
- Sharpe post-reset > 0.5
- Max DD on any single day < 3%
- Streak auto-pause fires maksymalnie 1× per month

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Macro features overfit | Walk-forward validation, watch holdout MCC |
| Regime classifier misclassifies → bad routing | Start rule-based (explainable), upgrade to HMM only after baseline |
| News API downtime | Graceful degradation — fall back to current event_guard |
| Retrain makes LSTM worse than current | Keep backup, A/B compare, rollback if LSTM bull < 35% post-retrain |
| Too many changes concurrent → can't attribute wins | **Ship Phase B solo first**, observe 3-5 days. Then Phase C. |

---

## Next action sequence (recommended)

1. **Ship Phase B1-B3** (code changes: compute_features + FEATURE_COLS + callers) — ~2h work
2. **Phase B4 retrain** — 30 min background
3. **Restart API, observe 48h** — watchdog validation
4. **Document Phase B results** — voter accuracy before/after
5. IF Phase B clean → **Phase C1 regime classifier** (2-3 dni)
6. Phase C2 news calendar — parallel to C1
7. Shadow-log everything, assess after 2 weeks

**Nie robimy Phase D** dopóki Phase B+C nie pokażą WR ≥40% stabilnie.
