# 🤖 QUANT SENTINEL AI

> Zautomatyzowany system analizy XAUUSD z mechanizmem samouczenia

**QUANT SENTINEL AI** to zaawansowany bot Telegram analizujący rynek złota (XAUUSD) w oparciu o **Smart Money Concepts (SMC)**, makroekonomię oraz **sztuczną inteligencję (GPT-4o)**. Bot generuje sygnały handlowe, uczy się na własnych błędach, optymalizuje parametry ryzyka i automatycznie zbiera dane do dalszej analizy.

---

## 📋 Spis treści

1. [Funkcjonalności](#-funkcjonalności)
2. [Technologie](#-technologie)
3. [Instalacja](#-instalacja)
4. [Konfiguracja](#-konfiguracja)
5. [Uruchomienie](#-uruchomienie)
6. [Korzystanie z bota](#-korzystanie-z-bota)
7. [Jak to działa?](#-jak-to-działa)
8. [Mechanizmy samouczenia](#-mechanizmy-samouczenia)
9. [Struktura bazy danych](#-struktura-bazy-danych)
10. [Przykładowy output](#-przykładowy-output)
11. [Rozwiązywanie problemów](#-rozwiązywanie-problemów)
12. [Licencja](#-licencja)

---

## ✨ Funkcjonalności

### 📐 Analiza SMC (Smart Money Concepts)
- Wykrywanie Swing High/Low, Liquidity Grab, Market Structure Shift
- Identyfikacja Order Block, Fair Value Gap (FVG) oraz formacji DBR/RBD

### 🔍 Wielointerwałowa weryfikacja
- Główny interwał (5m / 15m / 1h / 4h) + H1 + M5 dla precyzyjnego wejścia

### 🌍 Makroekonomiczny filtr
- Reżim rynkowy (zielony / neutralny / czerwony) na podstawie USD/JPY Z-score i ATR

### 🤖 Sztuczna inteligencja (GPT-4o)
- Ocena konfluencji w skali 0–10 z uwzględnieniem historii strat
- Interpretacja newsów i sentymentu

### ⚡ Automatyczne generowanie sygnałów
- Co 15 minut bot samodzielnie analizuje rynek i zapisuje sygnały do bazy

### 🧠 Samouczenie i optymalizacja
- Statystyki wzorców (pattern stats) – blokowanie słabych setupów
- Dynamiczna optymalizacja parametrów (ryzyko %, minimalny zysk, dystans TP)
- Rekordy porażek z kontekstem rynkowym

### 📦 Pozostałe
- Pełna historia transakcji w bazie SQLite
- Powiadomienia na Telegram (alerty o zmianie trendu, Liquidity Grab, formacje DBR/RBD, nowy reżim makro)
- Interaktywne menu z przyciskami inline

---

## 🛠 Technologie

| Technologia | Zastosowanie |
|---|---|
| **Python 3.10+** | Język bazowy |
| **python-telegram-bot** | Obsługa bota Telegram |
| **Twelve Data API** | Dane rynkowe XAUUSD i USD/JPY |
| **OpenAI GPT-4o** | Analiza i ocena konfluencji |
| **FinBERT (Hugging Face)** | Szybka klasyfikacja sentymentu |
| **Pandas / Pandas_ta** | Przetwarzanie danych i wskaźniki techniczne |
| **SQLite** | Lokalna baza danych |
| **Flask** | Wbudowany webhook dla alertów TradingView (opcjonalnie) |

---

## 📦 Instalacja

**1. Sklonuj repozytorium**

```bash
git clone https://github.com/twoj_login/quant_sentinel.git
cd quant_sentinel
```

**2. Utwórz i aktywuj środowisko wirtualne**

```bash
python -m venv .venv

# Linux/Mac
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

**3. Zainstaluj zależności**

```bash
pip install -r requirements.txt
```

---

## ⚙️ Konfiguracja

Utwórz plik `.env` w głównym katalogu projektu:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
TWELVE_DATA_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

| Zmienna | Opis |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token od @BotFather |
| `TELEGRAM_CHAT_ID` | ID czatu (można uzyskać przez @userinfobot) |
| `OPENAI_API_KEY` | Klucz do API OpenAI (GPT-4o) |
| `TWELVE_DATA_API_KEY` | Klucz do Twelve Data (darmowy plan wystarczy) |

> ⚠️ **Uwaga:** wszystkie klucze są niezbędne do poprawnego działania.

---

## 🚀 Uruchomienie

```bash
python run.py
```

Bot wystartuje w trybie polling i automatycznie:

- Wyśle dashboard z menu na Twój czat
- Uruchomi w tle serwer Flask do obsługi webhooków (port 5000)
- Rozpocznie cykliczne zadania:

| Zadanie | Częstotliwość |
|---|---|
| Skaner rynku | co 5 minut |
| Resolver transakcji | co 2 minuty |
| Automatyczna analiza | co 15 minut |
| Optymalizacja parametrów | co godzinę |

> Aby zatrzymać bota, naciśnij `Ctrl+C` w konsoli.

---

## 💬 Korzystanie z bota

Po uruchomieniu na czacie pojawi się interaktywne menu.

### Komendy tekstowe

| Komenda | Opis |
|---|---|
| `/start` | Wyświetla menu główne i aktualny kapitał |
| `/cap KWOTA WALUTA` | Ustawia kapitał (np. `/cap 5000 PLN`) |
| `/stats` | Pokazuje statystyki: win rate, liczba TP/SL, ostatnie sygnały |
| `/chart` | Generuje wykres ceny złota dla aktywnego interwału |

### Przyciski w menu

| Przycisk | Opis |
|---|---|
| 🎯 ANALIZA QUANT PRO | Pełna analiza SMC + AI, generuje sygnał |
| 📊 STATUS SYSTEMU | Aktualny kapitał i ustawienia |
| 📰 NEWSY (XTB) | Pobiera i interpretuje najnowsze newsy finansowe |
| 🎭 SENTYMENT AI | Analiza nastrojów rynkowych (FinBERT + GPT) |
| ⏱ INTERWAŁ | Zmienia główny interwał analizy (5m / 15m / 1h / 4h) |
| 📈 WYKRES | Rysuje wykres ceny |
| ⚙️ PORTFEL | Umożliwia zmianę kapitału (skrót `/cap`) |
| 📖 POMOC | Wyświetla instrukcję |

### Przebieg analizy Quant PRO

Po wybraniu **🎯 ANALIZA QUANT PRO** bot:

1. Pobiera dane dla trzech interwałów (główny, H1, M5)
2. Oblicza wskaźniki SMC i reżim makro
3. Przekazuje kontekst do GPT-4o, który wystawia ocenę (0–10) i uzasadnienie
4. Jeśli ocena ≥ 5 → oblicza pozycję (lot, entry, SL, TP) i zapisuje do bazy
5. Wyświetla wyniki na czacie

---

## 🔬 Jak to działa?

### 1. Pobieranie danych
Bot korzysta z **Twelve Data API**, pobierając dane OHLCV dla XAUUSD oraz USD/JPY (proxy dla DXY). Dane są pobierane asynchronicznie dla trzech interwałów.

### 2. Analiza SMC (`smc_engine.py`)

| Element | Opis |
|---|---|
| **Swing High/Low** | Lokalne ekstrema (domyślnie okno 5 świec) |
| **Liquidity Grab** | Wybicie poziomu płynności z powrotem w przeciwną stronę |
| **Market Structure Shift (MSS)** | Zmiana struktury po Liquidity Grab |
| **Order Block** | Ostatnia świeca spadkowa przed wzrostem (bull) lub wzrostowa przed spadkiem (bear) |
| **Fair Value Gap (FVG)** | Luka między świecami i-2 a i (bullish/bearish) |
| **DBR/RBD** | Formacje Drop-Base-Rally / Rally-Base-Drop |
| **SMT Divergence** | Sprzeczność między złotem a USD/JPY |

### 3. Makroekonomiczny filtr

- **USD/JPY Z-score** – odchylenie od średniej ostatnich 20 świec
- **ATR** – średni prawdziwy zakres (zmienność)

| Reżim | Warunek | Znaczenie |
|---|---|---|
| 🟢 Zielony | Z-score < -1 i ATR > śr. ATR | Byczy dla złota |
| 🔴 Czerwony | Z-score > 1 i ATR < śr. ATR | Niedźwiedzi dla złota |
| 🟡 Neutralny | Pozostałe przypadki | Brak wyraźnego kierunku |

### 4. Obliczanie pozycji (`finance.py`)

- **Kierunek** – na podstawie konfluencji (Grab+MSS > DBR/RBD > Trend+FVG)
- **Entry** – zazwyczaj Order Block lub strefa bazy
- **SL** – dynamicznie: LONG poniżej OB/Swing Low, SHORT powyżej
- **TP** – domknięcie FVG, Swing High/Low lub min. ATR
- **Lot** – `1% kapitału / (dystans SL × 100)` (reguła 1% ryzyka)

### 5. Automatyczne zadania (`job_queue`)

- **Skaner rynku (co 5 min)** – sprawdza zmiany trendu, nowe FVG, Liquidity Grab, DBR/RBD, reżim makro
- **Resolver transakcji (co 2 min)** – sprawdza otwarte pozycje, aktualizuje status (PROFIT/LOSS), zapisuje okoliczności straty
- **Automatyczna analiza (co 15 min)** – generuje sygnał, zapisuje do bazy (powiadomienie tylko gdy ocena AI ≥ 8)
- **Optymalizacja parametrów (co godzinę)** – analizuje ostatnie 100 transakcji i dostraja `risk_percent`, `min_profit_usd`, `min_tp_distance_mult`

### 6. Moduły AI

- **FinBERT** – lokalna klasyfikacja sentymentu (Bullish / Bearish / Neutral)
- **GPT-4o** – głęboka analiza konfluencji, ocena setupu, interpretacja newsów, sugerowanie strategii

---

## 🧠 Mechanizmy samouczenia

System nie tylko generuje sygnały, ale również **uczy się na podstawie swoich wyników**.

| Mechanizm | Opis |
|---|---|
| **Statystyki wzorców** (`pattern_stats`) | Każdy sygnał otrzymuje unikalny wzorzec (np. `LONG_LiquidityGrab+MSS_bullish`). Po zamknięciu transakcji aktualizowane są liczniki wygranych/przegranych. |
| **Blokowanie słabych wzorców** | Waga wzorca = `win_rate × 1.5`. Jeśli waga < 0.5 (win_rate < 33%), sygnał jest odrzucany. |
| **Dynamiczna optymalizacja parametrów** | Co godzinę bot analizuje ostatnie 100 transakcji i dobiera wartości `risk_percent`, `min_profit_usd`, `min_tp_distance_mult` maksymalizujące średni zysk. |
| **Feedback Loop dla AI** | Przy każdej analizie Quant PRO bot przekazuje do GPT-4o listę ostatnich 5 porażek, aby model unikał tych samych błędów. |
| **Zapis okoliczności straty** | Gdy pozycja jest zamykana na SL, resolver zapisuje stan rynku (cena, trend, RSI, struktura, FVG) do późniejszej analizy. |

> Dzięki tym mechanizmom bot z czasem staje się coraz bardziej selektywny i lepiej dostosowuje się do zmieniających się warunków rynkowych.

---

## 🗄 Struktura bazy danych

Plik `data/sentinel.db` zawiera następujące tabele:

| Tabela | Opis |
|---|---|
| `trades` | Główna tabela transakcji: `id`, `timestamp`, `direction`, `entry`, `sl`, `tp`, `rsi`, `trend`, `structure`, `status`, `failure_reason`, `condition_at_loss`, `pattern` |
| `scanner_signals` | Sygnały wygenerowane przez skaner (do dalszej analizy) |
| `pattern_stats` | Zagregowane statystyki dla każdego wzorca: `count`, `wins`, `losses`, `win_rate` |
| `dynamic_params` | Aktualne wartości optymalizowanych parametrów: `risk_percent`, `min_profit_usd`, `min_tp_distance_mult` |
| `user_settings` | Kapitał użytkownika i preferencje (`balance`, `risk_percent`) |
| `processed_news` | Hasze przetworzonych alertów (deduplikacja) |

---

## 📊 Przykładowy output

Po naciśnięciu **🎯 ANALIZA QUANT PRO**:

```
🎯 WERDYKT QUANT PRO
━━━━━━━━━━━━━━
🏗️ STRUKTURA SMC (GŁÓWNY):
- Liquidity Grab: True (bullish) | MSS: True
- FVG: Bullish (+1.23$) | OB: 4650.00$
- DBR/RBD: DBR

🔍 POTWIERDZENIE M5:
- Trend: bull | Grab: True | MSS: True

🌍 MAKRO: Reżim: ZIELONY | USD/JPY Z-score: -1.24 | ATR: 12.96

🤖 ANALIZA AI:
WYNIK: 8/10
POWÓD: Silna konfluencja – Liquidity Grab + MSS na głównym interwale,
dodatkowo M5 potwierdza. Makro zielony sprzyja długim pozycjom. RSI w korekcie (44).
RADA: Wejście na Order Block M5 (4650$) z SL poniżej Swing Low.
━━━━━━━━━━━━━━
🚀 SYGNAŁ: LONG
📍 WEJŚCIE:    4650.00$
🛑 STOP LOSS:  4648.00$
✅ TAKE PROFIT: 4665.00$
📊 LOT: 0.12 (Liquidity Grab + MSS (Bullish))
━━━━━━━━━━━━━━
⚖️ STREFA: DISCOUNT | EQ: 4635.00
🧭 TREND M15/H1/M5: bull / bull / bull
📡 SMT: Brak
━━━━━━━━━━━━━━
📅 KALENDARZ:
⚠️ FOMC Statement (2025-04-15 14:00)
```

---

## 🔧 Rozwiązywanie problemów

**1. Bot nie odpowiada na komendy**
- Sprawdź, czy token w `.env` jest poprawny
- Upewnij się, że bot nie został zablokowany na czacie

**2. Błędy związane z Twelve Data**
- Sprawdź, czy klucz API jest aktywny i masz dostęp do symboli `XAU/USD` oraz `USD/JPY`
- Darmowy plan ma limit 8 zapytań/minutę – jeśli wystąpią przekroczenia, zmniejsz częstotliwość skanowania

**3. Błąd importu cyklicznego (circular import)**
- W plikach `scanner.py` i `self_learning.py` importy są lokalne (wewnątrz funkcji) – nie zmieniaj ich na globalne

**4. Bot nie generuje automatycznych sygnałów**
- Sprawdź, czy w `main.py` w `run_bot()` dodano zadanie `auto_analyze_and_learn` do `job_queue`
- W konsoli powinny pojawiać się komunikaty `📡 [AUTO-LEARN] Zapisano sygnał ...`

**5. Baza danych nie aktualizuje się**
- Upewnij się, że katalog `data/` ma prawa zapisu
- Możesz ręcznie sprawdzić zawartość tabeli `trades` za pomocą SQLite Browser

**6. Wysokie opóźnienia przy analizie**
- Zmniejsz `outputsize` w zapytaniach do Twelve Data (domyślnie 50)
- Rozważ wyłączenie zbędnych analiz (np. DBR/RBD) lub zwiększenie interwału głównego

---

## 📄 Licencja

Projekt jest udostępniany na licencji **MIT**. Możesz go dowolnie modyfikować i wykorzystywać komercyjnie.

---

## 🙏 Podziękowania

- [Twelve Data](https://twelvedata.com) – za stabilne API z danymi rynkowymi
- [OpenAI](https://openai.com) – za model GPT-4o
- [Hugging Face](https://huggingface.co) – za model FinBERT

---

*Ostatnia aktualizacja: kwiecień 2025*