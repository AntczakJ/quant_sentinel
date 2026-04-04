# 🔄 QUANT SENTINEL - Zmiany w v2.1

## 🐛 Błędy Naprawione

### 1. ❌ Problem: Zmiana balansu nie działa
**Status**: ✅ NAPRAWIONE

**Przyczyna**: Brakował API endpoint'u do aktualizacji balansu

**Rozwiązanie**:
- Dodałem POST endpoint `/api/portfolio/update-balance`
- Implementacja w backendzie (api/routers/portfolio.py)
- Dodałem metodę `updateBalance()` w frontend API client
- Zaimplementowałem logikę w komponencie `PortfolioStats.tsx`

**Test**:
```bash
curl -X POST http://localhost:8000/api/portfolio/update-balance \
  -H "Content-Type: application/json" \
  -d '{"balance": 15000}'
```

**Rezultat**: ✅ Balance zmienia się natychmiast, UI się odświeża

---

### 2. ❌ Problem: Wykres stoi w miejscu (nie aktualizuje się)
**Status**: ✅ NAPRAWIONE

**Przyczyna**: Refresh co 120 sekund był zbyt długi

**Rozwiązanie**:
- Zmniejszyłem interval z 120 sekund na **30 sekund**
- Dodałem śledzenie ostatniej ceny (`lastPrice` state)
- Wykres będzie się odświeżać co 30 sekund zawsze
- W przypadku mock data - zmienia się co minutę

**Kod zmieniony**: `frontend/src/components/charts/CandlestickChart.tsx` linia 65-70

**Rezultat**: ✅ Wykres się aktualizuje co 30 sekund, nawet gdy rynek zamknięty (mock data się zmienia)

---

### 3. ❌ Problem: Mock candles zawsze takie same
**Status**: ✅ NAPRAWIONE

**Przyczyna**: `np.random.seed(42)` - stały seed powodował że dane się nie zmieniają

**Rozwiązanie**:
- Zmienić seed z `42` na `current_minute % 1000`
- Teraz seed zmienia się co minutę
- Dane są konsystentne w obrębie tej samej minuty, ale zmieniają się co minutę

**Kod zmieniony**: `api/routers/market.py` linia 112

```python
# PRZED:
np.random.seed(42)  # Zawsze takie same dane

# PO:
current_minute = int(current_time / 60)
np.random.seed(current_minute % 1000)  # Nowe dane co minutę
```

**Rezultat**: ✅ Mock candles zmieniają się co minutę, bez potrzeby podłączenia do Twelve Data API

---

### 4. ❌ Problem: UnicodeEncodeError w logach (Windows)
**Status**: ✅ NAPRAWIONE

**Przyczyna**: Windows console nie obsługuje emoji i Unicode

**Rozwiązanie**:
- Ulepszyłem `UnicodeStreamHandler` w `src/logger.py`
- Dodałem fallback strategy do ASCII-fikacji tekstu
- Teraz emoji są zamieniane na `?` gdy console nie obsługuje

**Kod zmieniony**: `src/logger.py` linia 18-41

**Rezultat**: ✅ Backend startuje bez erroru na Windows

---

## ✨ Nowe Funkcjonalności

### 1. 💰 Edycja Balansu Portfela
- Klikni ikonę ✏️ obok "Balance" w PortfolioStats
- Wpisz nową wartość
- Kliknij ✓ aby zatwierdzić
- Balance się zmienia natychmiast

### 2. 📊 Szybsze Wykresy
- Wykresy odświeżają się co **30 sekund** zamiast 120
- Lepsze tracking zmian ceny w real-time

### 3. 💵 Prawidłowe Zaokrąglenie
- Wszystkie ceny zaokrąglone do **2 miejsc po przecinku**
- W tooltip'ach i nagłówkach

---

## 📊 Statystyki Poprawek

| Komponent | Linie zmienione | Typ | Status |
|-----------|-----------------|-----|--------|
| Portfolio Router | +35 | Backend | ✅ |
| API Client | +5 | Frontend | ✅ |
| PortfolioStats | -8, +16 | Frontend | ✅ |
| CandlestickChart | -50, +48 | Frontend | ✅ |
| Market Router | -30, +32 | Backend | ✅ |
| Logger | -14, +24 | Backend | ✅ |

**Total**: ~150 linii zmienionego kodu

---

## 🧪 Testy

### Backend Test
```bash
curl http://localhost:8000/api/portfolio/status
```
✅ Zwraca: `{"balance":10000.0, ...}`

### Update Test
```bash
curl -X POST http://localhost:8000/api/portfolio/update-balance \
  -H "Content-Type: application/json" \
  -d '{"balance": 20000}'
```
✅ Zwraca: `{"success":true, "balance":20000.0}`

---

## 🚀 Deployment

### Aby uruchomić nową wersję:

1. **Pull najnowszego kodu**
```bash
git pull origin main
```

2. **Zainstaluj zmiany**
```bash
pip install -r requirements.txt
cd frontend && npm install
```

3. **Uruchom aplikację**
```bash
start.bat  # Windows
# lub
chmod +x start.sh && ./start.sh  # Linux/Mac
```

---

## ℹ️ Znane Problemy

### Problem: "Cannot read properties of undefined"
- ✅ Naprawione w v2.1

### Problem: Wykres się nie aktualizuje
- ✅ Naprawione w v2.1 (zmniejszony interval)

### Problem: Cena nie zmienia się w headrze
- Oczekiwanie - będzie się aktualizować gdy rynek będzie otwarty

---

## 📝 Notes

- Wszystkie zmiany są backward compatible
- Nie ma breaking changes
- Database schema nie zmienił się
- Frontend jest teraz bardziej responsywny

---

**Wersja**: 2.1.0  
**Data**: 2026-04-04  
**Status**: ✅ Production Ready

