# 🚀 QUANT SENTINEL - Instrukcja Uruchamiania

## Szybki Start (Windows)

### Automatyczne uruchamianie (Polecane)
```bash
start.bat
```

Script automatycznie:
- Aktywuje wirtualne środowisko (.venv)
- Uruchamia Backend API na porcie 8000
- Uruchamia Frontend na porcie 5173
- Opcjonalnie uruchamia Scanner

### Ręczne uruchamianie

**1. Aktywować venv**
```powershell
.venv\Scripts\activate
```

**2. Instalacja bibliotek (jeśli potrzebne)**
```powershell
pip install -r requirements.txt
```

**3. Uruchamianie osobnych komponentów w osobnych terminalach**

Terminal 1 - Backend:
```powershell
python api/main.py
```

Terminal 2 - Frontend:
```powershell
cd frontend
npm run dev
```

Terminal 3 - Scanner (opcjonalnie):
```powershell
python run.py
```

## URLs dostępu

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **WebSocket**: ws://localhost:8000/ws

## Wymagania

- Python 3.11+
- Node.js 18+
- npm 9+

## Nowe Funkcjonalności (v2.1)

### 1. ✅ Aktualizacja Balansu
- Możliwość zmiany balansu portfela bezpośrednio z dashbordu
- Endpoint API: `POST /api/portfolio/update-balance`
- Frontend: Kliknij ikonę ✏️ obok "Balance"

### 2. ✅ Szybsze Odświeżanie Wykresów
- Wykres zmienia się co **30 sekund** (zamiast 120)
- Automatyczne detekcje zmian ceny
- W przypadku mock data - zmienia się co **minutę**

### 3. ✅ Zaokrąglenie Cen
- Wszystkie ceny zaokrąglone do **2 miejsc po przecinku**
- Tooltip wykresu pokazuje szczegółowe dane

## Troubleshooting

### Błąd: "Module not found"
```
pip install -r requirements.txt
```

### Frontend błędy TypeScript
```
cd frontend
npm install
npm run dev
```

### Backend nie startuje
- Sprawdź czy port 8000 jest wolny
- Sprawdź czy .env jest prawidłowo skonfigurowany
- Sprawdź czy wszystkie biblioteki Python są zainstalowane

### Błędy Unicode w logach (Windows)
- Użyj PowerShell zamiast Command Prompt
- Lub ustaw encoding: `$OutputEncoding = [System.Text.UTF8Encoding]::UTF8`

## Monitoring

Backend automatycznie:
- Pobiera dane z Twelve Data API (max 55 requestów/minutę)
- Analizuje trendy za pomocą ML modeli (LSTM, XGBoost, RL Agent)
- Wysyła notyfikacje na Telegram
- Utrzymuje WebSocket connection z frontendem
- Cache'uje dane aby zminimalizować requesty

## Development

```bash
# Build production
cd frontend
npm run build

# Testy
pytest tests/

# Linting
flake8 src/
black src/
```

## API Endpoints

### Portfolio
- `GET /api/portfolio/status` - Pobierz stan portfela
- `POST /api/portfolio/update-balance` - Zaktualizuj balans
- `GET /api/portfolio/history` - Historia portfela
- `GET /api/portfolio/summary` - Podsumowanie

### Market
- `GET /api/market/ticker?symbol=XAU/USD` - Aktualną cenę
- `GET /api/market/candles?symbol=XAU/USD&interval=15m` - Świece OHLCV
- `GET /api/market/indicators?symbol=XAU/USD&interval=15m` - Wskaźniki (RSI, BB, MACD)
- `GET /api/market/status` - Status rynku

### Signals
- `GET /api/signals/current` - Aktualny sygnał (consensus)
- `GET /api/signals/history?limit=50` - Historia sygnałów
- `GET /api/signals/consensus` - Consensus score

### Models
- `GET /api/models/stats` - Statystyki modeli
- `GET /api/models/rl-agent` - Stats RL Agent
- `GET /api/models/lstm` - Stats LSTM
- `GET /api/models/xgboost` - Stats XGBoost

## Optymalizacja Twelve Data API

**Limit**: 55 kredytów na minutę

Aplikacja automatycznie:
- Cache'uje dane na 30-120 sekund
- Zmniejsza ilość requestów
- Batchuje zapytania gdzie możliwe
- Ponawiała z exponential backoff'em przy 429 error

## Wsparcie

Jeśli coś nie działa:
1. Sprawdź logi w `logs/sentinel.log`
2. Sprawdź console frontend'u (F12)
3. Sprawdź czy API jest dostępne: `curl http://localhost:8000/docs`
4. Sprawdź czy port 8000 jest wolny: `netstat -ano | findstr :8000`


