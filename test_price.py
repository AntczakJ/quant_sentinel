"""
test_price.py — narzędzie do testowania połączenia z Twelve Data API.

Uruchamia pętlę pobierającą aktualną cenę złota (XAU/USD spot) co 15 sekund
i wyświetla ją w konsoli ze znacznikiem czasu.

Przeznaczenie:
  - Weryfikacja poprawności klucza API przed uruchomieniem bota
  - Sprawdzenie czy Twelve Data odpowiada w akceptowalnym czasie
  - Ręczny monitoring ceny złota bez uruchamiania całego systemu

Uruchomienie:
    python test_price.py

Zatrzymanie: Ctrl+C

Uwaga: darmowy plan Twelve Data ma limit 800 zapytań/dzień.
Przy interwale 15s = 4 zapytania/minutę = 240/godzinę.
Nie zostawiaj skryptu uruchomionego na dłużej niż potrzebujesz.
"""

import requests
import time
from datetime import datetime

# Klucz API pobierany bezpośrednio — to plik testowy, nie integruje się z config.py
# W środowisku produkcyjnym zawsze używaj os.getenv() i pliku .env
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
SYMBOL = "XAU/USD"  # Złoto Spot (nie futures)


def watch_twelve_data():
    """
    Pętla nieskończona pobierająca cenę złota z Twelve Data co 15 sekund.
    Wyświetla cenę z lokalnym znacznikiem czasu lub komunikat błędu API.
    """
    print(f"🚀 TEST LIVE: Twelve Data dla {SYMBOL}...")
    print("-" * 50)

    url = f"https://api.twelvedata.com/price?symbol={SYMBOL}&apikey={API_KEY}"

    while True:
        try:
            response = requests.get(url, timeout=10).json()

            if "price" in response:
                price = response['price']
                local_time = datetime.now().strftime('%H:%M:%S')
                print(f"[{local_time}] 💰 CENA SPOT: {price} $")
            else:
                # API zwróciło błąd (np. przekroczony limit lub błędny klucz)
                print(f"❌ Błąd API: {response.get('message', 'nieznany błąd')}")
                break

        except Exception as e:
            print(f"❌ Błąd połączenia: {e}")

        # 15 sekund przerwy — bezpieczny interwał dla darmowego planu API
        time.sleep(15)


if __name__ == "__main__":
    watch_twelve_data()
