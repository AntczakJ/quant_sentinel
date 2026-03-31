# 🦅 Quant Sentinel AI – Gold Trading Assistant

**Quant Sentinel** to zaawansowany ekosystem tradingowy oparty na Pythonie, zaprojektowany do precyzyjnej analizy rynku złota (**XAU/USD**). System łączy metodologię **Smart Money Concepts (SMC)** z nowoczesną analityką **AI (GPT-4o)**, dostarczając sygnały i analizy bezpośrednio na Telegram.

---

## 🌟 Kluczowe Funkcje

### 1. Inteligentna Analiza PRO
* **Multi-Timeframe Confluence:** Automatyczna weryfikacja zgodności trendu na interwałach M15 i H1. Jeśli trendy są sprzeczne, system blokuje trade w celu ochrony kapitału.
* **SMC Engine:** Wykrywanie struktur rynkowych, Fair Value Gaps (FVG) oraz analiza wskaźnika RSI.
* **AI Verdict:** Każdy setup jest procesowany przez model GPT-4o, który ocenia ryzyko i sentyment rynkowy.

### 2. Autonomiczny Skaner i Tracker
* **Real-time Monitoring:** Skaner w tle monitoruje cenę złota i automatycznie rozlicza otwarte pozycje (PROFIT/LOSS) w bazie danych.
* **SQLite Database:** Lokalna baza danych przechowująca historię transakcji, ustawienia portfela oraz logi systemowe.

### 3. Machine Learning (Feedback Loop)
* **Retrospekcja:** AI analizuje historię strat (LOSS) zapisaną w bazie danych i wykorzystuje te wnioski przy generowaniu kolejnych analiz, aby unikać powtarzania błędów rynkowych.

---

## 📂 Struktura Katalogów

```text
gold_dxy_analyzer/
├── data/
│   └── sentinel.db          # Baza danych SQLite
├── src/
│   ├── ai_engine.py        # Integracja z modelami OpenAI/Gemini
│   ├── config.py           # Klucze API i stałe konfiguracyjne
│   ├── database.py         # Zarządzanie strukturą SQL i statystykami
│   ├── interface.py        # Menu, przyciski i UI Telegrama
│   ├── scanner.py          # Silnik skanera i automatyczny tracker
│   └── smc_engine.py       # Algorytmy techniczne (RSI, Trend, SMC)
├── main.py                 # Główny punkt startowy aplikacji
└── requirements.txt        # Lista zależności Python
```

---

## ⚙️ Instrukcja Uruchomienia

### Krok 1: Instalacja zależności

Wymagany Python 3.10 lub nowszy. Otwórz terminal w folderze projektu i wpisz:

```bash
pip install -r requirements.txt
```

### Krok 2: Konfiguracja API

Wypełnij plik `src/config.py` swoimi danymi:

| Zmienna | Opis |
|---|---|
| `TOKEN` | Token bota od @BotFather |
| `TD_API_KEY` | Klucz API z Twelve Data |
| `OPENAI_API_KEY` | Klucz do modelu GPT |
| `CHAT_ID` | Twój unikalny identyfikator Telegram |

### Krok 3: Inicjalizacja

Upewnij się, że w folderze głównym istnieje katalog `data/`. Baza danych zostanie zainicjowana automatycznie przy pierwszym starcie.

> ⚠️ **Uwaga:** Przy zmianie struktury tabel (np. dodanie kolumn RSI), należy zresetować tabelę trades w DB Browser komendą:
> ```sql
> DROP TABLE trades;
> ```

### Krok 4: Start bota

```bash
python main.py
```

---

## 📊 Komendy Bota

| Komenda | Opis |
|---|---|
| `/start` | Uruchamia główny dashboard i menu sterowania |
| `/cap [kwota] [waluta]` | Ustawia kapitał startowy (np. `/cap 5000 USD`) |
| `/stats` | Wyświetla Win Rate, historię ostatnich sygnałów i stan portfela |
| `/status` | Szybki podgląd parametrów pracy bota i połączenia z bazą |

---

## 📦 requirements.txt

```text
python-telegram-bot
matplotlib
yfinance
requests
flask
pandas
openai
```

---

## 🛡️ Ostrzeżenie o ryzyku

> Handel na instrumentach CFD (Złoto) wiąże się z wysokim ryzykiem utraty kapitału. **Quant Sentinel AI** jest narzędziem wspomagającym analizę techniczną, a nie gotowym systemem inwestycyjnym. Inwestuj odpowiedzialnie.
