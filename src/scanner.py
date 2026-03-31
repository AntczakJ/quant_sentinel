"""
scanner.py — autonomiczny skaner rynku i resolver transakcji.

Odpowiada za dwa zadania cykliczne uruchamiane przez job_queue w main.py:

  1. scan_market_task (co 5 minut):
       - Pobiera świeżą analizę SMC z Twelve Data
       - Wykrywa zmiany trendu i nowe strefy FVG
       - Wysyła alerty push na Telegram gdy coś się zmienia

  2. resolve_trades_task (co 2 minuty):
       - Pobiera aktualną cenę złota z Twelve Data
       - Sprawdza otwarte pozycje w bazie SQLite
       - Zamyka pozycje które osiągnęły TP lub SL
       - Wysyła powiadomienie o wyniku na Telegram

Naprawione błędy:
  - Usunięto podwójny system trackera (poprzednio scanner wywoływał zarówno
    tracker.py /trades.json jak i database.py /SQLite — pozycje były rozliczane dwukrotnie)
  - Jedynym źródłem prawdy jest teraz baza SQLite (database.py)
"""

import requests

from src.config import TOKEN, CHAT_ID, USER_PREFS, LAST_STATUS, TD_API_KEY
from src.smc_engine import get_smc_analysis


def send_telegram_alert(text: str):
    """
    Pomocnicza funkcja do wysyłania powiadomień push na Telegram.
    Używa bezpośredniego API (nie przez bibliotekę python-telegram-bot),
    co pozwala wywoływać ją synchronicznie z dowolnego miejsca.
    """
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        print(f"❌ Błąd wysyłki Telegram: {e}")

import asyncio
async def scan_market_task(context):
    """
    Zadanie cykliczne (co 5 min).
    Poprawione: FVG działa niezależnie od zmiany trendu.
    """
    while True:

        try:
            analysis = get_smc_analysis(USER_PREFS['tf'])

            if not analysis:
                return

            current_trend = analysis['trend']
            current_fvg = analysis['fvg']
            current_price = analysis['price']
            current_rsi = analysis['rsi']
            current_structure = analysis.get('structure', 'Stable')

            from src.database import NewsDB
            db = NewsDB()

            fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)

            if fail_rate > 75:
                print(f"🚫 [SCANNER] Ignoruję sygnał: RSI {current_rsi} przy {current_structure} ma {fail_rate}% strat.")
                return  # Kończymy zadanie, nie wysyłamy alertu

            # --- 1. ALERT ZMIANY TRENDU ---
            if LAST_STATUS["trend"] is not None and current_trend != LAST_STATUS["trend"]:
                struct_icon = "🏗️" if "ChoCH" in current_structure else "⚡"
                alert_msg = (
                    f"⚠️ *ZMIANA TRENDU: GOLD*\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"Nowy Kierunek: *{current_trend.upper()}*\n"
                    f"{struct_icon} Struktura: `{current_structure}`\n"
                    f"📊 RSI: `{current_rsi}` | Szansa na fail: `{fail_rate}%`\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📥 _Sprawdź DASHBOARD dla parametrów._"
                )
                send_telegram_alert(alert_msg)

            # --- 2. ALERT NOWEJ STREFY FVG (POPRAWIONE WCIĘCIE) ---
            # Sprawdzamy FVG niezależnie od tego, czy trend się zmienił!
            if (current_fvg not in ["None", "Brak", None] and current_fvg != LAST_STATUS["fvg"]):

                # FILTR "NA SERIO":
                # Ignorujemy komunikaty, które nie niosą informacji o kierunku
                fvg_lower = current_fvg.lower()

                if "bull" in fvg_lower or "up" in fvg_lower:
                    kierunek = "BULLISH 🟢 (Luka wzrostowa)"
                    is_serious = True
                elif "bear" in fvg_lower or "down" in fvg_lower:
                    kierunek = "BEARISH 🔴 (Luka spadkowa)"
                    is_serious = True
                else:
                    # Jeśli silnik SMC zwraca tylko "Detected", uznajemy to za zbyt mało precyzyjne
                    kierunek = f"WYKRYTO ({current_fvg})"
                    is_serious = False

                if is_serious:
                    tf = USER_PREFS.get('tf', 'M15')
                    fvg_msg = (
                        f"⚡ *ISTOTNY FVG: GOLD ({tf})*\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🧭 Typ: *{kierunek}*\n"
                        f"💰 Cena: `{current_price}$`\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🎯 *TARGET:* Cena prawdopodobnie wróci zamknąć tę lukę.\n"
                        f"💡 _Pamiętaj: FVG to magnes dla ceny (Imbalance)._"
                    )
                    send_telegram_alert(fvg_msg)

            # --- 3. AKTUALIZACJA STANU ---
            LAST_STATUS["trend"] = current_trend
            LAST_STATUS["fvg"] = current_fvg

            print("✅ [SCANNER] Skonczono cykl.")

        except Exception as e:

            print(f"❌ [SCANNER] Błąd: {e}")

        await asyncio.sleep(300)  # Czekaj 5 minut

async def resolve_trades_task(context):
    """
    Poprawiona wersja: Bezpieczne importy i obsługa błędów ceny.
    """
    # 1. IMPORT LOKALNY (Naprawia Circular Import)
    from src.database import NewsDB
    db = NewsDB()

    # 2. POBIERANIE CENY (Z zabezpieczeniem przed None)
    url = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={TD_API_KEY}"
    try:
        # Używamy sesji requests z krótkim timeoutem
        response = requests.get(url, timeout=5)
        data = response.json()

        price_raw = data.get('price')
        if price_raw is None:
            print(f"⚠️ [RESOLVER] Twelve Data nie zwróciło ceny: {data}")
            return

        current_price = float(price_raw)
        print(f"🔍 [RESOLVER] Aktualna cena XAU/USD: {current_price}")

    except Exception as e:
        print(f"❌ [RESOLVER] Błąd sieci/ceny: {e}")
        return

    # 3. POBIERANIE POZYCJI
    try:
        open_trades = db.get_open_trades()
        if not open_trades:
            return  # Brak pozycji - kończymy cicho

        for trade in open_trades:
            # Rozpakowanie krotki (upewnij się, że Twoje db.get_open_trades() zwraca 5 wartości)
            t_id, direction, entry, sl, tp = trade
            status = None

            # 4. LOGIKA ROZSTRZYGNIĘCIA
            # Używamy strip() i upper(), żeby wyeliminować błędy w pisowni "LONG " vs "LONG"
            dir_clean = str(direction).strip().upper()

            if "LONG" in dir_clean:
                if current_price >= float(tp):
                    status = "PROFIT"
                elif current_price <= float(sl):
                    status = "LOSS"
            elif "SHORT" in dir_clean:
                if current_price <= float(tp):
                    status = "PROFIT"
                elif current_price >= float(sl):
                    status = "LOSS"

            # 5. AKTUALIZACJA I POWIADOMIENIE
            if status:
                db.update_trade_status(t_id, status)

                icon = "✅" if status == "PROFIT" else "❌"
                msg = (
                    f"{icon} *POZYCJA ROZSTRZYGNIĘTA!*\n"
                    f"ID: `{t_id}` | Kierunek: {direction}\n"
                    f"Wynik: *{status}*\n"
                    f"Wejście: `{entry}` | Wyjście: `{current_price}`"
                )
                # Wysyłamy przez context.bot (asynchronicznie)
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                print(f"💰 [RESOLVER] Zamknięto pozycję {t_id} jako {status}")

    except Exception as e:
        print(f"🚨 [RESOLVER] Błąd podczas sprawdzania pozycji: {e}")