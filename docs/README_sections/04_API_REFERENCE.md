# 🌐 API Reference

## Backend API (FastAPI)

Pełna dokumentacja API dostępna interaktywnie na: **http://localhost:8000/docs**

## Endpointy

### Rynek (Market)

#### Bieżąca cena
```http
GET /api/market/ticker?symbol=XAUUSD
```

**Odpowiedź:**
```json
{
  "symbol": "XAUUSD",
  "price": 2325.45,
  "timestamp": "2026-04-03T10:15:30Z",
  "change_percent": 0.15
}
```

#### Świece OHLCV
```http
GET /api/market/candles?symbol=XAUUSD&interval=5min&limit=100
```

**Parametry:**
- `symbol` - Symbol (XAUUSD, USDJPY)
- `interval` - Interwał (1min, 5min, 15min, 1h, 4h, 1day)
- `limit` - Liczba świec (domyślnie 100, max 5000)

**Odpowiedź:**
```json
{
  "candles": [
    {"time": "2026-04-03T10:10:00Z", "open": 2324.50, "high": 2326.00, "low": 2324.00, "close": 2325.45, "volume": 1500000},
    ...
  ]
}
```

#### Wskaźniki techniczne
```http
GET /api/market/indicators?symbol=XAUUSD&interval=1h
```

**Odpowiedź:**
```json
{
  "rsi": 55.32,
  "macd": 12.45,
  "macd_signal": 11.20,
  "macd_histogram": 1.25,
  "bollinger_upper": 2330.00,
  "bollinger_lower": 2320.00,
  "bollinger_middle": 2325.00,
  "atr": 12.50,
  "ema_20": 2323.45,
  "ema_50": 2318.20
}
```

---

### Sygnały (Signals)

#### Bieżący sygnał
```http
GET /api/signals/current
```

**Odpowiedź:**
```json
{
  "direction": "LONG",
  "entry": 2325.00,
  "stop_loss": 2323.00,
  "take_profit": 2330.00,
  "lot": 0.12,
  "confluence_score": 8,
  "timestamp": "2026-04-03T10:15:30Z",
  "pattern": "Liquidity Grab + MSS",
  "macro_regime": "GREEN",
  "ai_analysis": "Silna konfluencja - Liquidity Grab + MSS potwierdzone na M5"
}
```

#### Historia sygnałów
```http
GET /api/signals/history?limit=50
```

**Parametry:**
- `limit` - Liczba ostatnich sygnałów

**Odpowiedź:**
```json
{
  "signals": [
    {
      "id": 1,
      "direction": "LONG",
      "entry": 2325.00,
      "stop_loss": 2323.00,
      "take_profit": 2330.00,
      "status": "CLOSED",
      "profit_loss": 125.50,
      "timestamp": "2026-04-03T10:15:30Z"
    },
    ...
  ],
  "total_count": 250
}
```

#### Konsensus między modelami
```http
GET /api/signals/consensus
```

**Odpowiedź:**
```json
{
  "xgboost_probability": 0.75,
  "lstm_probability": 0.68,
  "dqn_action": "LONG",
  "ensemble_vote": "LONG",
  "confidence": 0.72,
  "timestamp": "2026-04-03T10:15:30Z"
}
```

---

### Portfel (Portfolio)

#### Status portfela
```http
GET /api/portfolio/status
```

**Odpowiedź:**
```json
{
  "balance": 5000.00,
  "open_positions": 1,
  "closed_positions": 15,
  "total_profit_loss": 235.50,
  "win_rate": 0.60,
  "equity": 5235.50,
  "max_drawdown": 0.05,
  "timestamp": "2026-04-03T10:15:30Z"
}
```

#### Historia portfela
```http
GET /api/portfolio/history?days=30
```

**Parametry:**
- `days` - Liczba dni do wyświetlenia

**Odpowiedź:**
```json
{
  "history": [
    {"date": "2026-04-03", "balance": 5235.50, "trades": 2, "daily_pnl": 35.50},
    ...
  ]
}
```

---

### Modele ML (Models)

#### Statystyki modeli
```http
GET /api/models/stats
```

**Odpowiedź:**
```json
{
  "xgboost": {
    "accuracy": 0.62,
    "precision": 0.65,
    "recall": 0.60,
    "f1_score": 0.62,
    "last_trained": "2026-04-03T08:00:00Z"
  },
  "lstm": {
    "accuracy": 0.58,
    "precision": 0.61,
    "recall": 0.55,
    "f1_score": 0.58,
    "last_trained": "2026-04-02T12:00:00Z"
  },
  "dqn": {
    "episodes": 1250,
    "avg_reward": 45.30,
    "last_trained": "2026-04-03T10:00:00Z"
  }
}
```

---

### Trening (Training)

#### Status treningu RL agenta
```http
GET /api/training/status
```

**Odpowiedź:**
```json
{
  "episodes": 1250,
  "total_reward": 56750.00,
  "avg_reward_last_100": 47.30,
  "epsilon": 0.05,
  "learning_rate": 0.001,
  "status": "training",
  "last_update": "2026-04-03T10:15:30Z"
}
```

---

## WebSocket Endpoints

### Live prices
```
WS ws://localhost:8000/ws/prices
```

**Subskrypcja:**
```json
{"action": "subscribe", "symbol": "XAUUSD", "interval": "1min"}
```

**Wiadomość:**
```json
{"symbol": "XAUUSD", "price": 2325.45, "timestamp": "2026-04-03T10:15:30Z"}
```

### Live signals
```
WS ws://localhost:8000/ws/signals
```

**Wiadomość:**
```json
{"direction": "LONG", "entry": 2325.00, "score": 8, "timestamp": "2026-04-03T10:15:30Z"}
```

---

## Błędy i kody statusu

| Kod | Znaczenie | Rozwiązanie |
|-----|-----------|------------|
| 200 | OK | Wszystko okej |
| 400 | Bad Request | Sprawdź parametry zapytania |
| 401 | Unauthorized | Brakuje autentykacji |
| 404 | Not Found | Zasób nie istnieje |
| 429 | Too Many Requests | Przekroczony limit API |
| 500 | Server Error | Błąd serwera - spróbuj później |

---

## Uwierzytelnianie (TODO)

Obecnie API nie wymaga autentykacji. W przyszłości będzie JWT.

---

## Rate Limiting

- **Limit**: 100 zapytań/minutę na IP
- **Timeout**: 30 sekund na zapytanie

---

## Przykłady w cURL

### Pobranie bieżącej ceny

```bash
curl "http://localhost:8000/api/market/ticker?symbol=XAUUSD"
```

### Pobranie sygnałów

```bash
curl "http://localhost:8000/api/signals/current"
```

### Pobranie historii portfela

```bash
curl "http://localhost:8000/api/portfolio/history?days=30"
```

---

## Integracja z frontend

Frontend automatycznie łączy się z API poprzez:

```javascript
const response = await fetch('http://localhost:8000/api/signals/current');
const data = await response.json();
```

WebSockets dla live updates:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/prices');
ws.addEventListener('message', (event) => {
  const data = JSON.parse(event.data);
  console.log('Nowa cena:', data.price);
});
```

---

**Więcej:** Pełna dokumentacja na http://localhost:8000/docs (interaktywna!)

