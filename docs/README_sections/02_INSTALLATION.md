# 📦 Instalacja i Konfiguracja

## Wymagania systemowe

- **Python 3.10+** (rekomendowana 3.11 lub 3.12)
- **pip** (menadżer pakietów)
- **Git** (do klonowania repozytorium)
- **Klucze API** do: Twelve Data, OpenAI, Telegram

## Instalacja

### Krok 1: Sklonuj repozytorium

```bash
git clone https://github.com/twoj_login/quant_sentinel.git
cd quant_sentinel
```

### Krok 2: Utwórz i aktywuj środowisko wirtualne

**Windows:**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**Linux/Mac:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### Krok 3: Zainstaluj zależności

```bash
pip install -r requirements.txt
```

### Krok 4: Konfiguracja zmiennych środowiskowych

Utwórz plik `.env` w głównym katalogu projektu:

```env
# --- TELEGRAM BOT ---
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789

# --- OPENAI (GPT-4o dla analizy) ---
OPENAI_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# --- TWELVE DATA (dane rynkowe) ---
TWELVE_DATA_API_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

# --- OPCJONALNIE: BAZA DANYCH W CHMURZE ---
# DATABASE_URL=libsql://nazwa.turso.io
# DATABASE_TOKEN=XXXXX
```

## Opis zmiennych konfiguracyjnych

| Zmienna | Obowiązkowe | Opis |
|---------|:-----------:|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Token bota od @BotFather na Telegramie |
| `TELEGRAM_CHAT_ID` | ✅ | ID czatu - uzyskaj przez @userinfobot |
| `OPENAI_API_KEY` | ✅ | Klucz do API OpenAI (GPT-4o) |
| `TWELVE_DATA_API_KEY` | ✅ | Klucz do Twelve Data (darmowy plan wystarczy) |
| `DATABASE_URL` | ❌ | Opcjonalnie: URL do Turso dla zdalnej bazy |
| `DATABASE_TOKEN` | ❌ | Token do Turso (jeśli używasz chmury) |

## Pozyskiwanie kluczy API

### 1. Telegram Token

1. Napisz do @BotFather na Telegramie
2. Komenda: `/newbot`
3. Postępuj zgodnie z instrukcjami
4. Skopiuj token do `.env`

### 2. Telegram Chat ID

1. Napisz do @userinfobot
2. Odpowiadać będzie ID Twojego czatu
3. Skopiuj do `TELEGRAM_CHAT_ID` w `.env`

### 3. OpenAI API Key

1. Przejdź na https://platform.openai.com/api-keys
2. Zaloguj się lub utwórz konto
3. Kliknij "Create new secret key"
4. Skopiuj klucz (pokazany tylko raz!)
5. Wklej do `OPENAI_API_KEY` w `.env`

### 4. Twelve Data API Key

1. Przejdź na https://twelvedata.com/
2. Zaloguj się lub utwórz darmowe konto
3. Przejdź do sekcji API Keys
4. Skopiuj klucz
5. Wklej do `TWELVE_DATA_API_KEY` w `.env`

## Weryfikacja instalacji

Po zainstalowaniu wszystkich zależności, sprawdź czy wszystko działa:

```bash
python -c "from src import config, database, smc_engine, ml_models, ai_engine; print('✅ Wszystkie moduły załadowane!')"
```

Jeśli zobaczysz `✅ Wszystkie moduły załadowane!`, jesteś gotowy do uruchomienia.

## Rozwiązywanie problemów z instalacją

### Problem: `ModuleNotFoundError: No module named 'torch'`

**Rozwiązanie:** PyTorch czasami wymaga specjalnych instalacji:

```bash
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Problem: `libsql-client` nie zainstaluje się

**Rozwiązanie:** Jeśli nie potrzebujesz Turso (zdalnej bazy), możesz pominąć ten pakiet:

```bash
pip install -r requirements.txt --ignore-installed libsql-client
```

### Problem: Brak dostępu do C++ compiler (Windows)

**Rozwiązanie:** Zainstaluj Visual C++ Build Tools z: https://visualstudio.microsoft.com/visual-cpp-build-tools/

---

## Co dalej?

Po pomyślnej instalacji przejdź do [⚡ Szybki Start (03_QUICKSTART.md)](03_QUICKSTART.md) aby uruchomić bota!

