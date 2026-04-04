# 🚀 Szybki Start

## Uruchomienie całego systemu - One Command

### Windows:
```bash
start.bat
```

### Linux/Mac:
```bash
bash start.sh
```

Skrypt automatycznie uruchomi:
- ✅ Backend (API na porcie 8000)
- ✅ Frontend (na porcie 5173)
- ✅ Bot Telegram (opcjonalnie)

---

## Uruchomienie komponentów ręcznie

Jeśli chcesz uruchomić komponenty osobno, otwórz **3 osobne terminale**:

### Terminal 1: Backend (FastAPI)

```bash
python api/main.py
```

Czekaj aż zobaczysz:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

✅ **API:** http://localhost:8000  
✅ **Dokumentacja API:** http://localhost:8000/docs  
✅ **WebSockets:** `/ws/prices`, `/ws/signals`

### Terminal 2: Frontend (React)

```bash
cd frontend
npm install  # tylko za pierwszym razem
npm run dev
```

Czekaj aż zobaczysz:
```
  VITE v... ready in ... ms

  ➜  Local:   http://localhost:5173/
```

✅ **Frontend:** http://localhost:5173

### Terminal 3: Bot Telegram (opcjonalnie)

```bash
python run.py
```

Czekaj aż zobaczysz:
```
✅ Bot TG uruchomiony - nasłuchiwanie na polecenia...
```

Teraz otwórz Telegram i napisz do swojego bota `/start`

---

## Status systemu

Po uruchomieniu wszystkich komponentów, system powinien wyglądać tak:

```
┌─────────────────────────────────────────────────┐
│         🤖 QUANT SENTINEL - Status               │
├─────────────────────────────────────────────────┤
│ ✅ Backend (FastAPI)     http://localhost:8000  │
│ ✅ Frontend (React)      http://localhost:5173  │
│ ✅ Bot Telegram          Nasłuchuje...          │
│ ✅ WebSockets            Aktywne                │
│ ✅ Baza danych           Synchronizowana        │
└─────────────────────────────────────────────────┘
```

### Sprawdzenie zdrowia systemu

Wejdź na http://localhost:8000/docs i przetestuj endpoint:

```bash
GET /api/market/ticker?symbol=XAUUSD
```

Powinna być odpowiedź:
```json
{
  "symbol": "XAUUSD",
  "price": 2325.45,
  "timestamp": "2026-04-03T10:15:30Z"
}
```

---

## Pierwsze kroki z botem Telegram

### 1. Start bota

```
/start
```

Pojawi się menu główne.

### 2. Ustaw kapitał

```
/cap 5000 USD
```

Zastąp 5000 kwotą, z którą chcesz handlować.

### 3. Uruchom analizę

Naciśnij przycisk **🎯 ANALIZA QUANT PRO**

Bot przeprowadzi pełną analizę i wyświetli wyniki.

### 4. Sprawdź statystyki

```
/stats
```

Zobaczysz:
- Win rate
- Liczba TP/SL
- Ostatnie sygnały

---

## Generowanie sygnałów

System ma kilka sposobów na generowanie sygnałów:

### 1. Ręcznie - na żądanie (Telegram)

```
Naciśnij: 🎯 ANALIZA QUANT PRO
```

### 2. Automatycznie - co 15 minut

Bot automatycznie analizuje rynek i zapisuje sygnały do bazy.
Powiadomienia pojawiają się gdy ocena AI ≥ 8/10.

### 3. Przez API

```bash
curl http://localhost:8000/api/signals/current
```

---

## Monitoring

### Logi systemu

**Backend:**
```bash
tail -f logs/sentinel.log
```

**Frontend:**
Otwórz Developer Tools (F12) → Console

### Metryki w Dashboard

Wejdź na http://localhost:5173 aby zobaczyć:
- 📈 Ceny w real-time
- 📊 Wykresy sygnałów
- 💰 Status portfela
- 🤖 Statystyki ML modeli

---

## Zatrzymanie systemu

Aby zatrzymać wszystkie komponenty:

```bash
Ctrl + C
```

w każdym terminalu.

---

## Troubleshooting

### Bot nie odpowiada na `/start`

1. Sprawdź czy `TELEGRAM_BOT_TOKEN` w `.env` jest poprawny
2. Sprawdź czy bot jest aktywny w @BotFather
3. Spróbuj: `/start@TwojBotName`

### Port 8000 / 5173 jest już zajęty

```bash
# Zmień port w api/main.py (linia z uvicorn.run)
# lub w frontend/vite.config.ts
```

### Brak połączenia z API

```bash
# Sprawdź czy backend jest uruchomiony
curl http://localhost:8000/docs
```

### Błędy Twelve Data

Sprawdzaj limit API - darmowy plan ma 8 zapytań/minutę.

---

## Co dalej?

- 📘 [Konfiguracja komend Telegram](https://core.telegram.org/bots/api)
- 📊 [API Reference](04_API_REFERENCE.md)
- 🔬 [Jak to działa wewnętrznie?](05_HOW_IT_WORKS.md)
- 🧪 [Testing i Development](06_ADVANCED.md)

