"""
finance.py — obliczenia finansowe i zarządzanie ryzykiem.

Odpowiada za:
  - Przeliczanie kapitału użytkownika na USD (dla walut PLN/EUR/GBP)
  - Obliczanie wielkości pozycji (lot size) na podstawie reguły 1% ryzyka
  - Wyznaczanie poziomów Stop Loss i Take Profit

Naprawione błędy:
  - Usunięto circular import (poprzednio ten plik importował z src.main,
    a src.main importował z src.finance — powodowało to ImportError przy starcie).
  - Kapitał i waluta są teraz przekazywane jako parametry funkcji,
    a nie pobierane przez import ze stanu globalnego.
"""

import requests


def get_fx_rate(base: str = "USD", target: str = "PLN") -> float:
    """
    Pobiera aktualny kurs walutowy z Yahoo Finance (np. USD/PLN).

    Parametry:
        base   — waluta bazowa (np. "USD")
        target — waluta docelowa (np. "PLN")

    Zwraca:
        Kurs wymiany jako float, lub 4.00 jako wartość awaryjna gdy API nie odpowie.
    """
    try:
        import yfinance as yf
        symbol = f"{base}{target}=X"
        data = yf.Ticker(symbol).history(period="1d")
        if not data.empty:
            return round(float(data['Close'].iloc[-1]), 4)
        return 4.00
    except Exception:
        return 4.00


def calculate_position(analysis_data: dict, balance: float, user_currency: str,
                       td_api_key: str) -> dict:
    """
    SMC MASTER VERSION: Celuje w Order Block i domknięcie FVG przy zachowaniu RR.
    """
    # Dane z silnika SMC
    current_price = analysis_data['price']
    trend = analysis_data['trend']
    fvg_size = analysis_data.get('fvg_size', 0)
    ob_price = analysis_data.get('ob_price', current_price)  # Jeśli brak OB, użyj ceny rynkowej
    eq_level = analysis_data.get('eq_level', current_price)

    # --- 1. WALUTY (ZOSTAJE) ---
    balance_in_usd = balance
    if user_currency != "USD":
        try:
            rate_url = f"https://api.twelvedata.com/price?symbol=USD/{user_currency}&apikey={td_api_key}"
            r = requests.get(rate_url, timeout=5).json()
            rate = float(r.get('price', 4.0))
            balance_in_usd = balance / rate
        except:
            balance_in_usd = balance / 4.0

    # --- 2. INTELIGENTNE WEJŚCIE I SL (ORDER BLOCK) ---
    # Sugerujemy wejście na Order Blocku, nie na "teraz"
    entry_target = ob_price

    if trend == 'bull':
        direction = "LONG"
        # SL ustawiamy 2$ poniżej Order Blocka (bezpieczniej niż sztywne 5$)
        sl_buffer = 1.0 if analysis_data.get('trend') == 'bear' else 2.0
        sl = round(entry_target - sl_buffer, 2)
        # TP celuje w FVG lub Equilibrium
        tp_target = current_price + fvg_size if fvg_size > 0 else eq_level
        tp = round(max(tp_target, entry_target + 3.0), 2)
        logic = "OB Entry + FVG Target"
    else:
        direction = "SHORT"
        # Jeśli ogólny trend jest Bull (wzrostowy), a my próbujemy Shorta,
        # dajemy ciasny SL (1.0$), żeby szybciej wyjść z błędnego setupu.
        sl_buffer = 1.0 if analysis_data.get('trend') == 'bull' else 2.0
        sl = round(entry_target + sl_buffer, 2)
        tp_target = current_price - fvg_size if fvg_size > 0 else eq_level
        tp = round(min(tp_target, entry_target - 3.0), 2)
        logic = "OB Entry + FVG Target"

    # --- 3. DYNAMICZNY LOT (1% RYZYKA) ---
    risk_usd = balance_in_usd * 0.01
    dist = abs(entry_target - sl)
    # Wzór: Ryzyko / (Dystans SL * 100 uncji)
    lot_size = round(risk_usd / (dist * 100), 2) if dist > 0 else 0.01
    if lot_size < 0.01: lot_size = 0.01

    return {
        'lot': lot_size,
        'sl': sl,
        'tp': tp,
        'entry': entry_target,
        'direction': direction,
        'logic': logic
    }