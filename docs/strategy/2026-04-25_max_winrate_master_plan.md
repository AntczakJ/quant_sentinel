# Master Plan — Maksymalizacja Win Rate

**Data:** 2026-04-25
**Cel:** zwiększyć WR z aktualnych ~25-46% do **stabilnego 55%+** przy
PF ≥ 1.5, max DD ≤ 10%
**Horyzont:** 4-6 tygodni intensywnej pracy
**Filozofia:** każda zmiana musi przejść overfitting-check
(`memory/feedback_overfitting_check.md`); polegamy na DUŻYCH danych
(2-3 lata, multi-TF, multi-asset), proper walk-forward validation,
i shadow-mode live deployment.

---

## Aktualny stan (Phase 0 — gdzie jesteśmy)

**Liczby (33 closed trades 2026-04-06 → 2026-04-25):**
- WR globalna 46.7% / PF 0.83 / Return -1.08% / DD -4.33% (baseline 30d)
- LONG: WR 22%, -$441 cumulative — strukturalnie zepsute
- SHORT: WR 32%, +$326 cumulative — działa, ale słaby edge
- Każdy faktor scoringu na LONG = negative EV
- ML ensemble: XGB hold-out Sharpe -0.38, LSTM hold-out Sharpe -1.57

**Kluczowe deficyty zdiagnozowane:**
1. **LONG/SHORT asymmetria** — system trenowany na binarnym labelu
   "0.5 ATR move w 5 barach" nie rozróżnia bull-traps od reversji.
2. **Pojedynczy model na cały rynek** — brak rozróżnienia regime
   (trending vs ranging vs squeezing) skutkuje średnią predykcją która
   zawodzi w każdym konkretnym regime.
3. **Słabe labele targetu** — binary 0/1 traci informację o R-multiple.
   Model nie uczy się "duże wygrane vs małe wygrane".
4. **Backtest non-determinizm** — między dwoma backtestami z TYM SAMYM
   kodem ensemble produkował różne sygnały (LONG 384 vs 214). Brak
   deterministycznego stanu modeli przy reload.
5. **Brak proper walk-forward** — train na 2025, test na 2026 to nie
   walk-forward. Powinno być rolling window: train 90 dni → test 7 dni
   → roll forward.
6. **Tylko XAU + USDJPY** — brak intermarket signals (silver, oil,
   S&P, BTC, treasury yields), które dla złota są fundamentalne.

---

## Phase 1 — Data Foundation (1-2 tygodnie)

**Cel:** zebrać 2-3 lata danych across all TFs and intermarket assets,
przechowywać w lokalnej bazie/parquet, eliminować future API calls
podczas iteracji.

### 1.1 Lista assetów (intermarket dla złota)

| Symbol | Source | TFs | Powód |
|--------|--------|-----|-------|
| XAU/USD | TwelveData | 1m, 5m, 15m, 30m, 1h, 4h, 1d | Główny instrument |
| XAG/USD | TwelveData | 5m, 15m, 1h, 1d | Silver — gold cousin (corr 0.85) |
| USDJPY | TwelveData | 5m, 15m, 1h, 1d | USD strength proxy (already used) |
| EURUSD | TwelveData | 5m, 15m, 1h, 1d | Inverse USD proxy |
| DXY (UUP ETF proxy) | TwelveData | 1h, 1d | Dollar index |
| TLT (20y treasury) | TwelveData | 1h, 1d | Real yield proxy (gold inv corr) |
| SPY (S&P) | TwelveData | 1h, 1d | Risk-on/off |
| BTC/USD | TwelveData | 1h, 4h, 1d | Risk asset / safe haven competition |
| WTI oil | TwelveData | 1h, 1d | Inflation/risk |
| VXX (VIX) | TwelveData | 1h, 1d | Risk regime |

### 1.2 Plan zapytań API (rate limit 55/min)

**Budżet zapytań:**
- TwelveData: ~5000 bars/call max (zależy od TF)
- 5m TF * 3 lata = 3 * 365 * 24 * 12 = 315,360 bars → 64 calls
- 1m TF * 1 rok = 1 * 365 * 24 * 60 = 525,600 bars → 106 calls
- 1h TF * 3 lata = 3 * 365 * 24 = 26,280 bars → 6 calls
- 1d TF * 5 lat = 5 * 365 = 1,825 bars → 1 call

**Per-symbol (avg):**
- XAU (najgęstszy): ~180 calls (1m+5m+15m+30m+1h+4h+1d historie)
- Reszta symboli: ~30-60 calls każdy

**Łącznie:** ~600 calls = 11 min przy 55/min

**Pacing strategia:**
```
Każde 1.1s: 1 call
Każda minuta: max 55 calls
Co minutę: 5s buffer cooldown żeby NIE przekroczyć
Total time: 600 / 55 = 10.9 min + buffers = ~13-15 min
```

**Implementacja:**
```python
# scripts/data_collection/fetch_all_history.py
import time
from src.data.twelvedata import fetch_ohlcv

RATE_LIMIT = 55
PER_REQUEST_DELAY = 60.0 / RATE_LIMIT * 1.1  # 1.2s safety margin

def paced_fetch(symbol, interval, start, end):
    time.sleep(PER_REQUEST_DELAY)
    return fetch_ohlcv(symbol, interval, start, end)
```

### 1.3 Storage

**Format:** Parquet + DuckDB index
- `data/historical/{symbol}/{interval}.parquet` — partitioned by month
- `data/historical/manifest.json` — last_fetched timestamps per symbol/TF
- Incremental updates: only fetch since last_fetched

**Korzyści:**
- Backtest czyta z parquet (300x szybciej niż API)
- Nie zżeramy API budgetu na każde re-train
- Reproducibility: każdy backtest dostaje IDENTYCZNE dane

### 1.4 Macro / news data

**FRED (Federal Reserve):** rates, inflation, unemployment — daily
- API: fredapi (już zainstalowane)
- ~10 calls dla całej historii FFR, CPI, UNRATE, GDP, M2

**Forex Factory calendar:** event dates + actual vs forecast
- Scraping JSON endpoint (już mamy mechanizm)
- 1 call/dzień = 365/rok

**Output:** `data/historical/macro_events.parquet` z kolumnami:
`(timestamp, event, country, importance, actual, forecast, previous, surprise_score)`

### 1.5 Deliverable Phase 1

Skrypt `scripts/data_collection/build_data_warehouse.py`:
- Sprawdza manifest, fetch only missing data
- Pacing 55/min
- Resume on failure
- Validation: no gaps, no duplicates, sane OHLC values
- Output report: rows per symbol/TF, date range, data quality score

**Czas:** 3-4 dni development + 1 dzień długiego fetch = 1 tydzień
**Storage:** ~2-5 GB parquet

---

## Phase 2 — Better Labels (1 tydzień)

**Problem:** obecnie `compute_target` używa `>0.5 ATR move w 5 barach`
jako binary target (0/1). To traci informację o magnitude.

### 2.1 Triple-barrier labeling (Lopez de Prado)

**Definicja:** dla każdego baru entry, ustaw 3 bariery:
- TP barrier: entry + (k * ATR)
- SL barrier: entry − (k * ATR)
- Time barrier: entry + N barów (timeout)

**Label:** która bariera trafiona pierwsza:
- 1 = TP hit (winner)
- -1 = SL hit (loser)
- 0 = time hit (neutralne)

**Implementacja:** `src/learning/labels/triple_barrier.py`

**Korzyści:**
- Bezpośrednio aligned z naszym setupem trading'owym (TP/SL system)
- Eliminuje labelowanie "ruch był 0.5 ATR ale potem revertował przed TP"

### 2.2 R-multiple regression target

**Definicja:** `target_R = (max_favorable_excursion - max_adverse_excursion) / atr_at_entry`

**Label:** float — np. +2.5R (wygrał 2.5R), -0.8R (przegrał 0.8R), +0.1R (BE)

**Korzyści:**
- Model uczy się PREDIKOWAĆ ROZMIAR ruchu, nie tylko kierunek
- Pozwala ranking signals: A+ = predicted +2R, B = predicted +0.5R
- Score może być KALIBROWANY: "score 70 → expected +1.5R"

### 2.3 Per-direction labels

**Idea:** osobne labele dla LONG vs SHORT setupów, bo asymetria jest
obserwowana. LONG model uczy się tylko gdy historycznie LONG zrobił sens
(bull regime), SHORT model uczy się tylko na bear/range.

### 2.4 Regime label

**Idea:** classifier wcześniej (Phase 1) regime'u (trending/ranging/squeeze)
generuje label `regime_at_entry`. Każdy entry ma cechę "w jakim regime
byłem" — pozwala modelowi uczyć się różnych zachowań per regime.

### 2.5 Deliverable Phase 2

`src/learning/labels/`:
- `binary.py` (current — keep for back-compat)
- `triple_barrier.py` (new)
- `r_multiple.py` (new)
- `regime_aware.py` (combines triple_barrier + regime tag)

Test: re-label HISTORICAL trades using all three methods, compare label
distributions and predictability scores.

---

## Phase 3 — Better Features (1 tydzień, parallel z Phase 2)

### 3.1 Cross-asset features

Compute na 5m bar level:
- `xag_corr_20`, `xag_ret_5`, `xag_zscore_20` (silver)
- `eurusd_corr_20`, `eurusd_ret_5`
- `tlt_ret_1h`, `tlt_zscore_1h` (treasury — gold inverse correlation)
- `spy_ret_15m`, `spy_zscore_60` (risk-on/off)
- `btc_ret_1h`, `btc_zscore_1h`
- `vxx_level`, `vxx_change_15m` (volatility regime)

**Feature count:** +12 → razem ~48 features

### 3.2 Multi-TF feature cube

**Idea:** dla każdego entry na 5m, dołącz features z wszystkich TFs:
- 5m: aktualne 31 features
- 15m: top 10 features (RSI, MACD, ATR, EMA dist)
- 1h: top 10 features
- 4h: top 5 features (trend, MA position)
- 1d: top 5 features (multi-day trend)

**Total:** ~60 features per entry

**Implementacja:** `src/analysis/multi_tf_features.py`:
```python
def build_multi_tf_input(timestamp, all_tf_dfs):
    features = {}
    for tf, df in all_tf_dfs.items():
        latest = df.loc[df.index <= timestamp].iloc[-1]
        for col in TOP_FEATURES_PER_TF[tf]:
            features[f'{tf}_{col}'] = latest[col]
    return features
```

### 3.3 Sequence features (for LSTM/Transformer)

Zamiast pojedynczego row, model dostaje LAST_N_BARS macierz:
`(64 bars, 31 features) → LSTM/Transformer → prediction`

Pozwala modelowi uczyć się sequencyjnych patternów (np. "RSI wzrasta
przez 10 bars → reversal").

### 3.4 News sentiment context (V2)

**Krótkoterminowo:** sklasyfikuj newsy z calendar:
- `news_in_30min`: bool — czy jest event w następnych 30 min
- `news_tier`: 1/2/3 (NFP/CPI/Fed = 1, PPI/Retail = 2, fed_speak = 3)
- `news_directional_bias`: -1/0/+1 — historyczny bias kierunkowy dla
  tego eventu (np. wyższy CPI → typowo USD up → gold down)

**Długoterminowo:** LLM (Claude API) classification newsów na "bullish gold"
vs "bearish gold". Ale to dopiero V3 (kosztowne, wymagana ostrożność).

### 3.5 Deliverable Phase 3

- `src/analysis/features_v2.py` — pełna nowa `compute_features_v2(...)`
  zwracająca DataFrame z ~60 cechami
- Backwards-compat: stara `compute_features` zostaje (production live)
- Test: feature distributions sane, no NaN, no leakage (current bar
  used only for entry signal, not as feature)

---

## Phase 4 — Model Retraining (1-2 tygodnie)

### 4.1 Per-direction models

**Architektura:**
- `xau_long_xgb_v2.json` — predicts LONG outcome (R-multiple regression)
- `xau_short_xgb_v2.json` — predicts SHORT outcome
- `xau_long_lstm_v2.keras` — same target, sequence input
- `xau_short_lstm_v2.keras` — same

**Training data:** każdy z modeli widzi tylko trade'y w jego kierunku.
Przykład: xau_long_xgb_v2 trenowany na ~5000 LONG triple-barrier samples
z ostatnich 3 lat.

### 4.2 Per-regime models (V2)

**Idea:** w każdym regime osobny model. 4 regimes × 2 directions = 8 modeli.

Trenowane wyłącznie na danych z danego regime'u. Inference: regime
classifier określa aktualny regime → wybiera odpowiedni model.

**Korzyść:** model nie miesza "co działa w trending bull" z "co działa
w squeeze". Cena: mniej danych per model.

**Decyzja:** dopiero gdy total dataset > 20k samples (czyli po 3 latach
data + jeśli skuteczny w iteracji V1).

### 4.3 Transformer / TCN architecture (eksperyment)

**Idea:** Transformer (np. PatchTST, Informer) zamiast LSTM dla sequence.
Lepsze dla long-range dependencies.

**Plan:** PoC na pojedynczym XAU 5m, porównaj z LSTM. Jeśli +5% accuracy
out-of-sample → push do production.

**Risk:** transformery są big — może wymagać chmurowego GPU dla treningu.

### 4.4 Hyperparameter sweep — proper

**Methodology:**
- Optuna z TimeSeriesSplit cross-validation (NIE random KFold!)
- Train: 2023-2024, Val: 2025 (single split)
- Lub: rolling window — train Q1, val Q2, train Q1+Q2, val Q3, etc.
- Metric: Sharpe na out-of-sample backtest, NIE accuracy

**Target hyperparams:**
- XGB: max_depth, n_estimators, learning_rate, subsample, colsample
- LSTM: hidden_units, num_layers, dropout, sequence_length, batch_size
- Decision threshold (prediction confidence cutoff)

**Time:** 200 trials × 5 min/trial = ~17h per model. Run weekend.

### 4.5 DQN retrain z nowym reward

**Aktualnie:** DQN reward = trade PnL. Działa OK (66-80% live accuracy).

**Update:** dodać penalty za:
- Open trade w toxic regime (asian session LONG)
- Open trade po loss streak
- Position w przeciwnym kierunku do main trend HTF

Reward shaping powinien naturalne uniknąć złych setupów.

### 4.6 Ensemble weighting — auto-tune

**Aktualnie:** weights są ustawiane ręcznie + self_learning okresowo
adjustuje. To trochę ad-hoc.

**Update:** weight per voter = ROLLING SHARPE_OF_LAST_50_LIVE_PREDICTIONS.
Voter który zawiódł ostatnio → niska waga. Voter który dobrze trafiał →
wyższa waga. Renormalizuj co 24h.

### 4.7 Deliverable Phase 4

- 4 nowe modele: long/short × xgb/lstm
- Training pipeline `scripts/train_v2.py` z proper CV
- Ensemble weight auto-tune cron-job (daily)
- Validation report: per-direction accuracy, per-regime accuracy,
  Sharpe distribution

---

## Phase 5 — Robust Backtest Infrastructure (1 tydzień)

### 5.1 Walk-forward proper

**Aktualnie:** single 30-day backtest na końcowych danych — to jest
test SET, nie walk-forward.

**Update:** rolling window:
```
Train_start = 2024-01-01
Window_size = 90 dni
Step_size   = 7 dni
For each step:
    train on [train_start, train_start + 90d]
    test on  [train_start + 90d, train_start + 90d + 7d]
    record metrics
    train_start += 7d
```

**Output:** 100+ small backtests covering 2 lata. Statistical significance
of edge.

### 5.2 Per-regime breakdown

Dla każdego backtestu okresu, oznacz dominujący regime:
- WR / PF per regime
- Identify weakest regime → priorytet do fixów

### 5.3 Multi-TF concurrent backtest

**Aktualnie:** scanner skanuje 5m → 15m → 30m → 1h → 4h kolejno, 1
trade na cycle. To OK dla single-strategy.

**Update PoC:** 4 osobne strategie (jedna per TF: 5m, 15m, 1h, 4h),
każda otwiera independent positions, łączą się w portfolio.
Backtest portfolio level (Sharpe, max DD, correlation matrix między
strategiami).

**Decision criterion:** jeśli portfolio Sharpe > best single TF Sharpe
→ deploy multi-TF system.

### 5.4 Deterministic backtest mode

**Problem:** ensemble produkuje różne sygnały między backtestami z tym
samym kodem (LONG 384 vs 214). Zaobserwowane dziś.

**Root cause:** model.predict() używa stochastic dropout? Cache state
TF? Random init w augmentation?

**Fix:** force deterministic mode:
```python
import os, random, numpy as np, tensorflow as tf
os.environ['TF_DETERMINISTIC_OPS'] = '1'
random.seed(42); np.random.seed(42); tf.random.set_seed(42)
```

Plus: w backtest disable any non-deterministic ops (dropout, noise).

### 5.5 Trade replay debugging

**Tool:** `scripts/replay_trade.py {trade_id}` — ładuje historyczny
moment, re-runs cały pipeline (data fetch, features, voting, scoring,
risk), wyświetla każdy decision step.

Pomaga w analizie: "dlaczego ten trade został otwarty? Który voter
zagłosował, jaki był ensemble score, jaki final position size."

### 5.6 Deliverable Phase 5

- `src/backtest/walk_forward.py` — proper rolling validation
- `src/backtest/regime_breakdown.py` — per-regime metrics
- `src/backtest/multi_tf_portfolio.py` — concurrent multi-strategy
- `scripts/replay_trade.py`
- Refactor `run_production_backtest.py` z deterministic seeds

---

## Phase 6 — Live Validation (running parallel z Phase 4-5)

### 6.1 Shadow mode (KRYTYCZNE)

**Idea:** nowy ensemble runs **alongside** production, ale NIE handluje.
Tylko loguje swoje decyzje.

**Implementacja:**
```python
# api/main.py background task
async def shadow_scanner():
    while True:
        signal_v1 = current_ensemble.predict(...)
        signal_v2 = new_ensemble.predict(...)
        log_to('data/shadow_predictions.jsonl', {
            't': now, 'v1': signal_v1, 'v2': signal_v2,
            'price_at_decision': price, 'features': features
        })
```

**Po 2-4 tygodniach:** porównaj v2 vs v1 hypothetical PnL (przy faktycznych
cenach które potem nastąpiły). Jeśli v2 > v1 statystycznie → swap.

### 6.2 Gradual rollout

**Po shadow approval:**
- Tydzień 1: v2 robi 25% trades (random selection)
- Tydzień 2: v2 robi 50%
- Tydzień 3-4: v2 robi 100%

**Kill switch:** jeśli v2 underperformuje vs v1 by > 1% w okresie
tygodnia → revert.

### 6.3 KPI dashboard

Live frontend panel:
- WR rolling 7d / 30d
- PF rolling
- Per-direction WR
- Per-regime WR
- v2 shadow PnL (gdy aktywny)
- Voter contribution heatmap

---

## Phase 7 — Continuous Improvement (ongoing)

### 7.1 Self-learning v2

**Aktualnie:** self_learning.py optymalizuje pojedyncze parametry
(target_rr, sl_atr_multiplier). OK ale ograniczone.

**Update:** Bayesian optimization nad pełnym configspace co 7 dni:
- Wszystkie scoring weights (bos +18, choch +15, etc.)
- Wszystkie thresholds (b_cut, RSI penalty levels)
- Risk parameters
- Constraint: nie zmieniaj > 20% per iteration

### 7.2 Anomaly detection

Daily check:
- Czy WR ostatnich 50 trades < 2σ poniżej średniej historycznej?
- Czy któryś voter > 2σ off od swojego baseline accuracy?
- Czy distribution score'ów setups się przesunęła?

Jeśli yes → alert + auto-pause + trigger investigation.

### 7.3 A/B testing harness

Każda zmiana scoring/risk wchodzi przez A/B:
- Random 50% trades grupa A (current), 50% grupa B (new)
- Po N=100 trades, sprawdź statistical significance
- Jeśli B > A z p<0.05 → migracja

---

## Time / dependency / KPI

### Timeline (4-6 tygodni)

| Tydzień | Phase | Output |
|---------|-------|--------|
| 1 | Phase 1: Data | 2-5 GB parquet, all symbols, all TFs |
| 1-2 | Phase 2: Labels | Triple-barrier + R-multiple labelers |
| 2 | Phase 3: Features | features_v2 z ~60 features |
| 2-3 | Phase 4: Models | 4 modele (long/short × xgb/lstm) |
| 3 | Phase 5: Backtest infra | Walk-forward + per-regime |
| 3-4 | Phase 6: Shadow mode | v2 logging next to v1 |
| 4-5 | Validation | 2-4 tygodnie shadow data |
| 5-6 | Gradual rollout | 25% → 50% → 100% |

### Success criteria (KPI)

**Pre-rollout (backtest walk-forward):**
- WR średnia ≥ 55% (vs current 46.7%)
- PF średnie ≥ 1.5 (vs current 0.83)
- Sharpe ≥ 0.8 (annual)
- Max DD ≤ 10%
- Per-direction: LONG WR ≥ 45%, SHORT WR ≥ 50%
- Per-regime: brak regime z WR < 35%

**Post-rollout (shadow mode 2 tygodnie):**
- v2 hypothetical PnL > v1 actual PnL z p < 0.10
- v2 max DD shadow < 1.5x current actual DD

**Live (po pełnym rollout, 4 tygodnie):**
- WR live ≥ 50% (margin niżej niż backtest, normalne slippage)
- PF live ≥ 1.3
- Brak loss streak > 7 trades w 24h

### Dependencies / blockers

- **Hardware:** GTX 1070 wystarczy dla LSTM/XGB. Transformer może wymagać
  cloud GPU (A100 hourly $1-4) — jeśli zdecydujemy transfer V2.
- **Data quality:** TwelveData może mieć gaps, trzeba validate. Backup
  source: yfinance (już w fallback chain).
- **Compute time:** full Phase 4 retraining + walk-forward ~24h GPU/CPU.
- **Live disruption:** zero, dopóki shadow mode. Production system
  dalej działa.

---

## Co robić w tej kolejności

**Tydzień 1 (najważniejszy):**
1. Phase 1.1-1.5 — data warehouse builder script
2. Run nightly to populate parquet store
3. Phase 5.4 — fix backtest non-determinism (deterministic seeds)

**Tydzień 2:**
1. Phase 2 — implement label functions, re-label historical trades
2. Phase 3 — implement features_v2
3. Phase 5.1 — walk-forward backtest harness

**Tydzień 3:**
1. Phase 4.1-4.4 — train per-direction models z hyperparameter sweep
2. Phase 5.2 — per-regime backtest evaluation
3. Phase 6.1 — shadow mode infrastructure

**Tydzień 4-5:**
1. Phase 6.2 — gradual rollout
2. Phase 7.1 — self-learning v2

**Tydzień 6:**
1. KPI evaluation
2. Decyzja: full rollout vs iterate

---

## Kluczowe overfitting-checks (z `feedback_overfitting_check.md`)

Przed każdą zmianą scoring/threshold/parametru:
1. n trades supporting the rule? n < 30 → soft penalty only
2. Per-direction split? Default to direction-aware
3. Time slicing — multiple weeks/regimes covered?
4. Multiple comparisons discount applied?
5. Reversibility — soft > hard
6. Regime dependence noted?

**Phase 4 modele:** mandatory walk-forward CV (NIE random split). Każdy
hyperparameter tuned na out-of-sample, nie in-sample.

**Phase 6 shadow:** v2 musi pokazać statistically significant improvement
PRZED rollout — p < 0.10 minimum.

---

## Dlaczego to zadziała (hipoteza)

1. **Triple-barrier + R-multiple** — bezpośrednio aligned z trading objective
   (model uczy się TEGO co nas interesuje, nie proxy)
2. **Per-direction modele** — eliminuje LONG/SHORT asymetrię u źródła
   (każdy model uczy się swojego kierunku osobno)
3. **Multi-asset features** — gold to NIE jest izolowany asset, intermarket
   signals są kluczowe (TLT, USDJPY, SPY, BTC wszystkie wpływają)
4. **Walk-forward validation** — eliminuje overfitting który aktualnie
   maskujemy single-window backtestem
5. **Shadow mode** — ostateczna walidacja bez ryzyka kapitału

**Risk:** każdy z tych ulepszeń nie gwarantuje sukcesu. Może się okazać że
złoto w 2026-2027 jest fundamentally tougher (bull blow-off top, choppy
distribution). Dlatego Phase 6 (shadow) jest non-negotiable — jeśli v2
nie poprawia, wracamy do drawing board.

---

## Notes na potem

- `memory/long_short_asymmetry_2026-04-25.md` — punkt startowy dla
  zrozumienia LONG side problem
- `memory/feedback_overfitting_check.md` — mandatory checklist
- `memory/next_session_2026-04-25_priorities.md` — krótkoterminowe
  priorytety przed pełnym wdrożeniem master planu
