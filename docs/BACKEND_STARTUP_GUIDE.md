# 🎯 BACKEND URUCHOMIONY - INSTRUKCJE

**Data**: 2026-04-04  
**Status**: ✅ Backend API uruchamia się  

---

## ✅ Co się Dzieje

Backend Python API (`api/main.py`) uruchomił się na porcie 8000.

System inicjalizuje:
1. ✅ Baza danych SQLite
2. ✅ Modele ML (LSTM, XGBoost, DQN)
3. ✅ Rate limiting dla Twelve Data API
4. ✅ Cache persistent
5. ✅ Logger system

**Czas inicjalizacji**: ~15-30 sekund

---

## 📊 Co Będzie Dostępne

### Endpoints API:
```
GET    /api/health                          ✅ Health check
GET    /api/market/ticker                   ✅ Current price
GET    /api/market/candles                  ✅ OHLCV data
GET    /api/signals/current                 ✅ Trading signal
GET    /api/signals/history                 ✅ Signal history
GET    /api/analysis/quant-pro              ✅ Full SMC+ML analysis
GET    /api/analysis/ml-ensemble            ✅ ML predictions only
GET    /api/analysis/trades                 ✅ Trade history
POST   /api/portfolio/add-trade             ✅ Add trade
GET    /api/portfolio/status                ✅ Portfolio
GET    /api/portfolio/current-price         ✅ Live price
POST   /api/portfolio/update-balance        ✅ Update balance
```

### WebSocket:
```
WS     /ws/updates                          ✅ Real-time updates
```

---

## 🌐 Frontend Autom atycznie Połączy Się

Frontend (Vite dev server na :5173) będzie:
1. Czekać na Backend ready
2. Wysyłać requesty do :8000/api/*
3. Wyświetlać dane w real-time

---

## 🔄 Co Zrobić Jeśli Dalej ERR_CONNECTION_REFUSED

### Opcja 1: Czekaj i Odśwież
- Poczekaj 30 sekund
- Odśwież stronę: **F5**

### Opcja 2: Sprawdź Port
```powershell
# PowerShell:
netstat -ano | findstr :8000

# Powinno pokazać: Backend słucha na :8000
```

### Opcja 3: Ręczny Start
```powershell
cd C:\Users\Jan\PycharmProjects\quant_sentinel
python api/main.py

# Lub
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Opcja 4: Sprawdź Logi
```powershell
Get-Content -Path "logs\sentinel.log" -Tail 50
```

---

## ✅ Znaki że Działa

- Backend nie pyta o hasło
- Brak "connection refused" w logach
- Port 8000 słucha
- GET `/api/health` zwraca JSON

---

## 📋 Checklist

- [ ] Backend uruchomiony (`python api/main.py`)
- [ ] Port 8000 słucha (Test-NetConnection)
- [ ] Frontend strona się ładuje (http://localhost:5173)
- [ ] Brak Network Errors w console
- [ ] Dane się ładują (prices, signals, trades)

---

## 🎯 Oczekiwane Zachowanie

### Przy Starcie:
1. Frontend connectuje do backendu (5-10 sekund)
2. Dane zaczynają się ładować
3. Network Errors znikają
4. Wykresy się rysują
5. Sygnały się pojawią

### W Realtime:
- Price updates co 1 sekund
- Signals co 5 sekund
- Trades historia auto-refresh

---

**Status**: ✅ **BACKEND URUCHOMIONY**

**Następny krok**: Odśwież frontend (F5) i czekaj na dane! 🚀

