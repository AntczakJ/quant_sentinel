# 🤖 ML Ensemble Integration - Dokumentacja

## Przegląd

System został zintegrowany z **3 modelami ML** i **ensemble voting system**, które teraz biorą aktywny udział w podejmowaniu decyzji handlowych.

### Modele ML:
1. **LSTM** - Predykcja kierunku (0-1 skala)
2. **XGBoost** - Predykcja kierunku (0-1 skala)  
3. **DQN Agent** - Rekomendacja akcji (0=hold, 1=buy, 2=sell)

---

## 🏗️ Architektura Integracji

### Flow Pipeline:

```
┌─────────────────────────────────────────────────────────────┐
│ 1. API: GET /analysis/quant-pro                            │
│    - Pobiera dane SMC                                       │
│    - Pobiera AI assessment (GPT-4o)                        │
│    - Pobiera OHLCV candles (200 świec)                     │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────────┐
│ 2. ensemble_models.py: get_ensemble_prediction()           │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐ │
│   │ Predykcje z modeli:                                  │ │
│   ├──────────────────────────────────────────────────────┤ │
│   │ ✓ predict_lstm_direction(df) → 0.0-1.0              │ │
│   │ ✓ predict_xgb_direction(df) → 0.0-1.0               │ │
│   │ ✓ predict_dqn_action(prices, balance) → 0,1,2       │ │
│   └──────────────────────────────────────────────────────┘ │
│                                                              │
│   ┌──────────────────────────────────────────────────────┐ │
│   │ Fuzja (Voting):                                      │ │
│   │ SMC: 35% | LSTM: 25% | XGBoost: 20% | DQN: 20%    │ │
│   └──────────────────────────────────────────────────────┘ │
│                                                              │
│   Output:                                                    │
│   - final_score: 0.0-1.0                                   │
│   - ensemble_signal: LONG | SHORT | CZEKAJ                │
│   - confidence: 0.0-1.0                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────────┐
│ 3. finance.py: calculate_position()                         │
│                                                              │
│   ✓ Weryfikuje SMC sygnał przez ML ensemble               │
│   ✓ Jeśli konflikt: loguje warning                         │
│   ✓ Jeśli niska pewność: zwraca CZEKAJ                    │
│   ✓ Oblicza lot size, SL, TP                              │
│   ✓ Zwraca ensemble_data w odpowiedzi                     │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────────┐
│ 4. API Response                                             │
│                                                              │
│ {                                                            │
│   "smc_analysis": {...},                                    │
│   "ai_assessment": "...",                                   │
│   "position": {                                             │
│     "direction": "LONG",                                    │
│     "entry": 2050.5,                                        │
│     "stop_loss": 2048.5,                                    │
│     "take_profit": 2055.0,                                  │
│     "lot_size": 0.1                                         │
│   },                                                         │
│   "ml_ensemble": {                                          │
│     "signal": "LONG",                                       │
│     "final_score": 0.742,                                   │
│     "confidence": 0.65,                                     │
│     "models_available": 3,                                  │
│     "predictions": {                                        │
│       "smc": {"direction": "LONG", "confidence": 0.80},    │
│       "lstm": {"direction": "LONG", "confidence": 0.72},   │
│       "xgb": {"direction": "SHORT", "confidence": 0.55},   │
│       "dqn": {"direction": "LONG", "confidence": 0.70}     │
│     }                                                        │
│   }                                                          │
│ }                                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 📡 Nowe API Endpoints

### 1. `/analysis/quant-pro` (zmodyfikowany)
```bash
GET /analysis/quant-pro?tf=15m
```

**Nowe pola w response:**
```json
{
  "ml_ensemble": {
    "signal": "LONG|SHORT|CZEKAJ",
    "final_score": 0.0-1.0,
    "confidence": 0.0-1.0,
    "models_available": 1-4,
    "predictions": {
      "smc": {...},
      "lstm": {...},
      "xgb": {...},
      "dqn": {...}
    }
  }
}
```

### 2. `/analysis/ml-ensemble` (NOWY)
```bash
GET /analysis/ml-ensemble?tf=15m
```

**Response:**
```json
{
  "timestamp": "2026-04-04T...",
  "timeframe": "15m",
  "current_price": 2050.5,
  "ensemble_signal": "LONG|SHORT|CZEKAJ",
  "final_score": 0.742,
  "confidence": 0.65,
  "models_available": 3,
  "individual_predictions": {
    "smc": {"direction": "LONG", "confidence": 0.80, "value": 1.0},
    "lstm": {"direction": "LONG", "confidence": 0.72, "value": 0.72},
    "xgb": {"direction": "SHORT", "confidence": 0.55, "value": 0.45},
    "dqn": {"direction": "LONG", "confidence": 0.70, "value": 0.8}
  },
  "weights": {
    "smc": 0.35,
    "lstm": 0.25,
    "xgb": 0.20,
    "dqn": 0.20
  }
}
```

---

## 🔧 Konfiguracja Wag

**Domyślne wagi** w `ensemble_models.py`:

```python
weights = {
    "smc": 0.35,      # SMC Engine - podstawowa analiza techniczna
    "lstm": 0.25,     # LSTM - rozpoznawanie wzorców
    "xgb": 0.20,      # XGBoost - klasyfikacja
    "dqn": 0.20       # DQN - strategic decision making
}
```

**Aby zmienić wagi**, zmodyfikuj w `calculate_position()`:

```python
ensemble_result = get_ensemble_prediction(
    df=df,
    smc_trend=trend,
    current_price=price,
    balance=balance,
    initial_balance=initial_balance,
    position=0,
    weights={  # ← Tutaj
        "smc": 0.40,
        "lstm": 0.25,
        "xgb": 0.15,
        "dqn": 0.20
    }
)
```

---

## 📊 Logika Fuzji

### Konwersja predykcji na skalę 0-1:

**SMC:**
- Bull → 1.0
- Bear → 0.0

**LSTM/XGBoost:**
- Prognoza > 0.5 → kierunek LONG, wartość = prognoza
- Prognoza < 0.5 → kierunek SHORT, wartość = prognoza

**DQN (akcje):**
- 0 (hold) → 0.5
- 1 (buy) → 0.8
- 2 (sell) → 0.2

### Wyliczenie final_score:

```
final_score = Σ(model_value × model_weight) / Σ(weights)
```

### Interpretacja:

- **score > 0.65** → LONG signal (pewność: confidence%)
- **score < 0.35** → SHORT signal (pewność: confidence%)
- **0.35-0.65** → CZEKAJ (neutralna strefa)

### Filtr pewności:

- **confidence < 0.4** → CZEKAJ (zbyt mało pewności, czekamy na wyraźniejszy sygnał)
- **confidence ≥ 0.4** → Możemy otworzyć pozycję

---

## 🚨 Validacja i Filtry

### 1. Konflikt SMC vs ML

Jeśli SMC mówi LONG ale ML mówi SHORT:
```
⚠️ SMC (LONG) vs ML (SHORT) KONFLIKT
```

Logika:
- Jeśli ML ma confidence > 70%: log warning
- Position nadal otwierany wg SMC, ale z notatką

### 2. Niska pewność ensemble

Jeśli `confidence < 40%` i `ml_signal == CZEKAJ`:
```json
{
  "direction": "CZEKAJ",
  "reason": "Niska pewność ensemble (25%) - czekamy na wyraźniejszy sygnał"
}
```

### 3. Niewystarczające dane

Jeśli danych < 60 świec (dla LSTM):
```
Model LSTM: unavailable (za mało danych)
```

System automatycznie pada na pozostałe modele.

---

## 🧠 Logika Modeli

### LSTM
- Bierze ostatnie 60 świec
- 8 cech technicznych (RSI, MACD, ATR, volatility, returns, itp)
- Normalizacja MinMaxScaler
- Output: prawdopodobieństwo wzrostu (0-1)

### XGBoost
- Bierze ostatnie 100 świec
- 8 cech technicznych
- 100 drzew decyzyjnych (n_estimators=100)
- Output: prawdopodobieństwo wzrostu (0-1)

### DQN Agent
- Reinforcement Learning (Q-Learning)
- State: [ostatnie 20 cen] + [balance] + [position]
- Akcje: 0=hold, 1=buy, 2=sell
- Output: najlepsza akcja (0, 1, lub 2)

---

## 💾 Ładowanie Modeli (Lazy Loading)

Modele ładują się **tylko przy pierwszym użyciu** i cachują się w pamięci:

```python
_models_cache = {
    "lstm": None,
    "xgb": None,
    "dqn": None
}
```

**Ścieżki modeli:**
- `models/lstm.keras`
- `models/xgb.pkl`
- `models/rl_agent.keras`

Jeśli model nie istnieje → fallback (vraca None) → system używa pozostałych.

---

## 📝 Logging

Wszystkie decyzje logują się z tagiem:

```
✅ LSTM model loaded
✅ XGBoost model loaded
✅ DQN Agent loaded
🤖 Ensemble: 3 modele | Score: 0.742 | Confidence: 65% | Signal: LONG
⚠️ SMC (LONG) vs ML (SHORT) KONFLIKT
💡 ML ma wysoką pewność (80%) dla LONG, ale SMC mówi SHORT
```

---

## 🔄 Scanner Integration

Scanner (`scanner.py`) teraz:
1. Pobiera sygnały SMC
2. Uruchamia ML ensemble validation
3. Loguje ML confidence jeśli > 70%
4. Wysyła alerty z notatkami o ML

---

## 📈 Monitoring Performansu

Aby śledzić performance ensemble, sprawdź logi:

```bash
tail -f logs/sentinel.log | grep -E "Ensemble|ML|confidence"
```

---

## 🔮 Przyszłe Rozszerzenia

1. **Online Learning**: Model uczy się z każdej transakcji
2. **Confidence Thresholds**: Dynamiczne progi pewności
3. **Model Retraining**: Automatyczne retrening gdy accuracy spada
4. **Backtesting**: Historyczna walidacja performance
5. **A/B Testing**: Testowanie różnych wag

---

## ⚠️ Troubleshooting

### Problem: Model nie ładuje się
**Rozwiązanie**: Sprawdź czy plik istnieje w `models/`:
```bash
ls -la models/
```

### Problem: Zbyt dużo CZEKAJ sygnałów
**Rozwiązanie**: Zmniejsz wagi na pewności lub dostosuj progi:
```python
# W get_ensemble_prediction():
if results["confidence"] < 0.3:  # Było 0.4
    results["ensemble_signal"] = "CZEKAJ"
```

### Problem: ML i SMC się nie zgadzają
**Rozwiązanie**: To NORMALNE. Log zawiera porównanie. Jeśli ML ma wysoką pewność i SMC się myli, system to zaloguje jako `⚠️ KONFLIKT`.

---

## 📞 Support

Wszystkie błędy logują się z całym stacktrace do `logs/sentinel.log`.

Aby debugować ML prediction:
```python
from src.ensemble_models import predict_lstm_direction
pred = predict_lstm_direction(df)
print(f"LSTM prediction: {pred}")
```

