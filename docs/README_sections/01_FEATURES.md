# ✨ Funkcjonalności QUANT SENTINEL

## 📐 Analiza SMC (Smart Money Concepts)

Smart Money Concepts to zaawansowana metodologia analizy technicznej oparta na naturze rynków finansowych oraz sposobie działania dużych graczy (smart money).

### Kluczowe elementy SMC:

- **Swing High/Low** - Identyfikacja lokalnych ekstremów, które stanowią punkty odniesienia dla całej analizy
- **Liquidity Grab** - Wzorzec gdzie cena wybija poziom płynności, a następnie wraca w przeciwną stronę (tzw. "sztuczka animatorów rynku")
- **Market Structure Shift (MSS)** - Zmiana struktury rynku po Liquidity Grab, sygnalizująca zmianę kierunku trendu
- **Order Block** - Ostatnia świeca spadkowa przed wzrostem (dla bychów) lub wzrostowa przed spadkiem (dla niedźwiedzi) - strefa gdzie smart money wchodzi na pozycje
- **Fair Value Gap (FVG)** - Luka między świecami, gdzie brak cen transakcji (imbalance) - cena zwykle powraca do takiej luki
- **DBR/RBD formacje** - Drop-Base-Rally (akumulacja) i Rally-Base-Drop (dystrybucja)
- **SMT Divergence** - Sprzeczność między ruchem złota a USD/JPY (wskaźnik zmęczenia ruchu)

## 🔍 Wielointerwałowa weryfikacja

Analiza na trzech poziomach czasowych w celu potwierdzenia sygnału:

- **Główny interwał** - 5m / 15m / 1h / 4h (do wyboru przez użytkownika)
- **Interwał H1** - potwierdzenie na wyższym timeframe
- **Interwał M5** - potwierdzenie wejścia na niższym timeframe

Ten hierarchiczny system zmniejsza fałszywe sygnały o 40-60%.

## 🌍 Makroekonomiczny filtr

System automatycznie ocenia warunki makroekonomiczne poprzez:

- **USD/JPY Z-score** - odchylenie ceny USD/JPY od średniej ostatnich 20 świec
- **ATR (Average True Range)** - zmienność rynku

| Reżim | Warunek | Znaczenie | Akcja |
|---|---|---|---|
| 🟢 Zielony | Z-score < -1 i ATR > średni | Byczy dla złota | Preferuj długie pozycje |
| 🔴 Czerwony | Z-score > 1 i ATR < średni | Niedźwiedzi dla złota | Preferuj krótkie pozycje |
| 🟡 Neutralny | Pozostałe przypadki | Brak wyraźnego kierunku | Bądź ostrożny |

## 🤖 Sztuczna inteligencja (GPT-4o)

Zaawansowana analiza przy użyciu modelu GPT-4o od OpenAI:

- **Ocena konfluencji** - Punktacja 0-10 na podstawie liczby zgodnych wskaźników
- **Kontekst historyczny** - System analizuje ostatnie 5 porażek, aby unikać tych samych błędów
- **Interpretacja newsów** - Automatyczna analiza wiadomości finansowych i ich wpływu na złoto
- **Sentyment rynkowy** - Ocena nastrojów rynkowych oparta na zdywersyfikowanych źródłach

## ⚡ Automatyczne generowanie sygnałów

System pracuje 24/7 z automatycznym cyklem analizy:

- Co **5 minut** - Skaner rynku sprawdza zmiany trendu, nowe FVG, Liquidity Grab, DBR/RBD, zmiany reżimu makro
- Co **15 minut** - Automatyczna analiza Quant PRO (kompletna analiza + ocena AI)
- Co **2 minuty** - Resolver pozycji - sprawdzenie otwartych transakcji, aktualizacja statusu, zapis okoliczności strat

## 🧠 Samouczenie i optymalizacja

System nie tylko handluje, ale również **uczy się ze swoich wyników**:

### Statystyki wzorców
Każdy sygnał otrzymuje unikalny wzorzec (np. `LONG_LiquidityGrab+MSS_bullish`). Po zamknięciu transakcji aktualizowane są liczniki wygranych/przegranych dla tego wzorca.

### Blokowanie słabych wzorców
Waga wzorca = `win_rate × 1.5`. Jeśli waga < 0.5 (czyli win_rate < 33%), sygnał jest automatycznie odrzucany.

### Dynamiczna optymalizacja parametrów
Co godzinę bot analizuje ostatnie 100 transakcji i dobiera wartości:
- `risk_percent` - procent ryzyka na transakcję
- `min_profit_usd` - minimalny zysk w dolarach
- `min_tp_distance_mult` - mnożnik dystansu Take Profit

### Feedback Loop dla AI
Przy każdej analizie Quant PRO bot przekazuje do GPT-4o listę ostatnich 5 porażek z kontekstem rynkowym, aby model unikał powtarzania błędów.

### Zapis okoliczności straty
Gdy pozycja jest zamykana na Stop Loss, resolver zapisuje:
- Bieżąca cena
- Trend rynkowy
- Wartości RSI, MACD, ATR
- Struktura SMC
- Obecne FVG
- Typ liquidity graba
- Reżim makro

Te dane są później analizowane do identyfikacji wspólnych powodów strat.

## 📦 Pozostałe funkcjonalności

### Pełna historia transakcji
- Baza SQLite zawiera wszystkie transakcje z parametrami
- Łatwy dostęp do historii dla analizy performance
- Automatyczne kopie zapasowe

### Powiadomienia na Telegram
Interaktywny bot Telegram z powiadomieniami o:
- Zmianach trendu (na głównym interwale i H1)
- Liquidity Grab (bullish/bearish)
- Formacjach DBR/RBD
- Zmianach reżimu makroekonomicznego
- Nowych sygnałach z oceną AI ≥ 8/10

### Interaktywne menu z przyciskami inline
- Menu główne z szybkim dostępem do funkcji
- Przyciski do zmiany ustawień
- Wykresy ceny generowane na żądanie
- Łatwe przejście między interwałami

---

**Dzięki tym mechanizmom bot z czasem staje się coraz bardziej selektywny i lepiej dostosowuje się do zmieniających się warunków rynkowych.**

