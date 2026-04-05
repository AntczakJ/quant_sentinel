# 🚀 Szybki start na nowym urządzeniu

## 1. Klonowanie i środowisko

```bash
git clone <repo-url> quant_sentinel
cd quant_sentinel

# Python (Windows)
python -m venv .venv
.venv\Scripts\activate

# Python (Linux/Mac)
python3 -m venv .venv
source .venv/bin/activate

# Instalacja zależności
pip install -r requirements.txt
```

## 2. Konfiguracja sekretów

```bash
# Skopiuj wzorzec i uzupełnij swoje klucze API
cp .env.example .env
# Otwórz .env i wpisz klucze: TELEGRAM, OPENAI, TWELVE_DATA
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev       # dev server na http://localhost:5173
# lub
npm run build     # build produkcyjny
```

## 4. Uruchomienie

```bash
# Backend API (FastAPI na porcie 8000)
python api/main.py

# Telegram bot + scheduler
python run.py

# Oba naraz
python run.py &
python api/main.py
```

## 5. Trening modeli

Modele są już wytrenowane i dostępne po `git pull` w katalogu `models/`:
- `lstm.keras` / `lstm.h5` — model LSTM
- `xgb.pkl` — XGBoost
- `lstm_scaler.pkl` — scaler dla LSTM
- `rl_agent.keras` — agent RL

Aby retrenować:

```bash
# Wszystkie modele naraz
python train_all.py

# Tylko RL agent
python train_rl.py

# Testy regresji (szybkie)
python tests/run_quick_tests.py

# Pełne testy
python tests/run_all_tests.py
```

## 6. Baza danych

Baza `data/sentinel.db` jest śledzona w git — po pull masz całą historię sygnałów i transakcji.

Jeśli używasz Turso/libsql (produkcja), ustaw w `.env`:
```
DATABASE_URL=libsql://your-db.turso.io
TURSO_AUTH_TOKEN=your_token
```

## ⚠️ Uwagi

- `.env` **NIGDY** nie trafia do git — zawiera sekrety
- `.venv/` — środowisko wirtualne tworz lokalnie, nie jest w repo
- `cache/` — wypełnia się automatycznie przy pierwszym uruchomieniu
- `logs/` — generowane na bieżąco

## Struktura plików po pull

```
quant_sentinel/
├── models/           ← wytrenowane modele ML (w git)
│   ├── lstm.keras
│   ├── lstm.h5
│   ├── lstm_scaler.pkl
│   ├── rl_agent.keras
│   └── xgb.pkl
├── data/
│   ├── sentinel.db   ← baza danych (w git)
│   └── test_sentinel.db
├── src/              ← kod Python
├── api/              ← FastAPI
├── frontend/src/     ← React/TypeScript
├── train_all.py      ← skrypt treningowy
├── train_rl.py       ← trening RL
├── requirements.txt  ← zależności Python
├── .env.example      ← wzorzec konfiguracji
└── .env              ← TWOJE sekrety (NIE w git!)
```

