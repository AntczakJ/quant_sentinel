"""
run.py — punkt startowy aplikacji z auto-instalacją zależności.

Uruchamia bota w następującej kolejności:
  1. Sprawdza i instaluje brakujące biblioteki z requirements.txt
  2. Wysyła Dashboard z menu na Telegram w osobnym wątku (nie blokuje startu)
  3. Uruchamia głównego bota (src/main.py → run_bot())

Użycie:
    python run.py

Zamiast bezpośredniego `python src/main.py`, uruchamiaj zawsze przez run.py —
auto-instalacja upewnia się że środowisko jest kompletne przed startem.
"""

import os
import sys
import subprocess
import threading
import time
import requests
import json

from src.logger import logger


def install_requirements():
    """
    Automatycznie instaluje wszystkie biblioteki z requirements.txt.
    Wywoływane przy każdym starcie — pip pomija paczki które są już zainstalowane,
    więc nie wydłuża znacząco czasu uruchomienia przy kolejnych startach.
    """
    req_file = "requirements.txt"
    if os.path.exists(req_file):
        logger.info("📦 Sprawdzam i instaluję biblioteki z requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
            logger.info("✅ Biblioteki gotowe.")
        except Exception as e:
            logger.info(f"❌ Błąd instalacji: {e}")
    else:
        # Fallback — instalujemy minimalny zestaw gdy requirements.txt nie istnieje
        logger.warning("⚠️ Nie znaleziono requirements.txt - instaluję zestaw standardowy...")
        libs = [
            "python-telegram-bot", "yfinance", "pandas-ta",
            "python-dotenv", "requests", "pandas"
        ]
        for lib in libs:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
            except Exception:
                pass


def alert_start():
    """
    Wysyła powiadomienie startowe z menu Dashboard na Telegram.

    Czeka 5 sekund żeby bot zdążył się zainicjować i połączyć z API Telegrama,
    a następnie wysyła wiadomość z interaktywnym menu przez bezpośrednie API.

    Uruchamiane w osobnym wątku daemon — nie blokuje głównego wątku bota.
    """
    # Czekamy na zainicjalizowanie bota przed wysłaniem powiadomienia
    time.sleep(5)

    from src.config import TOKEN, CHAT_ID
    from src.interface import main_menu

    if TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        # Serializujemy obiekt InlineKeyboardMarkup do JSON dla raw API
        reply_markup = json.dumps(main_menu().to_dict())

        data = {
            "chat_id": CHAT_ID,
            "text": (
                "🚀 *SENTINEL PRO ONLINE*\n"
                "System sprawdzony, analiza SMC aktywna. Dashboard poniżej:"
            ),
            "parse_mode": "Markdown",
            "reply_markup": reply_markup
        }
        try:
            requests.post(url, data=data, timeout=10)
            logger.info("✅ Wysłano Dashboard na Telegram.")
        except Exception as e:
            logger.info(f"❌ Nie udało się wysłać powiadomienia: {e}")


if __name__ == "__main__":
    # Krok 1: upewnij się że wszystkie zależności są zainstalowane
    install_requirements()

    # Krok 2: wyślij Dashboard w tle (daemon — zakończy się razem z botem)
    threading.Thread(target=alert_start, daemon=True).start()

    # Krok 3: uruchom głównego bota
    logger.info("🚀 QUANT SENTINEL BOOTING...")
    try:
        from src.main import run_bot
        run_bot()
    except KeyboardInterrupt:
        logger.info("⚠️ Bot przerwany przez użytkownika (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ KRYTYCZNY BŁĄD: {e}")
        logger.error("Sprawdź logi powyżej i upewnij się że wszystkie zmienne .env są ustawione")
        sys.exit(1)
