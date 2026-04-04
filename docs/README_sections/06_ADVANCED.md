# 🧪 Advanced - Testing, Development, Troubleshooting

## Testing

### Szybki test (REKOMENDOWANY)

```bash
python tests/run_quick_tests.py
```

✅ **Wynik:** 20/20 tests pass (100%)

### Uruchom konkretny test

```bash
python tests/test_config.py
python tests/test_database.py
python tests/test_smc_engine.py
python tests/test_finance.py
python tests/test_ai.py
python tests/test_ml.py
python tests/test_integration.py
python tests/test_performance.py
```

### Uruchom z pytest

```bash
# Wszystkie testy
pytest tests/ -v

# Z coverage report
pytest tests/ --cov=src --cov-report=html

# Konkretny test
pytest tests/test_signals.py::test_signal_generation -v
```

---

## Test Suites

### 1. Unit Tests (test_*.py)

**Plik:** `tests/test_config.py`, `tests/test_database.py` itd.

- ✅ Testy konfiguracji (zmienne środowiskowe, thread-safety)
- ✅ Testy bazy danych (CRUD operations)
- ✅ Testy cache'a (performance, TTL)
- ✅ Testy SMC Engine (analiza, caching)
- ✅ Testy Finance (position sizing)
- ✅ Testy AI (GPT-4o integration)
- ✅ Testy ML (model loading, predictions)

### 2. Integration Tests

**Plik:** `tests/test_integration.py`

Testuje pełny pipeline:
- Pobieranie danych → SMC analysis → ML prediction → AI evaluation → Signal generation

### 3. Performance Tests

**Plik:** `tests/test_performance.py`

Benchmarki:
- SMC analysis time
- ML prediction latency
- Database query time
- API response time
- WebSocket latency

### 4. API Tests

**Plik:** `tests/test_api_endpoints.py`

- GET /api/market/ticker
- GET /api/market/candles
- GET /api/signals/current
- GET /api/portfolio/status
- WebSocket connections

---

## Debugging

### Logi systemu

**Backend:**
```bash
tail -f logs/sentinel.log
```

**Logi w kodzie:**
```python
from src.logger import logger

logger.info("Informacja")
logger.warning("Ostrzeżenie")
logger.error("Błąd")
logger.debug("Debug info")
```

### Debugger IDE

**PyCharm:**
1. Ustaw breakpoint (kliknij na linię)
2. Run → Debug 'run.py'
3. Używaj Step Over (F10), Step Into (F11)

**VS Code:**
1. Zainstaluj Python extension
2. Utwórz `.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal"
    }
  ]
}
```
3. F5 to debug

### Print debugging

```python
# Szybki debug
print(f"DEBUG: {variable_name} = {variable_value}")

# Z timingiem
import time
start = time.time()
# ... kod
print(f"Czas: {time.time() - start:.3f}s")

# JSON debug
import json
print(json.dumps(data, indent=2))
```

---

## Troubleshooting

### Bot nie odpowiada

```python
# Sprawdź czy bot jest uruchomiony
ps aux | grep "python run.py"

# Czy token w .env jest poprawny?
echo $TELEGRAM_BOT_TOKEN

# Spróbuj restartu
Ctrl + C
python run.py
```

### Błędy API

**Problem:** "ConnectionRefusedError: [Errno 111] Connection refused"

**Rozwiązanie:**
```bash
# Upewnij się że backend działa
python api/main.py

# Sprawdź port
netstat -tlnp | grep 8000  # Linux
netstat -ano | findstr :8000  # Windows
```

**Problem:** "401 Unauthorized" z Twelve Data

**Rozwiązanie:**
```bash
# Sprawdź klucz API
echo $TWELVE_DATA_API_KEY

# Odwiedź https://twelvedata.com/account/api-keys
# Upewnij się że klucz jest aktywny
```

### Baza danych

**Problem:** "sqlite3.OperationalError: database is locked"

**Rozwiązanie:**
```python
# Baza jest używana przez inny proces
# Sprawdź czy nie ma 2 instancji bota

# Jeśli застрял, usuń lock file
import sqlite3
conn = sqlite3.connect('data/sentinel.db')
conn.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging
conn.close()
```

**Problem:** "database disk image is malformed"

**Rozwiązanie:**
```bash
# Baza jest uszkodzona - zrób backup i usuń
mv data/sentinel.db data/sentinel.db.backup
# Bot utworzy nową bazę

# Jeśli to produkcja, przywróć z backupu
cp data/sentinel.db.backup data/sentinel.db
```

### ML Models

**Problem:** "Model not found: models/xgb.pkl"

**Rozwiązanie:**
```bash
# Modele trzeba wytrenować
python -c "from src.ml_models import MLPredictor; m = MLPredictor(); m.train_xgb(data)"

# Lub poczekaj aż bot automatycznie je wytrenuje
```

---

## Development

### Dodanie nowego wskaźnika

**Krok 1:** Dodaj do `src/indicators.py`

```python
def calculate_williams_r(df, period=14):
    """Williams %R indicator"""
    high = df['high'].rolling(period).max()
    low = df['low'].rolling(period).min()
    williams_r = -100 * (high - df['close']) / (high - low)
    return williams_r
```

**Krok 2:** Dodaj do SMC Engine (`src/smc_engine.py`)

```python
def get_smc_analysis(df_xau, df_dxy, interval, macro_regime):
    # ... existing code ...
    analysis['williams_r'] = calculate_williams_r(df_xau)
    return analysis
```

**Krok 3:** Dodaj test (`tests/test_smc_engine.py`)

```python
def test_williams_r():
    df = create_test_candles()
    wr = calculate_williams_r(df)
    assert not wr.isna().all()
    assert (wr >= -100).all() and (wr <= 0).all()
```

**Krok 4:** Uruchom test

```bash
pytest tests/test_smc_engine.py::test_williams_r -v
```

### Dodanie nowego ML Model

**Krok 1:** Dodaj do `src/ml_models.py`

```python
class MLPredictor:
    def train_random_forest(self, df):
        """Random Forest classifier"""
        from sklearn.ensemble import RandomForestClassifier
        features = self._features(df)
        features['direction'] = (features['close'].shift(-1) > features['close']).astype(int)
        features.dropna(inplace=True)
        
        X = features.drop(columns=['direction', 'open', 'high', 'low', 'close', 'volume'], errors='ignore')
        y = features['direction']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        self.rf = RandomForestClassifier(n_estimators=100, max_depth=10)
        self.rf.fit(X_train, y_train)
        
        acc = self.rf.score(X_test, y_test)
        logger.info(f"Random Forest trained, accuracy: {acc:.2f}")
        
        with open(os.path.join(self.model_dir, 'rf.pkl'), 'wb') as f:
            pickle.dump(self.rf, f)
        return acc
```

**Krok 2:** Zintegruj z ensemble voting (`src/scanner.py`)

```python
def get_ensemble_vote():
    xgb_pred = ml.predict_xgb(df)
    lstm_pred = ml.predict_lstm(df)
    dqn_action = rl.get_action(state)
    rf_pred = ml.predict_rf(df)  # NEW
    
    votes = sum([xgb_pred > 0.5, lstm_pred > 0.5, dqn_action == BUY, rf_pred > 0.5])
    return "LONG" if votes >= 2 else "HOLD"
```

**Krok 3:** Test

```bash
pytest tests/test_ml.py -v
```

### Dodanie nowego API Endpoint

**Plik:** `api/routers/signals.py`

```python
from fastapi import APIRouter

router = APIRouter(prefix="/api/signals", tags=["signals"])

@router.get("/ensemble-stats")
async def get_ensemble_stats():
    """Statystyki ensemble votingu"""
    from src.scanner import get_ensemble_vote_stats
    stats = get_ensemble_vote_stats()
    return {
        "xgb_avg_confidence": stats['xgb_avg'],
        "lstm_avg_confidence": stats['lstm_avg'],
        "dqn_avg_reward": stats['dqn_avg'],
        "ensemble_agreement_rate": stats['agreement_rate']
    }
```

**Zarejestruj w `api/main.py`:**

```python
from api.routers import signals

app.include_router(signals.router)
```

**Test:**

```bash
curl http://localhost:8000/api/signals/ensemble-stats
```

---

## Performance Optimization

### Caching

```python
from src.cache import cache_with_ttl

@cache_with_ttl(ttl_seconds=60)
def expensive_calculation():
    # Ta funkcja wynik będzie cachowany przez 60s
    return heavy_computation()
```

### Database Indexing

```python
def create_tables(self):
    self._execute("CREATE TABLE trades (...)")
    # Dodaj indeksy
    self._execute("CREATE INDEX idx_trades_timestamp ON trades(timestamp)")
    self._execute("CREATE INDEX idx_trades_status ON trades(status)")
```

### Batch Operations

```python
# ❌ Źle (wolne)
for trade in trades:
    db.save(trade)

# ✅ Dobrze (szybkie)
db.save_batch(trades)
```

---

## Release Checklist

Przed wdrożeniem do produkcji:

- [ ] Wszystkie testy pass (20/20)
- [ ] Nie ma deprecation warnings (`python -W error -m pytest`)
- [ ] Code coverage > 80%
- [ ] Dokumentacja zaktualizowana
- [ ] Backup bazy danych
- [ ] .env jest bezpieczny
- [ ] Logi działają
- [ ] Performance benchmarks OK
- [ ] API response times <1s

---

## Contributing

1. **Fork repozytorium**
2. **Utwórz branch:** `git checkout -b feature/my-feature`
3. **Commit:** `git commit -m "Add new feature"`
4. **Push:** `git push origin feature/my-feature`
5. **Pull Request:** Otwórz PR na GitHub
6. **Code Review:** Czekaj na review
7. **Merge:** Po aprobacie, merge do main

---

## Git Workflow

```bash
# Clone
git clone https://github.com/twoj_login/quant_sentinel.git

# Sprawdź status
git status

# Dodaj zmiany
git add .

# Commit
git commit -m "Opis zmiany"

# Push
git push origin main

# Pull najnowsze zmiany
git pull origin main

# Sprawdź historię
git log --oneline -10
```

---

## Architecture Decision Records (ADR)

Dokumentujemy kluczowe decyzje architektoniczne:

**Plik:** `docs/ADR/001_ensemble_voting.md`

```markdown
# ADR-001: Ensemble Voting Strategy

## Problem
Pojedyncze modele ML mają accuracy ~60%, co daje zbyt dużo false signalsów.

## Solution
Ensemble voting: 3+ modele (XGBoost, LSTM, DQN) głosują nad kierunkiem.

## Decision
- XGBoost: szybki, dobrze handluje klasycznymi wskaźnikami
- LSTM: sekwencyjny, uczy się patternów
- DQN: RL, uczy się z nagród z czasu na czas

## Consequences
- +25% accuracy
- +3 ms latencji
- Mniej fałszywych sygnałów

## Status: ACCEPTED ✅
```

---

## Zasoby

- 📚 [FastAPI Docs](https://fastapi.tiangolo.com/)
- 🐍 [Python Best Practices](https://pep8.org/)
- 🧪 [Pytest Documentation](https://docs.pytest.org/)
- 💰 [XGBoost Tuning](https://xgboost.readthedocs.io/)
- 🧠 [TensorFlow/Keras](https://www.tensorflow.org/)

---

## Support

- ❓ Masz pytania? Otwórz Issue na GitHub
- 🐛 Znaleźliśmy bug? Otwórz Issue z `[BUG]`
- 💡 Pomysł na feature? Otwórz Discussion

---

**Ostatnia aktualizacja:** Kwiecień 2026

