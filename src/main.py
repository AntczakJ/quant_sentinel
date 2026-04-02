# main.py
"""
main.py — główny orchestrator bota Telegram.
"""

import io
import threading
import asyncio
import os
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import requests
import pandas as pd

from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import BadRequest
from telegram.request import HTTPXRequest

from src.logger import logger
from src.config import TOKEN, USER_PREFS, CHAT_ID, TD_API_KEY, \
    ENABLE_ML, ENABLE_RL, ENABLE_ADVANCED_INDICATORS, ENABLE_PATTERNS
from src.interface import main_menu, tf_menu
from src.smc_engine import get_smc_analysis, request_with_retry
from src.finance import calculate_position
from src.scanner import scan_market_task, resolve_trades_task
from src.ai_engine import ask_ai_gold
from src.database import NewsDB
from src.sentiment import get_sentiment_data
from src.news import get_latest_news, get_economic_calendar
from src.self_learning import auto_analyze_and_learn

from flask import Flask, request as flask_request

# Import nowych modułów
from src.data_sources import get_provider
from src.indicators import ichimoku, volume_profile
from src.candlestick_patterns import engulfing, pin_bar, inside_bar
from src.ml_models import ml
from src.rl_agent import DQNAgent

# =============================================================================
# INICJALIZACJA
# =============================================================================
logger.info("🚀 Przygotowuję silniki AI (to może potrwać chwilę)...")
try:
    from src.sentiment import _get_ai_instance
    _get_ai_instance()
    logger.info("✅ Systemy AI gotowe do pracy.")
except Exception as e:
    logger.info(f"⚠️ Ostrzeżenie przy ładowaniu AI: {e}")

db = NewsDB()
db.init_weights()

# ========== AGENT RL ==========
rl_agent = None
if ENABLE_RL:
    try:
        rl_agent = DQNAgent(state_size=22, action_size=3)
        rl_agent.load("models/rl_agent.keras")
        logger.info("RL Agent załadowany.")
    except Exception as e:
        logger.warning(f"Nie udało się załadować agenta RL: {e}")

# =============================================================================
# FLASK WEBHOOK
# =============================================================================
app_flask = Flask(__name__)

@app_flask.route('/webhook', methods=['POST'])
def tradingview_webhook():
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
    app_flask.run(host='0.0.0.0', port=5000)

# =============================================================================
# KOMENDY
# =============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = db.get_balance(user_id)
    await update.message.reply_text(
        f"🚀 *QUANT SENTINEL AI ONLINE*\n"
        f"💰 Kapitał w bazie: `{balance}$` | Interwał: `{USER_PREFS['tf']}`",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

async def cap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        if not context.args or len(context.args) < 1:
            raise IndexError
        amount = float(context.args[0])
        currency = context.args[1].upper() if len(context.args) > 1 else "USD"
        supported = ["USD", "PLN", "EUR", "GBP"]
        if currency not in supported:
            await update.message.reply_text(f"⚠️ Obsługiwane waluty: {', '.join(supported)}")
            currency = "USD"
        db.update_balance(user_id, amount)
        USER_PREFS["currency"] = currency
        await update.message.reply_text(f"✅ *Portfel ustawiony!*\n💰 Kapitał: `{amount} {currency}`", parse_mode="Markdown")
    except IndexError:
        await update.message.reply_text("❌ Użycie: `/cap KWOTA WALUTA` (np. `/cap 2500 PLN`)")
    except ValueError:
        await update.message.reply_text("❌ Podaj poprawną liczbę dla kwoty!")

async def sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = db.get_session_stats()
    if not stats:
        await update.message.reply_text("Brak danych o sesjach.")
        return
    msg = "📊 *STATYSTYKI SESJI*\n━━━━━━━━━━━━━━\n"
    current = None
    for pattern, session, count, wins, losses, win_rate in stats:
        if pattern != current:
            if current is not None:
                msg += "\n"
            msg += f"*{pattern}*\n"
            current = pattern
        win_icon = "✅" if win_rate > 0.5 else "❌"
        msg += f"  {session}: {count} trades, {win_rate:.1%} {win_icon}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = db.get_balance(user_id)
    results, history = db.get_performance_stats()
    profit = results.get('PROFIT', 0)
    loss = results.get('LOSS', 0)
    total = profit + loss
    win_rate = (profit / total * 100) if total else 0
    history_text = ""
    for h in history:
        icon = "⚪" if h[2] == 'OPEN' else ("✅" if h[2] == 'PROFIT' else "❌")
        time_str = h[0][11:16] if h[0] else "??:??"
        history_text += f"{icon} `{time_str}` | {h[1]}\n"
    msg = (f"📊 *STATYSTYKI QUANT SENTINEL*\n━━━━━━━━━━━━━━\n"
           f"💰 Portfel: `{balance}$` \n📈 Win Rate: *{win_rate:.1f}%*\n"
           f"✅ TP: `{profit}` | ❌ SL: `{loss}`\n━━━━━━━━━━━━━━\n"
           f"🕒 *OSTATNIE SYGNAŁY:*\n{history_text if history_text else '_Brak historii_'}\n")
    target = update.message if update.message else update.callback_query.message
    await target.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    param_names = ['risk_percent', 'min_tp_distance_mult', 'target_rr', 'min_score']
    msg = "⚙️ *Ustawienia dynamiczne*\n"
    for name in param_names:
        val = db.get_param(name, 'nie ustawione')
        msg += f"• `{name}`: {val}\n"
    msg += "\nAby zmienić: `/set param wartość`\nPrzykład: `/set min_score 5`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def set_param_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Użycie: `/set nazwa_parama wartość`")
        return
    param_name = context.args[0]
    try:
        value = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Wartość musi być liczbą.")
        return
    db.set_param(param_name, value)
    await update.message.reply_text(f"✅ Ustawiono `{param_name}` = {value}")

async def backtest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Uruchamiam backtest (może potrwać chwilę)...")
    from src.self_learning import optimize_parameters
    await asyncio.to_thread(optimize_parameters)
    best_risk = db.get_param('risk_percent', '?')
    best_mult = db.get_param('min_tp_distance_mult', '?')
    best_rr = db.get_param('target_rr', '?')
    msg = f"📊 *Backtest zakończony*\nNajlepsze parametry:\n"
    msg += f"• risk_percent: {best_risk}\n• min_tp_distance_mult: {best_mult}\n• target_rr: {best_rr}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.cursor.execute("SELECT timestamp, profit FROM trades WHERE status IN ('PROFIT','LOSS') AND profit IS NOT NULL ORDER BY timestamp ASC")
    rows = db.cursor.fetchall()
    if not rows:
        await update.message.reply_text("Brak danych do wygenerowania portfela.")
        return
    equity = 10000.0
    equity_curve = [equity]
    timestamps = []
    drawdowns = []
    peak = equity
    max_dd = 0
    for ts, profit in rows:
        equity += profit
        equity_curve.append(equity)
        timestamps.append(ts)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
        drawdowns.append(dd)
    plt.figure(figsize=(10,6))
    plt.plot(timestamps, equity_curve, color='blue', label='Kapitał')
    plt.title('Krzywa kapitału')
    plt.xlabel('Data')
    plt.ylabel('Kapitał (USD)')
    plt.grid(True)
    plt.legend()
    buf1 = io.BytesIO()
    plt.savefig(buf1, format='png')
    buf1.seek(0)
    plt.close()
    plt.figure(figsize=(10,4))
    plt.fill_between(timestamps, 0, drawdowns, color='red', alpha=0.5)
    plt.title(f'Drawdown (maksymalny: {max_dd:.2f} USD)')
    plt.xlabel('Data')
    plt.ylabel('Drawdown (USD)')
    plt.grid(True)
    buf2 = io.BytesIO()
    plt.savefig(buf2, format='png')
    buf2.seek(0)
    plt.close()
    media = [InputMediaPhoto(media=buf1, caption=f"Kapitał końcowy: {equity:.2f} USD"), InputMediaPhoto(media=buf2)]
    await context.bot.send_media_group(chat_id=update.effective_chat.id, media=media)

# =============================================================================
# OBSŁUGA PRZYCISKÓW INLINE
# =============================================================================
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    async def safe_edit(text: str, reply_markup=None):
        if reply_markup is None:
            reply_markup = main_menu()
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise e

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

        # Pobierz surowe świece do zaawansowanej analizy
        provider = get_provider()
        df_raw = provider.get_candles("XAU/USD", USER_PREFS['tf'], count=100)
        
        # Bezpieczne sprawdzenie czy dane istnieją
        has_valid_data = df_raw is not None and not df_raw.empty and len(df_raw) >= 10
        
        if has_valid_data:
            try:
                if ENABLE_ADVANCED_INDICATORS:
                    ichi = ichimoku(df_raw)
                    cloud_bull = (df_raw['close'].iloc[-1] > ichi['senkou_span_a'].iloc[-1] and
                                  df_raw['close'].iloc[-1] > ichi['senkou_span_b'].iloc[-1])
                    vp = volume_profile(df_raw)
                    near_poc = abs(vp['poc'] - s['price']) / s['price'] < 0.01
                if ENABLE_PATTERNS:
                    engulf = engulfing(df_raw)
                    pin = pin_bar(df_raw)
                    inside = inside_bar(df_raw)
            except Exception as e:
                logger.warning(f"⚠️ Błąd przy obliczeniu zaawansowanych wskaźników: {e}")
                has_valid_data = False
        else:
            logger.debug(f"Brak wystarczających danych surowych (otrzymano {len(df_raw) if df_raw is not None else 0} świec)")

        # Kontekst makro
        macro_context = (f"Reżim: {s['macro_regime'].upper()} | USD/JPY Z-score: {s['usdjpy_zscore']} | "
                         f"ATR: {s['atr']} (śr: {s['atr_mean']})")

        # Kontekst dla AI (rozszerzony o nowe czynniki)
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
        # Dodatkowe informacje z zaawansowanej analizy (bezpieczne sprawdzenie)
        if ENABLE_ADVANCED_INDICATORS and has_valid_data and 'cloud_bull' in locals():
            learning_context += f"\nWSKAŹNIKI ZAAWANSOWANE:\n- Cena powyżej chmury Ichimoku: {cloud_bull}\n- Cena blisko POC: {near_poc}\n"
        if ENABLE_PATTERNS and has_valid_data and 'engulf' in locals():
            learning_context += f"\nFORMACJE ŚWIECOWE:\n- Engulfing: {engulf}\n- Pin Bar: {pin}\n- Inside Bar: {inside}\n"

        learning_prompt = """
        Jesteś rygorystycznym analitykiem Quant. OCEŃ SETUP (0-10) według zasad:
        1. Liquidity Grab + MSS -> +4
        2. Makro reżim zgodny -> +2
        3. FVG w stronę trendu -> +2
        4. DBR/RBD zgodne -> +2
        5. RSI w strefie 40-50 (bull) lub 50-60 (bear) -> +1
        6. Struktura H1 przeciwna -> -2
        7. SMT Divergence -> -3
        8. Makro reżim przeciwny -> -3
        9. Cena w PREMIUM przy LONG -> -2
        10. Trend M5 zgodny -> +1
        11. Liquidity Grab M5 w tę samą stronę -> +2
        12. M5 przeciwny -> -2
        13. Ichimoku bullish -> +1
        14. Blisko POC -> +1
        15. Engulfing bullish -> +2, bearish -> -2
        16. Pin Bar bullish -> +1, bearish -> -1
        17. Inside Bar -> +0.5
        Wydaj: [WYNIK: X/10] [POWÓD] [RADA]
        """
        ai_verdict = await asyncio.to_thread(ask_ai_gold, "smc", learning_context + "\n" + learning_prompt)
        ai_match = re.search(r"WYNIK:\s*(\d+(?:\.\d+)?)/10", ai_verdict)
        ai_score = float(ai_match.group(1)) if ai_match else 0
        if ai_score < 4.0:
            await safe_edit(f"⏸️ *SYGNAŁ ODRZUCONY*\nOcena AI: {ai_score}/10 – zbyt niska jakość setupu.\n\n🤖 *AI:*\n{ai_verdict}")
            return

        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")

        # --- Obliczenie pozycji ---
        p = calculate_position(s, balance, currency, TD_API_KEY)
        if p.get("direction") == "CZEKAJ":
            await safe_edit(f"⏸️ *SYGNAŁ ZBLOKOWANY*\n{p.get('reason')}\n\n🤖 *AI:*\n{ai_verdict}")
            return

        direction = p['direction']           # rzeczywisty kierunek transakcji
        factors = {}                         # słownik czynników

        # ========== AGENT RL ==========
        if rl_agent is not None and has_valid_data:
            try:
                close_prices = df_raw['close'].values
                if len(close_prices) >= 20:
                    state = rl_agent.build_state(close_prices, balance=1.0, position=0)
                    action = rl_agent.act(state)
                    if (direction == "LONG" and action == 1) or (direction == "SHORT" and action == 2):
                        factors['rl_action'] = 1
                else:
                    logger.debug(f"Not enough close prices for RL agent: {len(close_prices)}")
            except Exception as e:
                logger.debug(f"⚠️ Błąd RL Agent: {e}")
        # =================================

        # ========== ZAAWANSOWANE CZYNNIKI ==========
        if ENABLE_ADVANCED_INDICATORS and has_valid_data and 'cloud_bull' in locals():
            if cloud_bull:
                factors['ichimoku_bull'] = 1
            if near_poc:
                factors['near_poc'] = 1
        if ENABLE_PATTERNS and has_valid_data and 'engulf' in locals():
            if engulf == 'bullish':
                factors['engulfing_bull'] = 1
            elif engulf == 'bearish':
                factors['engulfing_bear'] = 1
            if pin == 'bullish':
                factors['pin_bar_bull'] = 1
            elif pin == 'bearish':
                factors['pin_bar_bear'] = 1
            if inside:
                factors['inside_bar'] = 1
        if ENABLE_ML and has_valid_data:
            try:
                prob_xgb = ml.predict_xgb(df_raw)
                prob_lstm = ml.predict_lstm(df_raw)
                ml_signal = (prob_xgb + prob_lstm) / 2
                if direction == "LONG" and ml_signal > 0.6:
                    factors['ml_bull'] = 1
                elif direction == "SHORT" and ml_signal < 0.4:
                    factors['ml_bear'] = 1
            except Exception as e:
                logger.debug(f"⚠️ Błąd ML models: {e}")
        # =========================================

        # Konfluencja OB
        ob_confluence = s.get('ob_confluence', 0)
        if ob_confluence > 0:
            factors['ob_confluence'] = ob_confluence

        # Strefy Supply/Demand
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
        if (direction == "LONG" and s_higher.get('choch_bullish')) or (direction == "SHORT" and s_higher.get('choch_bearish')):
            factors['choch_h1'] = 1

        # BOS
        if (direction == "LONG" and s.get('bos_bullish')) or (direction == "SHORT" and s.get('bos_bearish')):
            factors['bos'] = 1

        # CHoCH
        if (direction == "LONG" and s.get('choch_bullish')) or (direction == "SHORT" and s.get('choch_bearish')):
            factors['choch'] = 1

        # Liczba OB
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

        # FVG
        fvg_type = s.get('fvg_type')
        if (direction == "LONG" and fvg_type == "bullish") or (direction == "SHORT" and fvg_type == "bearish"):
            factors['fvg'] = 1

        # Liquidity Grab + MSS
        if s.get('liquidity_grab') and s.get('mss'):
            if (direction == "LONG" and s.get('liquidity_grab_dir') == "bullish") or (direction == "SHORT" and s.get('liquidity_grab_dir') == "bearish"):
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

        # M5 konfluencja
        if s_lower.get('trend') == s.get('trend'):
            factors['m5_confluence'] = 1

        # Oblicz factor_score
        factor_score = 1
        for factor, present in factors.items():
            weight = db.get_param(f"weight_{factor}", 1.0)
            factor_score += present * weight

        has_ob = factors.get('ob_count', 0) > 0
        MIN_SCORE = db.get_param('min_score', 5.0)
        if not has_ob or factor_score < MIN_SCORE:
            await safe_edit(
                f"⏸️ *SYGNAŁ ZBLOKOWANY*\n"
                f"Ocena: {factor_score:.1f} / {MIN_SCORE} | Order block: {'tak' if has_ob else 'nie'}\n"
                f"Nie spełniono kryteriów wejścia.\n\n"
                f"🧠 *Czynniki aktywne:* {', '.join(factors.keys()) if factors else 'brak'}\n"
                f"🤖 *AI:*\n{ai_verdict}"
            )
            return

        # Logowanie transakcji
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

        msg = (f"🎯 *WERDYKT QUANT PRO*\n━━━━━━━━━━━━━━\n"
               f"🏗️ *STRUKTURA SMC (GŁÓWNY):* \n- Liquidity Grab: {s['liquidity_grab']} ({s['liquidity_grab_dir']}) | MSS: {s['mss']}\n"
               f"- FVG: {s['fvg']} | OB: {s['ob_price']}$\n- DBR/RBD: {s['dbr_rbd_type']}\n"
               f"🔍 *POTWIERDZENIE M5:* \n- Trend: {s_lower['trend']} | Grab: {s_lower['liquidity_grab']} | MSS: {s_lower['mss']}\n"
               f"🌍 *MAKRO:* {macro_context}\n"
               f"🤖 *ANALIZA AI:* \n{ai_verdict}\n━━━━━━━━━━━━━━\n"
               f"🚀 *SYGNAŁ:* `{p['direction']}`\n📍 *WEJŚCIE:* `{p['entry']}$`\n🛑 *SL:* `{p['sl']}$`\n✅ *TP:* `{p['tp']}$`\n"
               f"📊 *LOT:* `{p['lot']}` ({p['logic']})\n━━━━━━━━━━━━━━\n"
               f"⚖️ *STREFA:* `{'DISCOUNT' if s['is_discount'] else 'PREMIUM'}` | EQ: `{s['eq_level']}`\n"
               f"🧭 *TREND M15/H1/M5:* `{s['trend']}` / `{s_higher['trend']}` / `{s_lower['trend']}`\n"
               f"📡 *SMT:* `{s['smt']}`\n━━━━━━━━━━━━━━\n"
               f"📅 *KALENDARZ:* \n{eco_calendar}")
        await safe_edit(msg)

    # ... pozostałe przyciski (status_check, sentiment, news, itp.) pozostają bez zmian ...
    # (poniższy kod skopiuj z poprzedniej wersji – nie wymaga modyfikacji)
    elif query.data in ['change_cap', 'status_check']:
        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")
        await safe_edit(f"📊 *DASHBOARD FINANSOWY*\n━━━━━━━━━━━━━━━━━━━━\n💰 Kapitał: `{balance} {currency}`\n💵 Przelicznik: `Automatyczny`\n━━━━━━━━━━━━━━━━━━━━\n👉 Aby zmienić: `/cap 5000 PLN`")
    elif query.data == 'sentiment':
        await safe_edit("🎭 *Badanie nastrojów rynkowych...*")
        try:
            s = await asyncio.to_thread(get_smc_analysis, USER_PREFS['tf'])
            failure_report = db.get_failures_report()
            sentiment_raw = await asyncio.to_thread(get_sentiment_data)
            full_context = (f"AKTUALNE DANE ZŁOTA:\nCena: {s['price']}, Trend: {s['trend']}, RSI: {s['rsi']}, FVG: {s['fvg']}\n"
                            f"HISTORIA TWOICH BŁĘDÓW:\n{failure_report}\nNEWSY Z RYNKU:\n{sentiment_raw}")
            ai_opinion = await asyncio.to_thread(ask_ai_gold, "trading_signal", full_context)
            await safe_edit(f"🎯 *WERDYKT AI:* \n\n{ai_opinion}")
        except Exception as e:
            await safe_edit(f"❌ Błąd: {e}")
    elif query.data == 'news':
        await safe_edit("📰 *AI filtruje newsy...*")
        try:
            raw_news = await asyncio.to_thread(get_latest_news)
            ai_news = await asyncio.to_thread(ask_ai_gold, "news", raw_news)
            await safe_edit(f"📰 *INTERPRETACJA NEWSÓW:*\n\n{ai_news}")
        except Exception as e:
            await safe_edit(f"❌ Błąd newsów: {e}")
    elif query.data == 'stats_btn':
        await stats_command(update, context)
    elif query.data == 'settings':
        balance = db.get_balance(user_id)
        await safe_edit(f"⚙️ *USTAWIENIA*\n\nKapitał: `{balance}$` | Interwał: `{USER_PREFS['tf']}`")
    elif query.data == 'back':
        balance = db.get_balance(user_id)
        await safe_edit(f"🚀 *QUANT SENTINEL DASHBOARD*\nKapitał: `{balance}$`")
    elif query.data == 'menu_tf':
        await safe_edit("⏱ *Wybierz interwał analizy:*", reply_markup=tf_menu())
    elif query.data.startswith('set_'):
        new_tf = query.data.split('_')[1]
        if new_tf == '5m':
            new_tf = '5m'
        USER_PREFS["tf"] = new_tf
        await safe_edit(f"✅ Interwał zmieniony na: *{new_tf}*")
    elif query.data == 'help':
        msg = ("📖 *POMOC QUANT SENTINEL*\n\n🔹 *Przyciski w menu*\n"
               "• 🎯 ANALIZA QUANT PRO – pełna analiza SMC + AI\n• 📊 STATUS SYSTEMU – kapitał i ustawienia\n"
               "• 📰 NEWSY – najnowsze wiadomości\n• 🎭 SENTYMENT AI – nastroje rynkowe\n"
               "• ⏱ INTERWAŁ – zmiana ram czasowych\n• ⚙️ PORTFEL – zmiana kapitału\n\n🔹 *Komendy tekstowe*\n"
               "`/cap KWOTA WALUTA` – ustaw kapitał (np. `/cap 5000 PLN`)\n"
               "`/stats` – historia transakcji i Win Rate\n"
               "`/settings` – wyświetl parametry dynamiczne\n`/set param wartość` – zmień parametr (np. `/set min_score 5`)\n"
               "`/backtest` – uruchom optymalizację parametrów na historii\n`/portfolio` – krzywa kapitału i drawdown\n"
               "`/sessions` – statystyki skuteczności według sesji\n\n"
               "📌 *Parametry dynamiczne*\n`min_score` – minimalna ocena setupu (domyślnie 5)\n"
               "`risk_percent` – % kapitału ryzykowany na transakcję\n"
               "`min_tp_distance_mult` – mnożnik ATR dla minimalnego dystansu TP\n"
               "`target_rr` – docelowy stosunek ryzyka do zysku\n\n💡 *Więcej informacji*: /settings lub /help")
        await safe_edit(msg)

# =============================================================================
# URUCHOMIENIE
# =============================================================================
def run_bot():
    logger.info("Test zapisu logu")
    threading.Thread(target=run_flask, daemon=True).start()
    request_config = HTTPXRequest(connect_timeout=30.0, read_timeout=120.0, write_timeout=60.0, pool_timeout=30.0)
    app = ApplicationBuilder().token(TOKEN).request(request_config).get_updates_request(request_config).build()
    if app.job_queue:
        job_settings = {"misfire_grace_time": 60}
        
        # Sprawdzenie czy zadania istnieją i logowanie
        try:
            if scan_market_task is not None:
                logger.info("📡 Rejestrowanie zadania: scan_market_task (co 5 min)")
                app.job_queue.run_repeating(scan_market_task, interval=300, first=10, job_kwargs=job_settings)
            else:
                logger.warning("⚠️ scan_market_task = None, nie będzie skanowania rynku")
                
            if resolve_trades_task is not None:
                logger.info("📊 Rejestrowanie zadania: resolve_trades_task (co 2 min)")
                app.job_queue.run_repeating(resolve_trades_task, interval=120, first=15, job_kwargs=job_settings)
            else:
                logger.warning("⚠️ resolve_trades_task = None, nie będzie rozwiązywania tradów")
                
            logger.info("🧠 Rejestrowanie zadania: auto_analyze_and_learn (co 15 min)")
            app.job_queue.run_repeating(auto_analyze_and_learn, interval=900, first=30, job_kwargs=job_settings)
        except Exception as e:
            logger.error(f"❌ Błąd rejestrowania zadań: {e}")
    else:
        logger.warning("⚠️ Job queue nie dostępny!")
        
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cap", cap_cmd))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("sessions", sessions_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("set", set_param_command))
    app.add_handler(CommandHandler("backtest", backtest_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    logger.info("🤖 Bot startuje w trybie POLLING...")
    app.run_polling()

if __name__ == '__main__':
    run_bot()