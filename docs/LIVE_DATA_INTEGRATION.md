# 📡 LIVE DATA INTEGRATION - Dokumentacja Zmian

**Data**: 2026-04-04  
**Status**: ✅ UKOŃCZONE I TESTOWANE  
**Testy**: ✅ 5/5 PASSED  

---

## 🎯 Co zostało zmienione

### 1. **Modele ML (LSTM, XGBoost, DQN) - TERAZ UŻYWAJĄ LIVE DATA**

Przed:
```python
# Pobierały dane z Yahoo Finance (yfinance)
df = yf.Ticker("GC=F").history(period="1mo", interval="15m")
```

Po:
```python
# Pobierają LIVE data z Twelve Data API
provider = get_provider()  # TwelveData
df = provider.get_candles('XAU/USD', '15m', 200)
```

### 2. **Zmodyfikowane pliki**

#### `src/ensemble_models.py`
```python
def get_ensemble_prediction(
    df: pd.DataFrame = None,  # ← Teraz opcjonalny
    ...
    use_twelve_data: bool = True,  # ← Auto-fetch z Twelve Data
    symbol: str = "XAU/USD",
    timeframe: str = "15m"
)
```

**Logika:**
- Jeśli `df is None` → pobiera live data z Twelve Data
- Jeśli `use_twelve_data=False` i brak df → fallback

#### `src/finance.py`
```python
if df is None:
    # Pobierz live data z Twelve Data
    provider = get_provider()
    df = provider.get_candles('XAU/USD', '15m', 200)
```

#### `tests/test_ml_ensemble_integration.py`
```python
# TEST 2 teraz testuje auto-fetch z Twelve Data
ensemble = get_ensemble_prediction(
    df=None,  # ← Wymusza fetch z Twelve Data!
    use_twelve_data=True
)
```

### 3. **train_rl.py - BEZ ZMIAN**

```python
# Nadal używa yfinance (dla offline trenowania)
df = yf.Ticker("GC=F").history(period="1mo", interval="15m")
```

To jest PRAWIDŁOWE, bo:
- `train_rl.py` to OFFLINE trenowanie modelu
- Nie powinno pobierać live data (może być niedostępna)
- Używa historycznych danych do trenowania

---

## 📊 Wyniki Testów

```
✅ TEST 1: Indywidualne modele ML
   - LSTM: 0.5209 (LONG) ✅
   - XGBoost: 0.8476 (LONG) ✅
   - DQN: BUY (1) ✅

✅ TEST 2: Ensemble Voting (with Twelve Data)
   - Pobrano 200 candles z XAU/USD 15m ✅
   - Score: 0.8013 ✅
   - Confidence: 54.0% ✅
   - Models: 3 dostępne ✅

✅ TEST 3: Conflicting Signals
✅ TEST 4: Low Confidence
✅ TEST 5: Custom Weights

REZULTAT: 5/5 TESTÓW PASSED
```

---

## 🔄 Flow - Teraz

### Analiza Pozycji

```
API: GET /analysis/quant-pro?tf=15m
    ↓
SMC Analysis (get_smc_analysis)
    ↓
AI Assessment (ask_ai_gold)
    ↓
calculate_position()
    ├─ Pobierz LIVE data z Twelve Data ✅ (NOWE)
    ├─ Uruchom get_ensemble_prediction()
    │   ├─ predict_lstm_direction() ← live data
    │   ├─ predict_xgb_direction() ← live data
    │   ├─ predict_dqn_action() ← live data
    │   └─ Weighted voting
    └─ Zwróć position z ML analysis
```

### Trening Modeli (offline)

```
train_rl.py
    ↓
fetch_historical_data() ← yfinance (bez zmian!)
    ↓
TradingEnv + DQNAgent
    ↓
Trening offline
    ↓
Zapis modelu do models/rl_agent.keras
```

---

## ⚙️ Techniczne Details

### Twelve Data Flow

1. **get_provider()** → zwraca TwelveDataProvider
2. **provider.get_candles('XAU/USD', '15m', 200)**
   - Rate limiting: 55 credits/min
   - Persistent cache
   - Exponential backoff na 429 errors

3. **Modele używają live data** ✅
   - LSTM → live closes (60 świec)
   - XGBoost → live closes (100 świec)
   - DQN → live closes (20 świec)

### Fallback Mechanism

```python
if df is None or df.empty:
    if use_twelve_data:
        try:
            df = provider.get_candles(...)
        except:
            return _fallback_ensemble_result()  # CZEKAJ
```

---

## 📝 Logika Pobierania Danych

### Before (STARE)
```
Każdy model miał własne pobieranie:
- LSTM: yahoo → 60 świec
- XGBoost: yahoo → 100 świec
- DQN: yahoo → 20 świec

Ryzyko: Stare dane z Yahoo
```

### After (NOWE) ✅
```
Centralne pobieranie:
get_ensemble_prediction()
    ↓
Twelve Data API → 200 świec (live)
    ↓
cache (persistent)
    ↓
LSTM → ostatnie 60
XGBoost → ostatnie 100
DQN → ostatnie 20

Korzyści:
- Jedna odpowiedź z API
- Wszystkie modele mają same dane
- Rate limiting scentralizowany
- Cache zmniejsza API calls
```

---

## 🎯 Gwarancje

| Aspekt | Gwarancja |
|--------|----------|
| **Live Data** | ✅ Pobiera z Twelve Data |
| **train_rl.py** | ✅ Bez zmian (yfinance) |
| **Offline Trenowanie** | ✅ Nadal działa |
| **Backward Compat** | ✅ 100% |
| **Rate Limiting** | ✅ Respektuje limity |
| **Fallback** | ✅ CZEKAJ jeśli data niedostępna |
| **Tests** | ✅ 5/5 PASSED |

---

## 🚀 Użycie

### Automatic (Recommended)
```python
# Nie podawaj df - pobierze live data
ensemble = get_ensemble_prediction(
    smc_trend="bull",
    current_price=2050,
    # ... pozostałe parametry
)
```

### Manual (jeśli masz df)
```python
# Podaj df - nie będzie pobierać
ensemble = get_ensemble_prediction(
    df=my_dataframe,
    use_twelve_data=False,  # ← Skip fetch
    ...
)
```

### Wyłącz Twelve Data (offline)
```python
ensemble = get_ensemble_prediction(
    df=None,
    use_twelve_data=False,  # ← Fallback
    ...
)
```

---

## 📋 Checklist

- [x] Modify ensemble_models.py
- [x] Add live data fetching
- [x] Modify finance.py
- [x] Add fallback mechanism
- [x] Update test_ml_ensemble_integration.py
- [x] Leave train_rl.py unchanged
- [x] Test individual models
- [x] Test ensemble with live data ✅
- [x] Test fallback
- [x] Verify backward compatibility
- [x] Run all tests ✅

**Status**: ✅ WSZYSTKO GOTOWE

---

## 🔍 Weryfikacja

### Test Pokazuje:
```
Fetched 200 candles: XAU/USD 15m
Ensemble: 3 modele | Score: 0.801 | Confidence: 54.0% | Signal: LONG
```

### Oznacza To:
1. ✅ Pobrano live data z Twelve Data
2. ✅ Wszystkie 3 modele mają dostęp do live data
3. ✅ Ensemble prawidłowo łączy predykcje
4. ✅ System gotowy do produkcji

---

## 📞 Support

Jeśli masz problem:

1. **Sprawdź API key**: `TWELVE_DATA_API_KEY` w `.env`
2. **Sprawdź logi**: `grep -i "Fetched\|Error" logs/sentinel.log`
3. **Test lokalnie**: `python tests/test_ml_ensemble_integration.py`
4. **Debug**: `logger.debug()` w ensemble_models.py

---

**Version**: v2.2.1  
**Date**: 2026-04-04  
**Status**: ✅ PRODUCTION READY  
**Tests**: ✅ 5/5 PASSED

