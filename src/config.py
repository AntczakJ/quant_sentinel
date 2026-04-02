"""
config.py — centralne miejsce konfiguracji bota.

Wszystkie klucze API i tokeny są wczytywane z pliku .env (przez python-dotenv),
nigdy nie są hardkodowane w kodzie źródłowym.

Struktura .env:
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
    OPENAI_API_KEY=...
    TWELVE_DATA_API_KEY=...
"""

import os
import threading
from dotenv import load_dotenv

# Wczytuje zmienne środowiskowe z pliku .env znajdującego się w katalogu głównym projektu
load_dotenv()

# --- KLUCZE API I TOKENY ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")       # Token bota Telegram (od @BotFather)
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")       # ID czatu, na który bot wysyła powiadomienia
OPENAI_KEY = os.getenv("OPENAI_API_KEY")      # Klucz do modeli OpenAI (GPT-4o)
TD_API_KEY = os.getenv("TWELVE_DATA_API_KEY") # Klucz do Twelve Data (dane rynkowe XAU/USD)

# --- PREFERENCJE UŻYTKOWNIKA ---
# Słownik trzymający bieżący stan ustawień sesji.
# Uwaga: to stan w pamięci — resetuje się przy restarcie bota.
# Trwałe ustawienia (np. kapitał) są przechowywane w bazie SQLite (database.py).
USER_PREFS = {
    "currency": "PLN",       # Waluta portfela użytkownika
    "capital": 5000.0,       # Kwota bazowa (używana jako fallback jeśli baza zawiedzie)
    "risk_pc": 1.0,          # Procent kapitału ryzykowany na jeden trade
    "tf": "15m",             # Aktywny interwał analizy (15m / 1h / 4h)
    "contract_size": 100,    # Wielkość kontraktu XTB Gold (1 lot = 100 uncji)
    "target_rr": 2.5         # Docelowy wskaźnik Risk/Reward
}

# --- PAMIĘĆ SKANERA ---
# Przechowuje ostatnio zaobserwowany stan rynku przez scanner.py.
# Używane do wykrywania zmian trendu i nowych stref FVG między skanami.
# THREAD-SAFE: chroni dostęp za pomocą Lock
LAST_STATUS_LOCK = threading.Lock()
LAST_STATUS = {
    "trend": None,  # Ostatni zaobserwowany trend ("bull" lub "bear")
    "fvg": None     # Ostatnia zaobserwowana strefa Fair Value Gap
}

# ================== Data sources ==================
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "twelve_data")   # 'twelve_data' or 'alpha_vantage'
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")

# ================== Machine Learning ==================
ENABLE_ML = os.getenv("ENABLE_ML", "False").lower() == "true"
ENABLE_RL = os.getenv("ENABLE_RL", "False").lower() == "true"
ENABLE_BAYES = os.getenv("ENABLE_BAYES", "False").lower() == "true"
ENABLE_ADVANCED_INDICATORS = os.getenv("ENABLE_ADVANCED_INDICATORS", "True").lower() == "true"
ENABLE_PATTERNS = os.getenv("ENABLE_PATTERNS", "True").lower() == "true"


def get_sym() -> str:
    """Zwraca symbol waluty portfela użytkownika (np. 'zł', '$', '€')."""
    return {"PLN": "zł", "USD": "$", "EUR": "€"}.get(USER_PREFS["currency"], "$")
