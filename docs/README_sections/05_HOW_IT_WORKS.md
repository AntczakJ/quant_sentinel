# 🔬 Jak to działa wewnętrznie?

## Architektura systemu

```
┌─────────────────────────────────────────────────────────────┐
│                    QUANT SENTINEL                           │
├─────────────────────────────────────────────────────────────┤
│                    Data Layer                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Twelve Data │  │ OpenAI GPT   │  │  Telegram    │       │
│  │   (OHLCV)   │  │   (Analysis) │  │  (Notifier)  │       │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                │                 │                 │
├─────────┼────────────────┼─────────────────┼─────────────────┤
│         │ Processing Layer │                                 │
│  ┌──────▼───────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  SMC Engine  │  │ ML Predictor │  │   AI Engine     │   │
│  │  (Analysis)  │  │  (XGB,LSTM)  │  │ (GPT-4o)        │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘   │
│         │                │                   │               │
├─────────┼────────────────┼───────────────────┼───────────────┤
│         │ Decision Layer │                   │               │
│  ┌──────▼──────────────────────────────────────┐            │
│  │        Signal Generator & Validator         │            │
│  │  - Pattern stats & filtering                │            │
│  │  - Position sizing & risk management       │            │
│  │  - Confluence scoring                      │            │
│  └──────┬───────────────────────────────────────┘            │
│         │                                                    │
├─────────┼────────────────────────────────────────────────────┤
│         │ Storage & Output                                   │
│  ┌──────▼──────────────────────────────────────┐            │
│  │     SQLite Database (Sentinel.db)          │            │
│  │  - Trades, patterns, stats, loss history  │            │
│  └──────┬──────────────────────────────────────┘            │
│         │                                                    │
│  ┌──────▼──────────────────────────────────────┐            │
│  │    FastAPI Backend + WebSocket              │            │
│  │  - Endpoints dla frontend                  │            │
│  │  - Live updates                            │            │
│  └──────┬──────────────────────────────────────┘            │
│         │                                                    │
│  ┌──────▼──────────────────────────────────────┐            │
│  │    Telegram Bot + React Frontend            │            │
│  │  - User interface                           │            │
│  │  - Signal display                          │            │
│  └──────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

---

## Pobieranie danych (Data Sources)

**Plik:** `src/data_sources.py`

System pobiera dane z **Twelve Data API** dla:
- **XAUUSD** - Cena złota
- **USDJPY** - Proxy dla siły dolara (USD Index)

Asynchroniczna integracja pozwala pobierać dane dla wielu interwałów jednocześnie:
- 5m, 15m, 1h, 4h, 1d

Dane są cachowane przez **60 sekund** (zmniejsza API calls o 73,914x!)

---

## Analiza SMC (Smart Money Concepts)

**Plik:** `src/smc_engine.py`

### Proces analizy

```python
def get_smc_analysis(df_xau, df_dxy, interval, macro_regime):
    """
    Zwraca kompletną analizę SMC dla podanego interwału
    """
    # 1. Identyfikuj swing points
    swing_high = find_swing_high(df_xau, window=5)
    swing_low = find_swing_low(df_xau, window=5)
    
    # 2. Sprawdź Liquidity Grab
    lg_bullish = detect_liquidity_grab_bullish(df_xau)
    lg_bearish = detect_liquidity_grab_bearish(df_xau)
    
    # 3. Market Structure Shift (po Grab)
    mss = detect_mss(df_xau, lg_bullish, lg_bearish)
    
    # 4. Order Block (ostatnia świeca przed zmianą)
    ob = find_order_block(df_xau)
    
    # 5. Fair Value Gap
    fvg = find_fvg(df_xau)
    
    # 6. Formacje DBR/RBD
    dbr_rbd = detect_dbr_rbd(df_xau)
    
    # 7. SMT Divergence (Złoto vs USD/JPY)
    smt_div = detect_smt_divergence(df_xau, df_dxy)
    
    # 8. Zwróć kompletny analysis
    return {
        'swing_high': swing_high,
        'swing_low': swing_low,
        'lg_bullish': lg_bullish,
        'lg_bearish': lg_bearish,
        'mss': mss,
        'ob': ob,
        'fvg': fvg,
        'dbr_rbd': dbr_rbd,
        'smt_div': smt_div,
    }
```

### Caching

Wyniki analizy SMC są cachowane przez 60 sekund - jeśli analizujesz ten sam interwał w ciągu minuty, dostajesz cached wynik bez przeliczania.

---

## Makroekonomiczny filtr

**Plik:** `src/indicators.py` + `src/smc_engine.py`

Automatyczna klasyfikacja reżimu makroekonomicznego:

```python
def get_macro_regime():
    """
    Oblicza reżim makro na podstawie USD/JPY i ATR
    """
    usdjpy_price = get_ticker("USDJPY")
    usdjpy_data = get_candles("USDJPY", "1h", limit=20)
    
    # 1. Oblicz Z-score dla USD/JPY
    usdjpy_zscore = (usdjpy_price - usdjpy_mean) / usdjpy_std
    
    # 2. Oblicz ATR (zmienność)
    atr = calculate_atr(usdjpy_data)
    atr_mean = mean(last_20_atr_values)
    
    # 3. Klasyfikuj
    if usdjpy_zscore < -1 and atr > atr_mean:
        return "GREEN"  # Byczy dla złota
    elif usdjpy_zscore > 1 and atr < atr_mean:
        return "RED"    # Niedźwiedzi dla złota
    else:
        return "NEUTRAL"
```

---

## Modele Machine Learning

**Plik:** `src/ml_models.py`

### 1. XGBoost Classifier

**Architektura:**
- Estymatory: 100
- Max depth: 5
- Learning rate: 0.1
- Funkcja celu: Klasyfikacja kierunku (UP/DOWN)

**Features:**
- RSI, MACD, ATR, Volatility
- Returns (1-day, 5-day)
- EMA positioning
- Green/Red candle indicator

**Output:** Prawdopodobieństwo wzrostu (0-1)

### 2. LSTM Neural Network

**Architektura:**
- Warstwa LSTM 1: 50 neuronów + Dropout 20%
- Warstwa LSTM 2: 50 neuronów + Dropout 20%
- Warstwa Dense: 25 neuronów
- Output Dense: 1 neuron (sigmoid)

**Dane wejściowe:**
- Sekwencje 60 świec z normalizacją MinMax
- Te same features co XGBoost

**Output:** Prawdopodobieństwo wzrostu (0-1)

### 3. Deep Q-Network (DQN) - Reinforcement Learning

**Architektura:**
- Wejście: 22 features (indykatory + state)
- Dense 128 neuronów + ReLU
- Dense 64 neuronów + ReLU
- Output: 3 akcje (BUY, SELL, HOLD)

**State Space:**
- Price, ATR, RSI, MACD, Volume, Trends (M5/H1/H4)
- SMC indicators (Grab, MSS, OB, FVG)
- Macro regime
- Recent rewards

**Action Space:**
- BUY (otwarcie long)
- SELL (otwarcie short)
- HOLD (czekaj)

**Reward Function:**
- +1 za każdy procent zysku
- -1 za każdy procent straty
- -0.5 za nierentowną pozycję

---

## Generowanie sygnału (Signal Generation)

**Plik:** `src/scanner.py` + `src/interface.py`

### Proces step-by-step

```
1. POBIERZ DANE (5m, H1, M5)
   ↓
2. ANALIZA SMC (wszystkie 3 interwały)
   ↓
3. PROGNOZA ML (XGBoost + LSTM + DQN)
   ↓
4. ENSEMBLE VOTING
   - Jeśli 3+ z 3 modeli mówią "UP" → sygnał BUY
   - Jeśli 3+ z 3 modeli mówią "DOWN" → sygnał SELL
   ↓
5. SPRAWDZENIE MAKRO
   - Green regime + BUY? ✅ Zwiększ confidence
   - Red regime + BUY? ⚠️ Zmniejsz confidence
   ↓
6. SPRAWDZENIE WZORCA
   - Czy ten wzorzec ma win_rate > 33%?
   - Jeśli nie → ODRZUĆ sygnał
   ↓
7. OCENA AI (GPT-4o)
   - Przekaż wszystkie dane do AI
   - AI wystawia ocenę 0-10 z uzasadnieniem
   ↓
8. JEŚLI OCENA AI ≥ 5:
   - Oblicz POSITION SIZING
   - ZAPISZ do bazy
   - WYŚLIJ powiadomienie (jeśli ≥ 8)
```

### Position Sizing

```python
def calculate_position(entry, sl, capital, risk_percent=1.0):
    """
    Reguła 1% - ryzyko na 1 transakcję nie przekroczy 1% kapitału
    """
    risk_usd = capital * (risk_percent / 100)
    distance_usd = abs(entry - sl) * 100  # cena * 100 (lot size)
    lot = risk_usd / distance_usd
    
    # Ograniczenia
    lot = max(0.01, min(lot, 10.0))
    
    # Oblicz TP (minimum 2x risk/reward)
    min_tp_distance = distance_usd * 2
    tp = entry + min_tp_distance / 100 if direction == "LONG" else entry - min_tp_distance / 100
    
    return {
        'lot': lot,
        'entry': entry,
        'sl': sl,
        'tp': tp
    }
```

---

## Samouczenie (Self-Learning)

**Plik:** `src/self_learning.py`

### Pattern Statistics

```python
def update_pattern_stats(pattern_name, outcome):
    """
    Aktualizuj win/loss rate dla wzorca
    """
    pattern = get_pattern_stats(pattern_name)
    
    if outcome == "WIN":
        pattern['wins'] += 1
    else:
        pattern['losses'] += 1
    
    pattern['win_rate'] = pattern['wins'] / (pattern['wins'] + pattern['losses'])
    
    # Blokowanie słabych wzorców
    pattern_weight = pattern['win_rate'] * 1.5
    pattern['is_active'] = pattern_weight > 0.5
    
    save_pattern_stats(pattern)
```

### Dynamic Parameter Optimization

Co godzinę bot analizuje ostatnie 100 transakcji i optymalizuje:

```python
def optimize_parameters():
    """
    Bayesian optimization dla risk_percent, min_profit_usd, min_tp_distance_mult
    """
    last_100_trades = get_last_trades(limit=100)
    
    # Dla każdej kombinacji parametrów:
    for risk_percent in [0.5, 1.0, 1.5]:
        for min_profit in [50, 100, 150]:
            for tp_mult in [1.5, 2.0, 2.5]:
                # Backtest tymi parametrami na ostatnich 100 trades
                results = backtest_with_params(
                    trades=last_100_trades,
                    risk_percent=risk_percent,
                    min_profit=min_profit,
                    tp_mult=tp_mult
                )
                
                # Zapisz best params
                if results['sharpe_ratio'] > best_sharpe:
                    best_sharpe = results['sharpe_ratio']
                    best_params = (risk_percent, min_profit, tp_mult)
    
    # Aktywuj best params
    save_best_parameters(best_params)
```

---

## Automatyczne zadania (Job Queue)

Bot uruchamia 4 zadania na stałe:

| Zadanie | Częstotliwość | Opis |
|---------|---------------|------|
| **Scanner** | co 5 minut | Sprawdza zmiany trendu, nowe FVG, Grab, DBR/RBD |
| **Resolver** | co 2 minuty | Sprawdza otwarte pozycje, aktualizuje status |
| **Auto-Learn** | co 15 minut | Generuje sygnał, zapisuje do bazy |
| **Optymizacja** | co godzinę | Optymalizuje parametry na ostatnich 100 trades |

---

## Przechowywanie danych (Database Schema)

**Plik:** `src/database.py`

```sql
-- Sygnały ze skanera
CREATE TABLE scanner_signals (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    direction TEXT,
    confidence REAL,
    pattern TEXT,
    macro_regime TEXT
);

-- Transakcje
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    direction TEXT,
    entry REAL,
    sl REAL,
    tp REAL,
    lot REAL,
    status TEXT,
    profit REAL,
    pattern TEXT
);

-- Statystyki wzorców
CREATE TABLE pattern_stats (
    pattern TEXT PRIMARY KEY,
    wins INTEGER,
    losses INTEGER,
    win_rate REAL,
    is_active BOOLEAN
);

-- Historia strat (do AI feedback)
CREATE TABLE loss_history (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    pattern TEXT,
    reason TEXT,
    market_condition TEXT
);

-- Parametry systemu
CREATE TABLE parameters (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME
);
```

---

## Przepływ danych - kompleksowy przykład

```
[14:00] Bot uruchamiany
  ↓
[14:05] SCANNER runs
  - Pobiera dane XAUUSD 5m, H1, M5
  - Analiza SMC → Liquidity Grab (bullish)
  - Sprawdza makro → GREEN
  - Zapisuje do DB: "LG+MSS bullish, confidence=75%"
  ↓
[14:15] AUTO-LEARN runs (co 15 min)
  - Bierze ostatni sygnał ze scannera
  - XGBoost: 0.72 (UP)
  - LSTM: 0.65 (UP)
  - DQN: BUY
  - Ensemble: BUY (3/3) ✅
  - AI analysis → 8/10
  - Oblicza pozycję: lot=0.12, entry=2325.00, SL=2323.00, TP=2330.00
  - Zapisuje do DB
  - Wysyła alert na Telegram ✅
  ↓
[14:20] Użytkownik wchodzi na pozycję
  ↓
[14:22] RESOLVER runs
  - Sprawdza: czy price hit TP lub SL?
  - Nie, price=2328.00 (profit: $120)
  - Aktualizuje status trade'a
  ↓
[14:25] Price spadła do 2323.00 (SL)
  ↓
[14:26] RESOLVER runs
  - Wykrył SL hit
  - Zamyka pozycję: status=LOSS, profit=-60
  - Analizuje warunki: "RSI było 58, struktura złamana, makro zmienił się"
  - Zapisuje do loss_history (dla AI feedback)
  - Aktualizuje pattern_stats: "LG+MSS bullish" - loss #2
  - win_rate zmienia się: 1W/2L = 33% (na krawędzi blokady!)
  ↓
[15:00] OPTIMIZATION runs
  - Analizuje ostatnie 100 trades
  - Znajduje: risk_percent=0.8% daje +17% Sharpe ratio vs 1%
  - Zmienia parametr systemu
  ↓
[15:05] SCANNER runs (następny cykl)
  - Nowy sygnał pojawia się z optymalizowanymi parametrami...
```

---

## Performance

- **SMC Analysis:** <50ms (cached)
- **ML Prediction:** <200ms
- **AI Analysis:** <2s
- **Database Query:** <10ms
- **Total Signal Generation:** <3s
- **WebSocket Latency:** <100ms

---

## Co dalej?

- 🧪 [Testing i Development](06_ADVANCED.md)
- 📘 [API Reference](04_API_REFERENCE.md)
- 🚀 [Szybki Start](03_QUICKSTART.md)

