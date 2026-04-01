"""
scanner.py — autonomiczny skaner rynku i resolver transakcji.

Naprawiono:
  - scan_market_task teraz zapisuje sygnały do scanner_signals
  - resolve_trades_task zapisuje powód i okoliczności przegranej do trades
  - processed_news jest teraz wypełniana przy alertach FVG/trend
"""

import hashlib
import requests

from src.config import TOKEN, CHAT_ID, USER_PREFS, LAST_STATUS, TD_API_KEY
from src.smc_engine import get_smc_analysis

def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

def send_telegram_alert(text: str):
    """
    Pomocnicza funkcja do wysyłania powiadomień push na Telegram.
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


async def scan_market_task(context):
    """
    Zadanie cykliczne (co 5 min).
    - Wykrywa zmiany trendu i nowe strefy FVG
    - Zapisuje sygnały do scanner_signals
    - Deduplikuje alerty przez processed_news
    """
    try:
        analysis = get_smc_analysis(USER_PREFS['tf'])

        if not analysis:
            return

        current_trend     = analysis['trend']
        current_fvg       = analysis['fvg']
        current_price     = analysis['price']
        current_rsi       = analysis['rsi']
        current_structure = analysis.get('structure', 'Stable')
        current_ob        = analysis.get('ob_price', current_price)
        current_sl        = analysis.get('sl', current_price)
        current_tp        = analysis.get('tp', current_price)

        from src.database import NewsDB
        db = NewsDB()

        fail_rate = db.get_fail_rate_for_pattern(current_rsi, current_structure)

        if fail_rate > 75:
            print(f"🚫 [SCANNER] Ignoruję sygnał: RSI {current_rsi} przy {current_structure} ma {fail_rate}% strat.")
            return

        # ========== 🧠 FILTR WAGI WZORCA ==========
        # Budujemy unikalny identyfikator wzorca na podstawie kierunku, struktury i typu FVG
        direction_str = "LONG" if analysis['trend'] == "bull" else "SHORT"
        pattern = f"{direction_str}_{analysis.get('structure', 'unknown')}_{analysis.get('fvg_type', 'None')}"

        from src.self_learning import get_pattern_adjustment
        weight = get_pattern_adjustment({"pattern": pattern})
        if weight < 0.5:
            print(f"🚫 [SCANNER] Pomijam sygnał {pattern} – niska waga {weight}")
            return
        # ========================================

        # ========== NOWE: Analiza M5 ==========
        analysis_m5 = get_smc_analysis("5m")

        # Dodatkowe alerty dla M5 (np. Liquidity Grab na M5)
        if analysis_m5 and analysis_m5.get('liquidity_grab'):
            alert_key = _hash(f"grab_m5_{analysis_m5['liquidity_grab_dir']}_{analysis_m5['price']:.1f}")
            if not db.is_news_processed(alert_key):
                grab_msg = f"⚡ *LIQUIDITY GRAB NA M5!*\nKierunek: *{analysis_m5['liquidity_grab_dir'].upper()}*\nCena: {analysis_m5['price']}$\n"
                if analysis_m5['liquidity_grab_dir'] == "bullish":
                    grab_msg += "Oczekuj szybkiego powrotu w górę – szukaj LONG na M5 FVG/OB."
                else:
                    grab_msg += "Oczekuj szybkiego spadku – szukaj SHORT na M5 FVG/OB."
                send_telegram_alert(grab_msg)
                db.mark_news_as_processed(alert_key)


        # --- 1. ALERT ZMIANY TRENDU ---
        if LAST_STATUS.get("trend") is not None and current_trend != LAST_STATUS["trend"]:
            alert_key = _hash(f"trend_{current_trend}_{current_structure}")

            if not db.is_news_processed(alert_key):
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
                db.mark_news_as_processed(alert_key)  # ← WYPEŁNIA processed_news

                # Zapisz sygnał do scanner_signals
                direction = "LONG" if current_trend == "Bull" else "SHORT"
                db.save_scanner_signal(
                    direction=direction,
                    entry=current_price,
                    sl=current_sl,
                    tp=current_tp,
                    rsi=current_rsi,
                    trend=current_trend,
                    structure=current_structure
                )  # ← WYPEŁNIA scanner_signals
                print(f"📡 [SCANNER] Zapisano sygnał {direction} do scanner_signals.")

        # --- 2. ALERT NOWEJ STREFY FVG ---
        if (current_fvg not in ["None", "Brak", None] and current_fvg != LAST_STATUS["fvg"]):
            fvg_lower = current_fvg.lower()

            if "bull" in fvg_lower or "up" in fvg_lower:
                kierunek = "BULLISH 🟢 (Luka wzrostowa)"
                direction = "LONG"
                is_serious = True
            elif "bear" in fvg_lower or "down" in fvg_lower:
                kierunek = "BEARISH 🔴 (Luka spadkowa)"
                direction = "SHORT"
                is_serious = True
            else:
                kierunek = f"WYKRYTO ({current_fvg})"
                direction = "LONG"
                is_serious = False

            if is_serious:
                fvg_key = _hash(f"fvg_{current_fvg}_{current_price:.1f}")

                if not db.is_news_processed(fvg_key):
                    tf = USER_PREFS.get('tf', '15m')
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
                    db.mark_news_as_processed(fvg_key)  # ← WYPEŁNIA processed_news

                    # Zapisz sygnał FVG do scanner_signals
                    db.save_scanner_signal(
                        direction=direction,
                        entry=current_price,
                        sl=current_sl,
                        tp=current_tp,
                        rsi=current_rsi,
                        trend=current_trend,
                        structure=f"FVG_{current_fvg}"
                    )  # ← WYPEŁNIA scanner_signals
                    print(f"📡 [SCANNER] Zapisano sygnał FVG {direction} do scanner_signals.")

        # --- 3. AKTUALIZACJA STANU ---
        LAST_STATUS["trend"] = current_trend
        LAST_STATUS["fvg"] = current_fvg

        print("✅ [SCANNER] Skonczono cykl.")

    except Exception as e:
        print(f"❌ [SCANNER] Błąd: {e}")


async def resolve_trades_task(context):
    """
    Poprawiona wersja: Przy LOSS zapisuje powód i okoliczności do bazy.
    """
    from src.database import NewsDB
    db = NewsDB()

    # 1. POBIERANIE CENY
    url = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={TD_API_KEY}"
    try:
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

    # 2. POBIERANIE I ROZLICZANIE POZYCJI
    try:
        open_trades = db.get_open_trades()
        if not open_trades:
            return

        # Pobierz aktualny kontekst rynkowy raz dla wszystkich pozycji
        try:
            analysis = get_smc_analysis(USER_PREFS['tf'])
            market_snapshot = (
                f"Cena: {current_price} | "
                f"Trend: {analysis.get('trend', '?')} | "
                f"RSI: {analysis.get('rsi', '?')} | "
                f"Struktura: {analysis.get('structure', '?')} | "
                f"FVG: {analysis.get('fvg', '?')}"
            ) if analysis else f"Cena: {current_price}"
        except Exception:
            market_snapshot = f"Cena: {current_price}"

        for trade in open_trades:
            t_id, direction, entry, sl, tp = trade
            status = None

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

            if status:
                db.update_trade_status(t_id, status)

                # ========== NOWE: aktualizacja statystyk sesji ==========
                if status in ("PROFIT", "LOSS"):
                    db.cursor.execute("SELECT pattern, session FROM trades WHERE id = ?", (t_id,))
                    row = db.cursor.fetchone()
                    if row and row[0]:
                        pattern = row[0]
                        session = row[1] or "Unknown"
                        db.update_session_stats(pattern, session, status)

                if status in ("PROFIT", "LOSS"):
                    from src.self_learning import update_factor_weights
                    update_factor_weights(t_id, status)

                db.cursor.execute("SELECT pattern FROM trades WHERE id = ?", (t_id,))
                pattern = db.cursor.fetchone()
                pattern = pattern[0] if pattern else None
                analysis_data = {"pattern": pattern}
                from src.self_learning import update_pattern_weight
                update_pattern_weight(analysis_data, status)

                exit_price = float(tp) if status == "PROFIT" else float(sl)

                # ← ZAPISUJE POWÓD I OKOLICZNOŚCI PRZEGRANEJ
                if status == "LOSS":
                    reason = (
                        f"Cena dotknęła SL ({sl}$). "
                        f"Wejście było na {entry}$, "
                        f"kierunek: {direction}."
                    )
                    db.log_loss_details(
                        trade_id=t_id,
                        reason=reason,
                        market_condition=market_snapshot
                    )
                    print(f"📝 [RESOLVER] Zapisano okoliczności straty dla pozycji {t_id}.")

                icon = "✅" if status == "PROFIT" else "❌"
                msg = (
                    f"{icon} *POZYCJA ROZSTRZYGNIĘTA!*\n"
                    f"ID: `{t_id}` | Kierunek: {direction}\n"
                    f"Wynik: *{status}*\n"
                    f"Wejście: `{entry}` | Wyjście: `{exit_price}`"
                )
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=msg,
                    parse_mode="Markdown"
                )
                print(f"💰 [RESOLVER] Zamknięto pozycję {t_id} jako {status}")

    except Exception as e:
        print(f"🚨 [RESOLVER] Błąd podczas sprawdzania pozycji: {e}")