# 📑 QUANT SENTINEL — Indeks Dokumentacji

**Wersja:** 2.5 | **Data:** 2026-04-05 | **Status:** ✅ Production Ready

---

## 🚀 Szybki Start

Nowy? Zacznij tutaj:

1. **[02_INSTALLATION.md](README_sections/02_INSTALLATION.md)** ← Instalacja (5 min)
2. **[03_QUICKSTART.md](README_sections/03_QUICKSTART.md)** ← Uruchomienie (5 min)
3. **[01_FEATURES.md](README_sections/01_FEATURES.md)** ← Funkcjonalności (10 min)

---

## 📚 Pełny Spis Treści

### 🎯 Dla Początkujących

| Dokument | Opis | Czas |
|----------|------|------|
| [02_INSTALLATION.md](README_sections/02_INSTALLATION.md) | Instalacja, konfiguracja, klucze API | 15 min |
| [03_QUICKSTART.md](README_sections/03_QUICKSTART.md) | Szybki start, pierwsze kroki, troubleshooting | 10 min |
| [01_FEATURES.md](README_sections/01_FEATURES.md) | Funkcjonalności, możliwości, samouczenie | 20 min |

### 🔧 Dla Deweloperów

| Dokument | Opis | Czas |
|----------|------|------|
| [05_HOW_IT_WORKS.md](README_sections/05_HOW_IT_WORKS.md) | Architektura, pipeline, algorytmy | 30 min |
| [04_API_REFERENCE.md](README_sections/04_API_REFERENCE.md) | REST API, WebSocket, endpointy | 20 min |
| [06_ADVANCED.md](README_sections/06_ADVANCED.md) | Testing, debugging, contributing | 30 min |
| [BACKEND_STARTUP_GUIDE.md](BACKEND_STARTUP_GUIDE.md) | Poradnik uruchamiania backendu | 10 min |

### 📊 Architektura & Decyzje

| Dokument | Opis |
|----------|------|
| [ADR_001_DECISIONS.md](ADR_001_DECISIONS.md) | Architecture Decision Records |
| [RAPORT_V2.3.md](RAPORT_V2.3.md) | Release notes v2.3 |
| [ML_ENSEMBLE_INTEGRATION.md](ML_ENSEMBLE_INTEGRATION.md) | Integracja modeli ML Ensemble |
| [LIVE_DATA_INTEGRATION.md](LIVE_DATA_INTEGRATION.md) | Integracja danych rynkowych (Twelve Data) |

### 🔧 Rozwiązywanie Problemów

| Dokument | Opis |
|----------|------|
| [FRONTEND_FIX_NETWORK_ERROR.md](FRONTEND_FIX_NETWORK_ERROR.md) | Naprawianie błędów sieciowych frontendu |
| [PORTFOLIO_SIGNALS_FIX.md](PORTFOLIO_SIGNALS_FIX.md) | Naprawianie portfolio i sygnałów |
| [TRADES_PORTFOLIO_FIXES.md](TRADES_PORTFOLIO_FIXES.md) | Naprawianie handlu i portfela |

---

## 🤖 Machine Learning & Trenowanie

### Pipeline ML (nowe w v2.5)

System składa się z **4 modeli** połączonych w ensemble:

| Model | Plik | Opis |
|-------|------|------|
| **XGBoost** | `src/ml_models.py` | Klasyfikacja kierunku (18 cech, walk-forward validation) |
| **LSTM** | `src/ml_models.py` | Sieć neuronowa sekwencyjna (60-step, persystentny scaler) |
| **Double DQN** | `src/rl_agent.py` | Agent RL z target network (3 akcje: hold/buy/sell) |
| **Ensemble** | `src/ensemble_models.py` | Fuzja SMC + LSTM + XGB + DQN z dynamicznymi wagami |

### Trenowanie

```bash
# Pełny pipeline (XGBoost + LSTM + DQN + Bayesian Opt + Backtest)
python train_all.py

# Tylko DQN
python train_rl.py

# Tylko backtest
python -m src.backtest

# Opcje zaawansowane
python train_all.py --rl-episodes 1000      # Więcej epizodów RL
python train_all.py --skip-rl --skip-bayes   # Szybki trening (bez RL)
```

### Self-Learning (ciągłe doskonalenie)

Po uruchomieniu bota (`python run.py`), system automatycznie:
- Aktualizuje **wagi czynników** po każdym zamkniętym trade'ze (`src/self_learning.py`)
- Optymalizuje **parametry tradingowe** (risk, TP distance, RR) co cykl uczenia
- Dostosowuje **wagi ensemble** — modele które mają rację dostają wyższą wagę
- Zapisuje **statystyki wzorców** — win rate per pattern, per session, per regime

### Konfiguracja ML w `.env`

```ini
ENABLE_ML=True          # Włącz modele ML
ENABLE_RL=True          # Włącz agenta DQN
ENABLE_BAYES=True       # Włącz optymalizację Bayesowską
DATABASE_URL=data/sentinel.db  # Lokalna baza (do trenowania)
```

---

## 🏗️ Struktura Projektu

```
quant_sentinel/
├── run.py                  # 🚀 Entrypoint bota Telegram
├── train_all.py            # 🧠 Master pipeline trenowania ML
├── train_rl.py             # 🤖 Trening agenta DQN
├── requirements.txt        # 📦 Zależności Python
│
├── src/                    # 🔧 Backend core
│   ├── main.py             # Orchestrator bota Telegram
│   ├── config.py           # Konfiguracja + .env
│   ├── database.py         # SQLite / Turso (libsql)
│   ├── smc_engine.py       # Analiza SMC (Smart Money Concepts)
│   ├── finance.py          # Zarządzanie ryzykiem + pozycja
│   ├── ml_models.py        # XGBoost + LSTM (trening + predykcja)
│   ├── rl_agent.py         # Double DQN Agent
│   ├── ensemble_models.py  # Ensemble fuzja 4 modeli
│   ├── ensemble_voting.py  # Głosowanie + meta-learner
│   ├── self_learning.py    # Samouczenie + optymalizacja parametrów
│   ├── bayesian_opt.py     # Optymalizacja Bayesowska (GP + UCB)
│   ├── backtest.py         # Backtesting + metryki (Sharpe, F1, DD)
│   ├── scanner.py          # Skaner rynku + resolver pozycji
│   ├── data_sources.py     # Provider danych (Twelve Data + cache)
│   └── ...                 # Pozostałe moduły pomocnicze
│
├── api/                    # 🌐 FastAPI backend (Web UI)
│   ├── main.py             # FastAPI app + CORS
│   └── routers/            # market, signals, portfolio, models, analysis, training
│
├── frontend/               # ⚛️ React + TypeScript (Vite)
│   └── src/                # Components, hooks, store, api
│
├── models/                 # 💾 Wytrenowane modele
├── tests/                  # 🧪 Testy (57+ checks)
├── data/                   # 📊 Bazy danych
└── docs/                   # 📚 Dokumentacja
```

---

## 🧪 Testowanie

```bash
# Szybkie testy (< 30s)
python tests/run_quick_tests.py

# Pełny suite (10 modułów)
python tests/run_all_tests.py

# Comprehensive (51 checks + API + frontend)
python tests/run_comprehensive_tests.py

# Nowe komponenty (Double DQN, backtest, scaler, DB)
python tests/test_new_features.py

# Frontend type-check
cd frontend && npx tsc --noEmit
```

---

## 🔄 Uruchamianie

### Backend API (Web Dashboard)
```bash
python api/main.py
# lub: uvicorn api.main:app --reload --port 8000
```

### Bot Telegram + Scanner
```bash
python run.py
```

### Frontend
```bash
cd frontend && npm install && npm run dev
```

### Trenowanie ML
```bash
python train_all.py
```

---

## 📈 Nowe w V2.5 (2026-04-05)

- ✅ **Double DQN** — stabilniejszy trening RL z target network
- ✅ **Lepszy reward shaping** — nagroda za zrealizowany P/L
- ✅ **LSTM scaler persistence** — spójne skalowanie train/inference
- ✅ **Walk-forward validation** dla LSTM (5 foldów)
- ✅ **Moduł backtestowy** (`src/backtest.py`) — Accuracy, F1, Sharpe, MaxDD
- ✅ **Master training pipeline** (`train_all.py`) — jeden command dla 4 modeli
- ✅ **Optymalizacja Bayesowska** — automatyczny tuning parametrów
- ✅ **57 nowych testów** dla komponentów ML
- ✅ **Porządki** — usunięto 17 zbędnych plików z roota

### Historia wersji

| Wersja | Data | Zmiany |
|--------|------|--------|
| **v2.5** | 2026-04-05 | Double DQN, backtest, train_all.py, porządki |
| **v2.4** | 2026-04-04 | 7 bug fixes, live data, auto-resolve trades |
| **v2.3** | 2026-04-03 | Ensemble voting, advanced features |
| **v2.2** | 2026-03-15 | API & Frontend release |
| **v2.1** | 2026-02-01 | ML models optimization |
| **v2.0** | 2026-01-01 | Initial release |

---

## 🎯 FAQ

**P: Jak zainstalować?**
O: [02_INSTALLATION.md](README_sections/02_INSTALLATION.md)

**P: Jak uruchomić?**
O: [03_QUICKSTART.md](README_sections/03_QUICKSTART.md)

**P: Jak trenować modele?**
O: `python train_all.py` — patrz sekcja [Machine Learning](#-machine-learning--trenowanie)

**P: Jak używać API?**
O: [04_API_REFERENCE.md](README_sections/04_API_REFERENCE.md)

**P: Jak to działa?**
O: [05_HOW_IT_WORKS.md](README_sections/05_HOW_IT_WORKS.md)

**P: Jak testować?**
O: [06_ADVANCED.md#testing](README_sections/06_ADVANCED.md)

---

## 🔗 Linki

| Zasób | Link |
|-------|------|
| **API Docs** | http://localhost:8000/docs (po uruchomieniu) |
| **Frontend** | http://localhost:5173 (po uruchomieniu) |
| **Logi** | `logs/sentinel.log` |

---

*Ostatnia aktualizacja: 2026-04-05*
*Wersja: 2.5*
*Status: ✅ Production Ready*
