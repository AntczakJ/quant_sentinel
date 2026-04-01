# main.py
"""
main.py — główny orchestrator bota Telegram.

Odpowiada za:
  - Inicjalizację bazy danych i aplikacji Telegram
  - Obsługę komend (/start, /cap, /stats, /chart)
  - Obsługę wszystkich przycisków inline menu (CallbackQueryHandler)
  - Uruchomienie Flask webhook (TradingView alerts) w osobnym wątku
  - Rejestrację zadań cyklicznych (skaner rynku, resolver transakcji)
"""

import io
import threading
import asyncio
import datetime

import matplotlib

matplotlib.use('Agg')  # Backend bez GUI — konieczne na serwerze
import matplotlib.pyplot as plt
import yfinance as yf
import requests
import httpx

# --- python-telegram-bot (główna obsługa menu i komend) ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest
from telegram.request import HTTPXRequest

from src.self_learning import auto_analyze_and_learn


from src.config import TOKEN, USER_PREFS, CHAT_ID, TD_API_KEY
from src.interface import main_menu, tf_menu
from src.smc_engine import get_smc_analysis
from src.finance import calculate_position
from src.scanner import scan_market_task, resolve_trades_task
from src.ai_engine import ask_ai_gold
from src.database import NewsDB
from src.sentiment import get_sentiment_data
from src.news import get_latest_news, get_economic_calendar

from flask import Flask, request as flask_request
from src.self_learning import run_learning_cycle


# =============================================================================
# INICJALIZACJA AI (warm-up przed startem sieci)
# =============================================================================
print("🚀 Przygotowuję silniki AI (to może potrwać chwilę)...")
try:
    from src.sentiment import _get_ai_instance
    _get_ai_instance()
    print("✅ Systemy AI gotowe do pracy.")
except Exception as e:
    print(f"⚠️ Ostrzeżenie przy ładowaniu AI: {e}")

# Jedna globalna instancja bazy danych — współdzielona przez wszystkie handlery
db = NewsDB()
db.init_weights()   # upewnia, że wagi istnieją


# =============================================================================
# FLASK WEBHOOK — obsługa alertów z TradingView
# =============================================================================

app_flask = Flask(__name__)

@app_flask.route('/webhook', methods=['POST'])
def tradingview_webhook():
    """
    Endpoint przyjmujący alerty z TradingView przez webhook.
    TradingView wysyła JSON z polami: ticker, action, price.
    Bot przekazuje alert na Telegram jako sformatowaną wiadomość.
    """
    data = flask_request.json
    if data:
        ticker = data.get('ticker', 'GOLD')
        action = data.get('action', 'SIGNAL')
        price = data.get('price', '???')
        alert_msg = (
            f"🔔 *ALERT TRADINGVIEW: {ticker}*\n"
            f"🚀 Akcja: *{action}*\n"
            f"💰 Cena: `{price}`"
        )
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={
            "chat_id": CHAT_ID,
            "text": alert_msg,
            "parse_mode": "Markdown"
        })
        return "OK", 200
    return "No Data", 400


def run_flask():
    """Uruchamia serwer Flask na porcie 5000 (w osobnym wątku)."""
    app_flask.run(host='0.0.0.0', port=5000)


# =============================================================================
# KOMENDY BOTA
# =============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Komenda /start — wyświetla powitanie z aktualnym stanem portfela i menu główne.
    Kapitał pobierany jest z bazy danych (trwały między sesjami).
    """
    user_id = update.effective_user.id
    balance = db.get_balance(user_id)
    await update.message.reply_text(
        f"🚀 *QUANT SENTINEL AI ONLINE*\n"
        f"💰 Kapitał w bazie: `{balance}$` | Interwał: `{USER_PREFS['tf']}`",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


async def cap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Komenda /cap KWOTA WALUTA — ustawia kapitał użytkownika.
    Przykład: /cap 5000 PLN

    Kapitał jest zapisywany trwale w bazie SQLite.
    Waluta jest zapisywana w pamięci sesji (USER_PREFS).
    Obsługiwane waluty: USD, PLN, EUR, GBP.
    """
    user_id = update.effective_user.id
    try:
        if not context.args or len(context.args) < 1:
            raise IndexError

        amount = float(context.args[0])
        currency = context.args[1].upper() if len(context.args) > 1 else "USD"

        supported_currencies = ["USD", "PLN", "EUR", "GBP"]
        if currency not in supported_currencies:
            await update.message.reply_text(
                f"⚠️ Obsługiwane waluty to: `{', '.join(supported_currencies)}`"
            )
            currency = "USD"

        db.update_balance(user_id, amount)
        USER_PREFS["currency"] = currency

        await update.message.reply_text(
            f"✅ *Portfel ustawiony!*\n💰 Kapitał: `{amount} {currency}`",
            parse_mode="Markdown"
        )
    except IndexError:
        await update.message.reply_text(
            "❌ Użycie: `/cap KWOTA WALUTA` (np. `/cap 2500 PLN`)"
        )
    except ValueError:
        await update.message.reply_text("❌ Podaj poprawną liczbę dla kwoty!")


async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Komenda /sessions – wyświetla statystyki sesji dla wzorców."""
    db = NewsDB()
    stats = db.get_session_stats()
    if not stats:
        await update.message.reply_text("Brak danych o sesjach.")
        return

    msg = "📊 *STATYSTYKI SESJI*\n━━━━━━━━━━━━━━\n"
    current_pattern = None
    for pattern, session, count, wins, losses, win_rate in stats:
        if pattern != current_pattern:
            if current_pattern is not None:
                msg += "\n"
            msg += f"*{pattern}*\n"
            current_pattern = pattern
        win_icon = "✅" if win_rate > 0.5 else "❌"
        msg += f"  {session}: {count} trades, {win_rate:.1%} {win_icon}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Komenda /stats — wyświetla statystyki systemu:
      - Aktualny kapitał z bazy
      - Win Rate (% zyskownych transakcji)
      - Liczba TP i SL
      - Historia ostatnich 5 sygnałów
    """
    user_id = update.effective_user.id
    balance = db.get_balance(user_id)
    results, history = db.get_performance_stats()

    profit_count = results.get('PROFIT', 0)
    loss_count = results.get('LOSS', 0)
    total = profit_count + loss_count
    win_rate = (profit_count / total * 100) if total > 0 else 0

    history_text = ""
    for h in history:
        icon = "⚪" if h[2] == 'OPEN' else ("✅" if h[2] == 'PROFIT' else "❌")
        time_str = h[0][11:16] if h[0] else "??:??"
        history_text += f"{icon} `{time_str}` | {h[1]}\n"

    msg = (
        f"📊 *STATYSTYKI QUANT SENTINEL*\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Portfel: `{balance}$` \n"
        f"📈 Win Rate: *{win_rate:.1f}%*\n"
        f"✅ TP: `{profit_count}` | ❌ SL: `{loss_count}`\n"
        f"━━━━━━━━━━━━━━\n"
        f"🕒 *OSTATNIE SYGNAŁY:*\n"
        f"{history_text if history_text else '_Brak historii_'}\n"
    )

    target = update.message if update.message else update.callback_query.message
    await target.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


async def send_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Komenda /chart — generuje i wysyła wykres ceny złota dla aktywnego interwału.
    Dane pobierane są z Yahoo Finance (GC=F — kontrakty futures złota).
    Wykres jest generowany w pamięci (BytesIO) i wysyłany jako zdjęcie.
    """
    target = update.message if update.message else update.callback_query.message
    status_msg = await target.reply_text("⏳ Generuję wykres Gold...")
    try:
        df = yf.download("GC=F", period="2d", interval=USER_PREFS['tf'], progress=False)
        plt.figure(figsize=(10, 6))
        plt.plot(df.index, df['Close'], color='#f39c12', label='Gold Price')
        plt.title(f"GOLD/USD ({USER_PREFS['tf']}) - Live Analysis")
        plt.grid(True, alpha=0.3)
        plt.legend()

        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close()

        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=buf,
            caption=f"📊 Wykres Gold ({USER_PREFS['tf']})"
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Błąd wykresu: {e}")


# =============================================================================
# OBSŁUGA PRZYCISKÓW INLINE
# =============================================================================

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Główny handler dla wszystkich przycisków inline menu.
    Każdy callback_data odpowiada jednemu przyciskowi zdefiniowanemu w interface.py.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    async def safe_edit(text: str, reply_markup=None):
        """
        Edytuje wiadomość z obsługą błędu 'Message is not modified'.
        Telegram zwraca błąd gdy próbujemy ustawić identyczną treść — ignorujemy go.
        """
        if reply_markup is None:
            reply_markup = main_menu()
        try:
            await query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise e

    # -------------------------------------------------------------------------
    # ANALIZA QUANT PRO
    # -------------------------------------------------------------------------
    if query.data == 'smc_pro':
        await safe_edit("🔍 *Analiza Quant PRO (M15 + H1 + Makro + SMC)...*")

        s, s_higher, s_lower, raw_news, eco_calendar = await asyncio.gather(
            asyncio.to_thread(get_smc_analysis, USER_PREFS['tf']),
            asyncio.to_thread(get_smc_analysis, "1h"),
            asyncio.to_thread(get_smc_analysis, "5m"),
            asyncio.to_thread(get_latest_news),
            asyncio.to_thread(get_economic_calendar)
        )

        if not s or not s_higher or not s_lower:
            await safe_edit("❌ Błąd danych rynkowych.")
            return

        # Przygotowanie kontekstu makro
        macro_context = (
            f"Reżim: {s['macro_regime'].upper()} | "
            f"USD/JPY Z-score: {s['usdjpy_zscore']} | "
            f"ATR: {s['atr']} (śr: {s['atr_mean']})"
        )

        # Przygotowanie kontekstu dla AI
        learning_context = f"""
        STRUKTURA RYNKU (SMC):
        - Cena: {s['price']}$ | Trend Główny: {s['trend']} | Trend H1: {s_higher['trend']} | Trend M5: {s_lower['trend']}
        - Swing High: {s['swing_high']} | Swing Low: {s['swing_low']}
        - Liquidity Grab: {s['liquidity_grab']} ({s['liquidity_grab_dir']})
        - Market Structure Shift: {s['mss']}
        - FVG: {s['fvg']} (typ: {s['fvg_type']}, wielkość: {s['fvg_size']})
        - Order Block: {s['ob_price']}$ | EQ: {s['eq_level']}$ | Strefa: {'DISCOUNT' if s['is_discount'] else 'PREMIUM'}
        - DBR/RBD: {s['dbr_rbd_type']}
        - SMT: {s['smt']}

        POTWIERDZENIE M5:
        - Trend M5: {s_lower['trend']}
        - Liquidity Grab M5: {s_lower['liquidity_grab']} ({s_lower['liquidity_grab_dir']})
        - MSS M5: {s_lower['mss']}
        - FVG M5: {s_lower['fvg']}
        - Order Block M5: {s_lower['ob_price']}$

        MAKROEKONOMIA:
        - {macro_context}
        - USD/JPY: {s['usdjpy']}
        - Kalendarz ekonomiczny (USD High Impact):
        {eco_calendar}

        NEWSY: {raw_news[:500]}

        HISTORIA OSTATNICH STRAT: {db.get_recent_lessons(5)}
        """

        learning_prompt = """
        Jesteś rygorystycznym analitykiem Quant. OCEŃ SETUP (0-10) według zasad:
        1. Jeśli Liquidity Grab + MSS -> dodaj 4 pkt.
        2. Jeśli makro reżim zgodny z kierunkiem -> dodaj 2 pkt.
        3. Jeśli FVG w stronę trendu -> dodaj 2 pkt.
        4. Jeśli DBR/RBD zgodne z trendem -> dodaj 2 pkt.
        5. Jeśli RSI w strefie 40-50 przy trendzie bull -> dodaj 1 pkt.
        6. Jeśli RSI w strefie 50-60 przy trendzie bear -> dodaj 1 pkt.
        7. Jeśli struktura H1 przeciwna -> odejmij 2 pkt.
        8. Jeśli SMT Divergence -> odejmij 3 pkt.
        9. Jeśli makro reżim przeciwny -> odejmij 3 pkt.
        10. Jeśli cena w PREMIUM przy LONG -> odejmij 2 pkt.
        11. Jeśli trend M5 zgodny z kierunkiem -> dodaj 1 pkt.
        12. Jeśli na M5 wystąpił Liquidity Grab w tę samą stronę -> dodaj 2 pkt.
        13. Jeśli M5 jest przeciwny -> odejmij 2 pkt.
        Wydaj: [WYNIK: X/10] [POWÓD] [RADA]
        """

        ai_verdict = await asyncio.to_thread(ask_ai_gold, "smc", learning_context + "\n" + learning_prompt)

        import re
        ai_match = re.search(r"WYNIK:\s*(\d+(?:\.\d+)?)/10", ai_verdict)
        ai_score = float(ai_match.group(1)) if ai_match else 0
        if ai_score < 4.0:
            await safe_edit(
                f"⏸️ *SYGNAŁ ODRZUCONY*\nOcena AI: {ai_score}/10 – zbyt niska jakość setupu.\n\n🤖 *AI:*\n{ai_verdict}")
            return

        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")

        # --- Obliczenie pozycji (to daje rzeczywisty kierunek) ---
        p = calculate_position(s, balance, currency, TD_API_KEY)

        # Jeśli calculate_position zwróciło "CZEKAJ" z powodu makro lub innych filtrów
        if p.get("direction") == "CZEKAJ":
            await safe_edit(f"⏸️ *SYGNAŁ ZBLOKOWANY*\n{p.get('reason')}\n\n🤖 *AI:*\n{ai_verdict}")
            return

        # --- Teraz budujemy czynniki w oparciu o rzeczywisty kierunek transakcji ---
        # --- Teraz budujemy czynniki w oparciu o rzeczywisty kierunek transakcji ---
        direction = p['direction']  # "LONG" lub "SHORT"
        factors = {}

        # Konfluencja OB (liczba OB w klastrze)
        ob_confluence = s.get('ob_confluence', 0)
        if ob_confluence > 0:
            factors['ob_confluence'] = ob_confluence

        # Strefy Supply/Demand (czy cena blisko strefy)
        sd_zones = s.get('sd_zones', {})
        demand_zones = sd_zones.get('demand', [])
        supply_zones = sd_zones.get('supply', [])
        current_price = s['price']
        if direction == "LONG":
            if any(abs(current_price - low) < 5.0 for low, _ in demand_zones):
                factors['sd_zone'] = 1
        elif direction == "SHORT":
            if any(abs(current_price - high) < 5.0 for _, high in supply_zones):
                factors['sd_zone'] = 1

        # Dywergencja RSI
        if (direction == "LONG" and s.get('rsi_div_bull')) or (direction == "SHORT" and s.get('rsi_div_bear')):
            factors['rsi_divergence'] = 1

        # CHoCH na H1
        if (direction == "LONG" and s_higher.get('choch_bullish')) or (
                direction == "SHORT" and s_higher.get('choch_bearish')):
            factors['choch_h1'] = 1

        # BOS (Break of Structure)
        if (direction == "LONG" and s.get('bos_bullish')) or (direction == "SHORT" and s.get('bos_bearish')):
            factors['bos'] = 1

        # CHoCH na bieżącym interwale
        if (direction == "LONG" and s.get('choch_bullish')) or (direction == "SHORT" and s.get('choch_bearish')):
            factors['choch'] = 1

        # Liczba Order Blocków (z listy order_blocks)
        ob_list = s.get('order_blocks', [])
        if ob_list:
            ob_count = min(len(ob_list), 3)
            factors['ob_count'] = ob_count

        # Order block główny
        ob_main = s.get('ob_price')
        if ob_main:
            if direction == "LONG" and ob_main < s['price']:
                factors['ob_main'] = 1
            elif direction == "SHORT" and ob_main > s['price']:
                factors['ob_main'] = 1

        # Order block M5
        ob_m5 = s_lower.get('ob_price')
        if ob_m5:
            if direction == "LONG" and ob_m5 < s['price']:
                factors['ob_m5'] = 1
            elif direction == "SHORT" and ob_m5 > s['price']:
                factors['ob_m5'] = 1

        # Order block H1
        ob_h1 = s_higher.get('ob_price')
        if ob_h1:
            if direction == "LONG" and ob_h1 < s['price']:
                factors['ob_h1'] = 1
            elif direction == "SHORT" and ob_h1 > s['price']:
                factors['ob_h1'] = 1

        # FVG w kierunku
        fvg_type = s.get('fvg_type')
        if (direction == "LONG" and fvg_type == "bullish") or (direction == "SHORT" and fvg_type == "bearish"):
            factors['fvg'] = 1

        # Liquidity Grab + MSS
        if s.get('liquidity_grab') and s.get('mss'):
            if (direction == "LONG" and s.get('liquidity_grab_dir') == "bullish") or (
                    direction == "SHORT" and s.get('liquidity_grab_dir') == "bearish"):
                factors['grab_mss'] = 1

        # DBR/RBD
        dbr_type = s.get('dbr_rbd_type')
        if (direction == "LONG" and dbr_type == "DBR") or (direction == "SHORT" and dbr_type == "RBD"):
            factors['dbr_rbd'] = 1

        # Makro zgodne
        macro = s.get('macro_regime')
        if (direction == "LONG" and macro == "zielony") or (direction == "SHORT" and macro == "czerwony"):
            factors['macro'] = 1

        # RSI optymalny
        rsi = s.get('rsi')
        if direction == "LONG" and 40 <= rsi <= 50:
            factors['rsi_opt'] = 1
        elif direction == "SHORT" and 50 <= rsi <= 60:
            factors['rsi_opt'] = 1

        # M5 konfluencja (trend zgodny)
        if s_lower.get('trend') == s.get('trend'):
            factors['m5_confluence'] = 1

        # Oblicz wagę sumaryczną
        factor_score = 0
        for factor, present in factors.items():
            weight = db.get_param(f"weight_{factor}", 1.0)
            factor_score += present * weight

        # Sprawdź warunek: co najmniej jeden order block (dowolny)
        has_ob = factors.get('ob_count', 0) > 0

        MIN_SCORE = 5.0
        if not has_ob or factor_score < MIN_SCORE:
            await safe_edit(
                f"⏸️ *SYGNAŁ ZBLOKOWANY*\n"
                f"Ocena: {factor_score:.1f} / {MIN_SCORE} | Order block: {'tak' if has_ob else 'nie'}\n"
                f"Nie spełniono kryteriów wejścia.\n\n"
                f"🧠 *Czynniki aktywne:* {', '.join(factors.keys()) if factors else 'brak'}\n"
                f"🤖 *AI:*\n{ai_verdict}"
            )
            return

        # Logowanie transakcji z rozszerzonym opisem struktury i czynnikami
        structure_desc = f"Grab:{s['liquidity_grab']}, MSS:{s['mss']}, FVG:{s['fvg_type']}, DBR:{s['dbr_rbd_type']}"
        db.log_trade(
            direction=p['direction'],
            price=p['entry'],
            sl=p['sl'],
            tp=p['tp'],
            rsi=s['rsi'],
            trend=s['trend'],
            structure=structure_desc,
            factors=factors
        )

        msg = (
            f"🎯 *WERDYKT QUANT PRO*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🏗️ *STRUKTURA SMC (GŁÓWNY):* \n"
            f"- Liquidity Grab: {s['liquidity_grab']} ({s['liquidity_grab_dir']}) | MSS: {s['mss']}\n"
            f"- FVG: {s['fvg']} | OB: {s['ob_price']}$\n"
            f"- DBR/RBD: {s['dbr_rbd_type']}\n"
            f"🔍 *POTWIERDZENIE M5:* \n"
            f"- Trend: {s_lower['trend']} | Grab: {s_lower['liquidity_grab']} | MSS: {s_lower['mss']}\n"
            f"🌍 *MAKRO:* {macro_context}\n"
            f"🤖 *ANALIZA AI:* \n{ai_verdict}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚀 *SYGNAŁ:* `{p['direction']}`\n"
            f"📍 *WEJŚCIE:* `{p['entry']}$` \n"
            f"🛑 *STOP LOSS:* `{p['sl']}$` \n"
            f"✅ *TAKE PROFIT:* `{p['tp']}$` \n"
            f"📊 *LOT:* `{p['lot']}` ({p['logic']})\n"
            f"━━━━━━━━━━━━━━\n"
            f"⚖️ *STREFA:* `{'DISCOUNT' if s['is_discount'] else 'PREMIUM'}` | EQ: `{s['eq_level']}`\n"
            f"🧭 *TREND M15/H1/M5:* `{s['trend']}` / `{s_higher['trend']}` / `{s_lower['trend']}`\n"
            f"📡 *SMT:* `{s['smt']}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"📅 *KALENDARZ:* \n{eco_calendar}"
        )

        await safe_edit(msg)

    # -------------------------------------------------------------------------
    # DASHBOARD FINANSOWY / PORTFEL
    # -------------------------------------------------------------------------
    elif query.data in ['change_cap', 'status_check']:
        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")
        status_msg = (
            f"📊 *DASHBOARD FINANSOWY*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Kapitał: `{balance} {currency}`\n"
            f"💵 Przelicznik: `Automatyczny`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 Aby zmienić: `/cap 5000 PLN`"
        )
        await safe_edit(status_msg)

    # -------------------------------------------------------------------------
    # SENTYMENT AI (FinBERT + GPT)
    # -------------------------------------------------------------------------
    elif query.data == 'sentiment':
        await safe_edit("🎭 *Badanie nastrojów rynkowych...*")
        try:
            s = await asyncio.to_thread(get_smc_analysis, USER_PREFS['tf'])
            failure_report = db.get_failures_report()

            sentiment_raw = await asyncio.to_thread(get_sentiment_data)
            full_context = (
                f"AKTUALNE DANE ZŁOTA:\n"
                f"Cena: {s['price']}, Trend: {s['trend']}, RSI: {s['rsi']}, FVG: {s['fvg']}\n"
                f"HISTORIA TWOICH BŁĘDÓW:\n{failure_report}\n"
                f"NEWSY Z RYNKU:\n{sentiment_raw}"
            )

            ai_opinion = await asyncio.to_thread(ask_ai_gold, "trading_signal", full_context)
            await safe_edit(f"🎯 *WERDYKT AI:* \n\n{ai_opinion}")
        except Exception as e:
            await safe_edit(f"❌ Błąd: {e}")

    # -------------------------------------------------------------------------
    # NEWSY (RSS + interpretacja GPT)
    # -------------------------------------------------------------------------
    elif query.data == 'news':
        await safe_edit("📰 *AI filtruje newsy...*")
        try:
            raw_news = await asyncio.to_thread(get_latest_news)
            ai_news = await asyncio.to_thread(ask_ai_gold, "news", raw_news)
            await safe_edit(f"📰 *INTERPRETACJA NEWSÓW:*\n\n{ai_news}")
        except Exception as e:
            await safe_edit(f"❌ Błąd newsów: {e}")

    # -------------------------------------------------------------------------
    # POZOSTAŁE PRZYCISKI
    # -------------------------------------------------------------------------
    elif query.data == 'stats_btn':
        await stats_command(update, context)

    elif query.data == 'settings':
        balance = db.get_balance(user_id)
        await safe_edit(
            f"⚙️ *USTAWIENIA*\n\nKapitał: `{balance}$` | Interwał: `{USER_PREFS['tf']}`"
        )

    elif query.data == 'back':
        balance = db.get_balance(user_id)
        await safe_edit(f"🚀 *QUANT SENTINEL DASHBOARD*\nKapitał: `{balance}$`")

    elif query.data == 'menu_tf':
        await safe_edit("⏱ *Wybierz interwał analizy:*", reply_markup=tf_menu())

    elif query.data.startswith('set_'):
        new_tf = query.data.split('_')[1]
        # Mapowanie na format akceptowany przez smc_engine (np. 5m, 15m, 1h, 4h)
        if new_tf == '5m':
            new_tf = '5m'
        USER_PREFS["tf"] = new_tf
        await safe_edit(f"✅ Interwał zmieniony na: *{new_tf}*")

    elif query.data == 'chart_action':
        await send_chart(update, context)

    elif query.data == 'help':
        msg = (
            "📖 *POMOC QUANT SENTINEL:*\n\n"
            "1. *Analiza PRO* — analiza SMC + AI dla aktywnego interwału\n"
            "2. *Status systemu* — kapitał i ustawienia portfela\n"
            "3. `/cap KWOTA WALUTA` — ustaw kapitał (np. `/cap 5000 PLN`)\n"
            "4. `/stats` — historia transakcji i Win Rate\n"
            "5. `/chart` — wykres ceny złota"
        )
        await safe_edit(msg)


# =============================================================================
# URUCHOMIENIE — python-telegram-bot z job_queue
# =============================================================================

def run_bot():
    """
    Startuje bota z poprawionymi limitami czasu i pulą połączeń.
    """

    # Flask webhook w osobnym wątku
    threading.Thread(target=run_flask, daemon=True).start()

    # Konfiguracja HTTP z większą pulą połączeń i dłuższymi timeoutami
    request_config = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=120.0,  # 2 minuty — AI potrzebuje czasu
        write_timeout=60.0,  # długie wiadomości / zdjęcia
        pool_timeout=30.0  # czas oczekiwania na wolne połączenie
    )

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request_config)
        .get_updates_request(request_config)
        .build()
    )

    if app.job_queue:
        job_settings = {"misfire_grace_time": 60}

        if scan_market_task is not None:
            app.job_queue.run_repeating(
                scan_market_task,
                interval=300,
                first=10,
                job_kwargs=job_settings
            )
        else:
            print("ERROR: scan_market_task is None")

        # Resolver transakcji
        if resolve_trades_task is not None:
            app.job_queue.run_repeating(
                resolve_trades_task,
                interval=120,
                first=15,
                job_kwargs=job_settings
            )
        else:
            print("ERROR: resolve_trades_task is None")

        # NOWE: automatyczna analiza co 15 minut (900 sekund)
        app.job_queue.run_repeating(
            auto_analyze_and_learn,
            interval=900,
            first=30,
            job_kwargs=job_settings
        )



    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cap", cap_cmd))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("chart", send_chart))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(CommandHandler("sessions", sessions_command))

    print("🤖 Bot startuje w trybie POLLING...")
    app.run_polling()


if __name__ == '__main__':
    run_bot()