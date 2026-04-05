# Quant Sentinel — Konfiguracja OpenAI Agent Builder

## Szybki start

### 1. Automatyczne tworzenie agenta (zalecane)

Dodaj klucz do `.env` i uruchom API — agent zostanie stworzony automatycznie:

```env
OPENAI_API_KEY=sk-...
# OPENAI_ASSISTANT_ID=  ← zostaw puste, zostanie uzupełnione po pierwszym starcie
```

Po pierwszym uruchomieniu API (`python api/main.py`) lub Telegram bota (`python run.py`)
w logach pojawi się:

```
🆕 Utworzono nowego asystenta: asst_XXXXXXXXXX
💡 Dodaj do .env: OPENAI_ASSISTANT_ID=asst_XXXXXXXXXX
```

Skopiuj ten ID do `.env`. Dzięki temu kolejne starty będą używać tego samego agenta (z zachowaną konfiguracją).

---

### 2. Konfiguracja ręczna w platform.openai.com/agent-builder

Jeśli chcesz skonfigurować agenta przez interfejs webowy:

1. Wejdź na https://platform.openai.com/agent-builder
2. Kliknij **"Create agent"**
3. Uzupełnij pola:

#### Nazwa agenta
```
Quant Sentinel Gold Trader
```

#### Model
```
gpt-4o
```

#### Instructions (system prompt)
Pobierz aktualną treść przez endpoint:
```
GET http://localhost:8000/api/agent/config
```
Skopiuj pole `instructions` z odpowiedzi JSON.

Lub użyj zawartości stałej `AGENT_INSTRUCTIONS` z `src/openai_agent.py`.

#### Narzędzia (Functions)
Pobierz schematy narzędzi z:
```
GET http://localhost:8000/api/agent/config
```
Skopiuj pole `tools` — to lista schematów JSON do dodania jako "Functions" w Agent Builderze.

**Lista narzędzi:**
| Narzędzie | Opis |
|---|---|
| `analyze_xauusd` | Pełna analiza SMC (trend, FVG, OB, makro, Liquidity Grab, MSS) |
| `get_trading_signal` | Sygnał tradingowy z entry/SL/TP/lot (SMC + ML ensemble) |
| `get_market_news` | Najnowsze wiadomości złota z Reuters/FXStreet |
| `get_economic_calendar` | Kalendarz ekonomiczny USD (NFP, CPI, FOMC) |
| `get_portfolio_stats` | Win rate, historia transakcji, lekcje systemu |
| `analyze_market_context` | Analiza AI kontekstu (sentyment, newsy, ocena setupu) |

4. Po zapisaniu skopiuj **Assistant ID** (format: `asst_XXXXXXXXXX`)
5. Dodaj do `.env`:
```env
OPENAI_ASSISTANT_ID=asst_XXXXXXXXXX
```

---

## Endpointy API agenta

| Metoda | Endpoint | Opis |
|---|---|---|
| `POST` | `/api/agent/chat` | Wyślij wiadomość, odbierz odpowiedź |
| `POST` | `/api/agent/thread` | Utwórz nowy wątek rozmowy |
| `GET` | `/api/agent/thread/{id}` | Historia wiadomości w wątku |
| `GET` | `/api/agent/info` | Informacje o agencie |
| `GET` | `/api/agent/config` | Eksport konfiguracji dla Agent Builder |

### Przykład użycia (Python)
```python
import requests

# Nowa rozmowa
resp = requests.post("http://localhost:8000/api/agent/chat", json={
    "message": "Przeanalizuj XAU/USD na M15 i daj mi sygnał"
})
data = resp.json()
print(data["response"])

# Kontynuacja tej samej rozmowy (pamięć!)
thread_id = data["thread_id"]
resp2 = requests.post("http://localhost:8000/api/agent/chat", json={
    "message": "A jak wygląda makro reżim?",
    "thread_id": thread_id   # ← agent pamięta poprzednią rozmowę
})
```

### Przykład użycia (JavaScript/TypeScript)
```typescript
import { agentAPI } from './api/client';

// Nowa rozmowa
const result = await agentAPI.chat("Przeanalizuj złoto na M15");
console.log(result.response);
console.log("Narzędzia użyte:", result.tool_calls);

// Kontynuacja
const result2 = await agentAPI.chat("A jak wygląda makro?", result.thread_id);
```

---

## Telegram — komenda /agent

Bot Telegram obsługuje komendę `/agent` z pełną pamięcią konwersacji per użytkownik:

```
/agent Przeanalizuj XAU/USD na M15
/agent Daj mi sygnał tradingowy z kapitałem 5000 PLN
/agent Jakie ważne newsy są dzisiaj?
/agent Czy setup jest dobry do wejścia LONG?
/agent reset   ← kasuje historię rozmowy
```

Thread ID jest zapisywany per `user_id` Telegrama w bazie danych (`agent_threads`),
więc agent **pamięta rozmowę między sesjami** (nawet po restarcie bota).

---

## Pamięć agenta

Agent korzysta z dwóch poziomów pamięci:

1. **Wątki (threads)** — OpenAI Assistants API przechowuje pełną historię konwersacji
   w chmurze OpenAI. Każdy użytkownik Telegram / każda sesja API ma swój wątek.

2. **Baza danych** — `agent_threads` tabela w SQLite/Turso przechowuje mapowanie
   `user_id → thread_id`, co umożliwia kontynuację rozmowy po restarcie aplikacji.

---

## Aktualizacja instrukcji agenta

Jeśli zmieniłeś `AGENT_INSTRUCTIONS` lub `AGENT_TOOLS_SCHEMA` w `src/openai_agent.py`,
zaktualizuj asystenta jedną linijką kodu:

```python
from src.openai_agent import QuantSentinelAgent
agent = QuantSentinelAgent.get_instance()
agent.sync_assistant()  # Synchronizuje instrukcje i narzędzia z OpenAI
```

