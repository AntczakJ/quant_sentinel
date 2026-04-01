"""
notifier.py — pomocniczy moduł do wysyłania alertów Telegram.

Zapewnia prostą funkcję send_alert() używaną przez webhook_reciever.py
(serwer Flask przyjmujący alerty z TradingView).

Klucze są wczytywane z pliku .env przez python-dotenv.
Nie używaj tego modułu wewnątrz głównego bota — tam używaj context.bot.send_message()
lub send_telegram_alert() z scanner.py, żeby nie mnożyć punktów wejścia do API.
"""

import os
import requests
from dotenv import load_dotenv
from src.logger import logger

# Wczytujemy .env — potrzebne gdy notifier.py jest uruchamiany poza kontekstem main.py
load_dotenv()


def send_alert(message: str):
    """
    Wysyła wiadomość Markdown na skonfigurowany czat Telegram.

    Parametry:
        message — treść wiadomości w formacie Markdown Telegrama

    Używane przez webhook_reciever.py do przekazywania alertów TradingView.
    Błędy wysyłki są logowane na konsolę (nie rzucają wyjątku).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Błąd wysyłania: {e}")
