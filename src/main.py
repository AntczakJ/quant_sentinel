"""
main.py — główny orchestrator bota Telegram.

Odpowiada za:
  - Inicjalizację bazy danych i aplikacji Telegram
  - Obsługę komend (/start, /cap, /stats, /chart)
  - Obsługę wszystkich przycisków inline menu (CallbackQueryHandler)
  - Uruchomienie Flask webhook (TradingView alerts) w osobnym wątku
  - Rejestrację zadań cyklicznych (skaner rynku, resolver transakcji)

Naprawione błędy (v2):
  - Usunięto wykonaj_pelna_analize_pro() — funkcja-zombie z SyntaxError
    (niezindentowany kod na dole tworzył pętlę poza funkcją)
  - Usunięto globalną safe_edit() — kolidowała z lokalną wersją w handle_buttons
  - Usunięto wszystkie zduplikowane importy (3× get_smc_analysis, 2× scan_market_task itp.)
  - Naprawiono news handler: ask_ai_gold() teraz wywołane przez asyncio.to_thread()
  - Naprawiono if __name__ == '__main__': teraz wywołuje run_bot() zamiast aiogram executor
  - Usunięto podwójny blok inicjalizacji AI (był zdefiniowany dwa razy przed db = NewsDB())
  - aiogram (bot/dp/executor) i python-telegram-bot (Application) zachowane razem
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

# --- aiogram (używane przez on_startup / scan_market_task) ---
from aiogram import Bot, Dispatcher, executor as aiogram_executor

# --- python-telegram-bot (główna obsługa menu i komend) ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest
from telegram.request import HTTPXRequest

from src.config import TOKEN, USER_PREFS, CHAT_ID, TD_API_KEY
from src.interface import main_menu, tf_menu
from src.smc_engine import get_smc_analysis
from src.finance import calculate_position
from src.scanner import scan_market_task
from src.ai_engine import ask_ai_gold
from src.database import NewsDB
from src.sentiment import get_sentiment_data
from src.news import get_latest_news, get_economic_calendar

from flask import Flask, request as flask_request

# --- aiogram bot/dispatcher (używane wyłącznie przez on_startup + aiogram executor) ---
aiogram_bot = Bot(token=TOKEN)
dp = Dispatcher(aiogram_bot)

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
        await safe_edit("🔍 *Analiza Quant PRO (M15 + H1 + USD/JPY)...*")

        s = await asyncio.to_thread(get_smc_analysis, USER_PREFS['tf'])
        s_higher = await asyncio.to_thread(get_smc_analysis, "1h")

        if not s or not s_higher:
            await safe_edit("❌ Błąd danych rynkowych.")
            return

        confluence_warning = ""
        is_counter_trend = False

        if s['trend'] != s_higher['trend']:
            is_counter_trend = True
            user_direction = "Long (Kupno)" if s['trend'] == "Bull" else "Short (Sprzedaż)"
            higher_trend_label = "Bearish (H1 spada)" if s_higher['trend'] == "Bear" else "Bullish (H1 rośnie)"
            confluence_warning = (
                f"⚠️ *GRASZ POD PRĄD TRENDU H1!*\n"
                f"━━━━━━━━━━━━━━\n"
                f"Twoja gra: *{user_direction}* | Trend H1: *{higher_trend_label}*\n"
                f"Zasada Quant PRO: Setup Counter-Trend ma mniejsze szanse na TP i jest bardziej ryzykowny.\n\n"
            )

        raw_news = await asyncio.to_thread(get_latest_news)
        eco_calendar = await asyncio.to_thread(get_economic_calendar)
        recent_losses = db.get_recent_lessons(5)

        learning_context = (
            f"STRUKTURA RYNKU:\n"
            f"- Cena: {s['price']}$ | Trend: {s['trend']} (Wyższy trend H1: {s_higher['trend']})\n"
            f"- Status: {s.get('structure', 'Stable')}\n"
            f"- Strefa: {'DISCOUNT (Tanio)' if s['is_discount'] else 'PREMIUM (Drogo)'}\n"
            f"- Order Block: {s['ob_price']}$ | Poziom EQ: {s['eq_level']}$\n"
            f"- FVG: {s['fvg']} | USD/JPY: {s['dxy']}\n"
            f"- SMT: {s['smt']}\n\n"
            f"FUNDAMENTY:\n"
            f"KALENDARZ EKONOMICZNY (High Impact USD):\n{eco_calendar}\n\n"
            f"HISTORIA OSTATNICH STRAT: {recent_losses}\n"
            f"{'UWAGA: To jest setup COUNTER-TREND!' if is_counter_trend else ''}\n"
            f"NEWSY: {raw_news[:500]}"
        )

        learning_prompt = f"""
        Jesteś rygorystycznym analitykiem Quant. Twoim zadaniem jest OCENA (0-10) tego setupu.
        ZASADY:
        1. Porównaj RSI z ostatnimi stratami. Jeśli sytuacja jest identyczna - odejmij 3 pkt.
        2. Jeśli USD/JPY rośnie, a my chcemy LONG - odejmij 2 pkt.
        3. Jeśli mamy FVG > 0.8$ w stronę trendu - dodaj 2 pkt.
        4. Jeśli w kalendarzu są blisko ważne dane USD, dopisz w [RADA]: 'UWAGA: Dane blisko!'.
        5. Jeśli to jest setup COUNTER-TREND (gramy pod prąd H1) - odejmij automatycznie 2 punkty.
        6. Spójrz na screen (obraz_0.png) - czy FVG jest na tyle duże, że warto ryzykować Counter-Trend?
        7. Jeśli BUY w strefie PREMIUM (powyżej 50% ruchu) -> odejmij 4 pkt (za drogo!).
        8. Jeśli SELL w strefie DISCOUNT -> odejmij 4 pkt (za tanio na short!).
        9. Jeśli cena dotyka właśnie Order Blocka -> dodaj 3 pkt (idealne wejście).
        10. Jeśli FVG jest powyżej Equilibrium przy Longu -> dodaj 1 pkt (magnes cenowy).
        11. Jeśli SMT Divergence wykryte -> ostrzeż o możliwej pułapce!
        12. Jeśli Status Struktury to 'ChoCH Bearish' a my chcemy LONG -> Odejmij 7 pkt (Kategoryczny zakaz kupowania!).
        13. Jeśli Status Struktury to 'ChoCH Bullish' a my chcemy SHORT -> Odejmij 7 pkt (Kategoryczny zakaz sprzedaży!).
        14. Jeśli Struktura to 'LIQUIDITY SWEEP' - to bardzo silny sygnał odwrócenia! Dodaj 4 pkt do oceny w stronę przeciwną do wybicia.
        15. Jeśli Status Struktury to 'ChoCH Bearish' (prawdziwe przebicie) - kategorycznie odejmij 8 pkt dla LONGÓW. Nie idź pod prąd pociągu.
        16. Jeśli cena jest w DISCOUNT i mamy LIQUIDITY SWEEP dołem - to jest setup 10/10 na BUY.

        ODPOWIEDZ KONKRETNIE:
        [WYNIK: X/10]
        [POWÓD]: (max 15 słów - opisz ryzyko lub przewagę setupu)
        [RADA]: (krótka wskazówka techniczna, np. Czekaj na dotknięcie OB {s['ob_price']})
        """

        ai_verdict = await asyncio.to_thread(ask_ai_gold, "analysis", learning_context + "\n" + learning_prompt)

        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")
        p = calculate_position(s, balance, currency, TD_API_KEY)


        db.log_trade(
            direction=p['direction'],
            price=p['entry'],
            sl=p['sl'],
            tp=p['tp'],
            rsi=s['rsi'],
            trend=s['trend'],
            structure='DISCOUNT' if s.get('is_discount') else 'PREMIUM'
        )

        msg = (
            f"🎯 *WERDYKT QUANT PRO*\n"
            f"━━━━━━━━━━━━━━\n"
            f"🏗️ *STRUKTURA:* `{s.get('structure', 'Prawidłowa')}`\n"
            f"{confluence_warning}"
            f"🤖 *ANALIZA AI:* \n_{ai_verdict}_\n"
            f"━━━━━━━━━━━━━━\n"
            f"🚀 *SYGNAŁ:* `{p['direction']}`\n"
            f"📍 *WEJŚCIE (OB):* `{p['entry']}$` \n"
            f"🛑 *STOP LOSS:* `{p['sl']}$` \n"
            f"✅ *TAKE PROFIT:* `{p['tp']}$` \n"
            f"📊 *LOT:* `{p['lot']}` ({p['logic']})\n"
            f"━━━━━━━━━━━━━━\n"
            f"⚖️ *STREFA:* `{'DISCOUNT' if s['is_discount'] else 'PREMIUM'}` | EQ: `{s['eq_level']}`\n"
            f"🧭 *TREND M15/H1:* `{s['trend']}` / `{s_higher['trend']}`\n"
            f"📡 *SMT:* `{s['smt']}`\n"
            f"━━━━━━━━━━━━━━\n"
            f"📅 *KALENDARZ:* \n_{eco_calendar if eco_calendar else 'Brak ważnych danych.'}_"
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
            # NAPRAWIONO: ask_ai_gold musi być w to_thread (funkcja synchroniczna)
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
# on_startup dla aiogram (skaner rynku)
# =============================================================================

async def on_startup(dispatcher):
    """Uruchamia skaner rynkowy raz przy starcie aiogram dispatcher."""
    asyncio.create_task(scan_market_task(dispatcher))
    print("✅ [SYSTEM] Skaner rynkowy podpięty do bota.")


# async def auto_click_pro(context: ContextTypes.DEFAULT_TYPE):
#     """Sztucznie wywołuje analizę PRO co X minut"""
#     from telegram import Update
#
#     # 1. Asynchroniczna pusta funkcja dla answer()
#     async def async_noop(*args, **kwargs):
#         pass
#
#     # 2. Wrapper dla send_message, który ignoruje argumenty edycji i wysyła nową wiadomość
#     async def send_msg_wrapper(text, *args, **kwargs):
#         # Wyciągamy parse_mode i reply_markup jeśli są w kwargs, resztę ignorujemy
#         p_mode = kwargs.get('parse_mode', 'Markdown')
#         r_markup = kwargs.get('reply_markup', None)
#         return await context.bot.send_message(
#             chat_id=CHAT_ID,
#             text=text,
#             parse_mode=p_mode,
#             reply_markup=r_markup
#         )
#
#     # 3. Tworzymy 'udawany' obiekt Update i CallbackQuery
#     mock_update = type('obj', (object,), {
#         'callback_query': type('obj', (object,), {
#             'data': 'smc_pro',
#             'answer': async_noop,
#             'message': type('obj', (object,), {
#                 'chat_id': CHAT_ID,
#                 'message_id': 0
#             }),
#             'from_user': type('obj', (object,), {'id': 999}),
#             # TUTAJ: używamy wrappera zamiast bezpośredniego send_message
#             'edit_message_text': send_msg_wrapper
#         }),
#         'effective_user': type('obj', (object,), {'id': 999}),
#         'effective_chat': type('obj', (object,), {'id': CHAT_ID})
#     })
#
#     # 4. Wywołanie handlera
#     try:
#         # Import lokalny, żeby uniknąć Circular Import
#         from src.main import handle_buttons
#         await handle_buttons(mock_update, context)
#         print("✅ [AUTOPILOT] Cykl analizy wykonany i wysłany na Telegram.")
#     except Exception as e:
#         print(f"❌ [AUTOPILOT ERROR] Błąd podczas emulacji: {e}")
#
#     # Wywołujemy Twój istniejący handler
#     try:
#         from src.main import handle_buttons # Upewnij się, że import jest poprawny
#         await handle_buttons(mock_update, context)
#         print("✅ [AUTOPILOT] Sztuczne kliknięcie wykonane pomyślnie.")
#     except Exception as e:
#         print(f"❌ [AUTOPILOT ERROR] Błąd podczas emulacji: {e}")

# =============================================================================
# URUCHOMIENIE — python-telegram-bot z job_queue
# =============================================================================

def run_bot():
    """
    Startuje bota z poprawionymi limitami czasu dla słabych połączeń.
    """
    print("🚀 Przygotowuję silniki AI (FinBERT)...")
    try:
        from src.sentiment import _get_ai_instance
        _get_ai_instance()
        print("✅ Modele AI załadowane do RAM.")
    except Exception as e:
        print(f"⚠️ Uwaga: Błąd ładowania modeli AI: {e}")

    # Flask webhook w osobnym wątku
    threading.Thread(target=run_flask, daemon=True).start()

    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request_config)
        .get_updates_request(request_config)
        .build()
    )

    if app.job_queue:
        job_settings = {"misfire_grace_time": 60}

        app.job_queue.run_repeating(
            scan_market_task,
            interval=300,
            first=10,
            job_kwargs=job_settings
        )

    # if app.job_queue:
    #     job_settings = {"misfire_grace_time": 60}
    #
    #     # 1. AUTOPILOT - Sztuczne klikanie PRO (Nauka otwierania)
    #     app.job_queue.run_repeating(
    #         auto_click_pro,  # Ta funkcja, którą opisałem wcześniej
    #         interval=900,  # Co 15 minut
    #         first=10,
    #         job_kwargs=job_settings
    #     )

        # 2. RESOLVER - Sprawdzanie wyników (Nauka na błędach)
        from src.scanner import resolve_trades_task  # Import tutaj rozwiązuje Circular Import!
        app.job_queue.run_repeating(
            resolve_trades_task,
            interval=120,  # Co 2 minuty sprawdza ceny
            first=15,
            job_kwargs=job_settings
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cap", cap_cmd))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("chart", send_chart))
    app.add_handler(CallbackQueryHandler(handle_buttons))

    print("🤖 Bot startuje w trybie POLLING...")
    app.run_polling()


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    # NAPRAWIONO: uruchamiamy run_bot() (python-telegram-bot),
    # a nie aiogram executor — który był martwy przez całą aplikację.
    # Jeśli chcesz używać aiogram executor zamiast tego, zamień na:
    #   aiogram_executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
    run_bot()