# src/self_learning.py
"""
self_learning.py – mechanizmy samouczenia: optymalizacja parametrów, analiza wzorców.
"""

import numpy as np
import random

from src.database import NewsDB
import asyncio
import re
from src.smc_engine import get_smc_analysis
from src.finance import calculate_position
from src.ai_engine import ask_ai_gold
from src.config import USER_PREFS, TD_API_KEY

# Minimalna liczba transakcji do uruchomienia optymalizacji
MIN_TRADES_FOR_OPT = 20

def update_pattern_weight(analysis_data: dict, outcome: str):
    """
    Aktualizuje statystyki wzorca na podstawie wyniku transakcji.
    Wywoływane przez resolver.
    """
    db = NewsDB()
    pattern = analysis_data.get('pattern')
    if pattern:
        db.update_pattern_stats(pattern, outcome)


def get_pattern_adjustment(analysis_data: dict) -> float:
    """
    Zwraca współczynnik korekty (0.5-1.5) na podstawie historycznej win rate wzorca.
    Im wyższa win rate, tym większy współczynnik.
    """
    db = NewsDB()
    pattern = analysis_data.get('pattern')
    if not pattern:
        return 1.0
    stats = db.get_pattern_stats(pattern)
    if stats['count'] < 5:
        return 1.0  # za mało danych
    # Współczynnik: win_rate * 1.5 (max 1.5, min 0.5)
    adj = stats['win_rate'] * 1.5
    return max(0.5, min(1.5, adj))


import random
from datetime import datetime

def optimize_parameters():
    """
    Pełny backtest parametrów (risk_percent, min_tp_distance_mult, target_rr)
    na historycznych transakcjach.
    """
    db = NewsDB()
    # Pobieramy wszystkie zakończone transakcje w porządku chronologicznym
    db.cursor.execute("""
        SELECT timestamp, direction, entry, sl, tp, status
        FROM trades
        WHERE status IN ('PROFIT', 'LOSS')
        ORDER BY timestamp ASC
    """)
    trades = db.cursor.fetchall()
    if len(trades) < 50:
        return  # za mało danych

    # Parametry do testowania
    risk_values = [0.5, 1.0, 1.5, 2.0]
    min_tp_dist_mult_values = [0.5, 1.0, 1.5, 2.0]
    target_rr_values = [1.5, 2.0, 2.5, 3.0]

    best_score = -float('inf')
    best_params = {}

    # Dla każdej kombinacji
    for risk in risk_values:
        for mult in min_tp_dist_mult_values:
            for rr in target_rr_values:
                equity = 10000.0  # kapitał początkowy
                total_trades = 0
                # Symulacja sekwencyjna
                for trade in trades:
                    timestamp, direction, entry, sl, tp, status = trade
                    # Przelicz dystans SL (ryzyko)
                    dist = abs(entry - sl)
                    if dist <= 0:
                        continue
                    # Oblicz lot na podstawie aktualnego equity
                    risk_usd = equity * (risk / 100)
                    lot = risk_usd / (dist * 100)
                    if lot < 0.01:
                        lot = 0.01
                    # Sprawdź czy TP jest wystarczająco daleko (symulacja filtra)
                    tp_distance = abs(entry - tp)
                    min_tp_dist = max(tp_distance * mult, 5.0)  # uwzględniamy stały próg 5$
                    if tp_distance < min_tp_dist:
                        continue  # transakcja zostałaby odrzucona
                    # Wyznacz potencjalny zysk/stratę
                    if status == "PROFIT":
                        profit = tp_distance * lot * 100
                        equity += profit
                    else:
                        equity -= risk_usd
                    total_trades += 1

                if total_trades == 0:
                    continue

                # Metryka: średni zysk na transakcję / max drawdown (uproszczenie)
                avg_profit = (equity - 10000.0) / total_trades
                score = avg_profit  # można rozszerzyć o Sharpe, drawdown
                if score > best_score:
                    best_score = score
                    best_params = {
                        "risk_percent": risk,
                        "min_tp_distance_mult": mult,
                        "target_rr": rr
                    }

    # Zapisz najlepsze parametry
    for name, value in best_params.items():
        db.set_param(name, value)
    print(f"📈 [BACKTEST] Zoptymalizowano parametry: {best_params} (score: {best_score:.2f})")

def auto_tune_pattern_weights():
    """
    Analizuje statystyki wzorców i zapisuje dynamiczne wagi.
    Wagi mogą być używane przez AI lub przy generowaniu sygnałów.
    """
    db = NewsDB()
    patterns = db.get_all_patterns_stats()
    for pattern, count, wins, losses, win_rate in patterns:
        if count >= 5:
            # Waga = win_rate * 2 (max 1.5, min 0.5)
            weight = win_rate * 2
            weight = max(0.5, min(1.5, weight))
            db.set_param(f"pattern_weight_{pattern}", weight)
        else:
            # Za mało danych – domyślnie 1.0
            db.set_param(f"pattern_weight_{pattern}", 1.0)

def run_learning_cycle():
    """
    Główna funkcja wywoływana cyklicznie (co X transakcji lub co dzień).
    """
    optimize_parameters()
    auto_tune_pattern_weights()


async def auto_analyze_and_learn(context):
    """
    Automatycznie wykonuje analizę Quant PRO i zapisuje sygnał do bazy.
    Wywoływane cyklicznie przez job_queue.
    """
    try:
        # Pobierz analizy dla trzech interwałów (asynchronicznie)
        s, s_higher, s_lower = await asyncio.gather(
            asyncio.to_thread(get_smc_analysis, USER_PREFS['tf']),
            asyncio.to_thread(get_smc_analysis, "1h"),
            asyncio.to_thread(get_smc_analysis, "5m")
        )
        if not s or not s_higher or not s_lower:
            print("⚠️ [AUTO-LEARN] Brak danych – pomijam.")
            return

        # Kontekst makro
        macro_context = f"Reżim: {s['macro_regime'].upper()} | USD/JPY Z-score: {s['usdjpy_zscore']} | ATR: {s['atr']}"

        # Kontekst dla AI
        learning_context = f"""
        STRUKTURA RYNKU (SMC):
        - Cena: {s['price']}$ | Trend Główny: {s['trend']} | Trend H1: {s_higher['trend']} | Trend M5: {s_lower['trend']}
        - Liquidity Grab: {s['liquidity_grab']} ({s['liquidity_grab_dir']})
        - MSS: {s['mss']}
        - FVG: {s['fvg']}
        - Order Block: {s['ob_price']}$
        - DBR/RBD: {s['dbr_rbd_type']}
        POTWIERDZENIE M5: Grab: {s_lower['liquidity_grab']}, MSS: {s_lower['mss']}
        MAKRO: {macro_context}
        """

        # Ocena AI – asynchronicznie
        learning_prompt = """
        OCEŃ SETUP (0-10) według zasad: +4 za Grab+MSS, +2 za makro zgodne, +2 za FVG, +2 za DBR/RBD, +1 za RSI w strefie 40-50 (bull) lub 50-60 (bear), -2 za przeciwny H1, -3 za SMT, -3 za przeciwny makro, -2 za PREMIUM przy LONG. Wydaj: [WYNIK: X/10] [POWÓD] [RADA].
        """
        ai_verdict = await asyncio.to_thread(ask_ai_gold, "smc", learning_context + "\n" + learning_prompt)

        # Wyciągnij ocenę
        score = 0
        match = re.search(r"WYNIK:\s*(\d+(?:\.\d+)?)/10", ai_verdict)
        if match:
            score = float(match.group(1))

        # Oblicz pozycję
        db = NewsDB()
        user_id = 1  # domyślny użytkownik (możesz pobrać z bazy jeśli masz wielu)
        balance = db.get_balance(user_id)
        currency = USER_PREFS.get("currency", "USD")
        p = calculate_position(s, balance, currency, TD_API_KEY)

        if p.get("direction") == "CZEKAJ":
            print(f"⏸️ [AUTO-LEARN] Sygnał odrzucony: {p.get('reason')}")
            return

        # Opcjonalnie: pomiń sygnały z niską oceną AI
        MIN_SCORE = 5.0
        if score < MIN_SCORE:
            print(f"⏸️ [AUTO-LEARN] Pomijam sygnał – niska ocena AI ({score}/10)")
            return

        # --- Oblicz czynniki w oparciu o rzeczywisty kierunek transakcji ---
        direction = p['direction']
        factors = {}

        # BOS
        if (direction == "LONG" and s.get('bos_bullish')) or (direction == "SHORT" and s.get('bos_bearish')):
            factors['bos'] = 1

        # CHoCH
        if (direction == "LONG" and s.get('choch_bullish')) or (direction == "SHORT" and s.get('choch_bearish')):
            factors['choch'] = 1

        # Liczba OB (z listy order_blocks)
        ob_list = s.get('order_blocks', [])
        if ob_list:
            ob_count = min(len(ob_list), 3)
            factors['ob_count'] = ob_count   # maks. 3 punkty


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

        # M5 konfluencja (trend zgodny)
        if s_lower.get('trend') == s.get('trend'):
            factors['m5_confluence'] = 1

        # Zapis do bazy (z czynnikami)
        pattern = f"{direction}_{s.get('structure', 'unknown')}_{s.get('fvg_type', 'None')}"
        db.log_trade(
            direction=direction,
            price=p['entry'],
            sl=p['sl'],
            tp=p['tp'],
            rsi=s['rsi'],
            trend=s['trend'],
            structure=pattern,
            pattern=pattern,
            factors=factors
        )
        print(f"📡 [AUTO-LEARN] Zapisano sygnał {direction} do bazy (ocena AI: {score}/10, czynniki: {list(factors.keys())})")

        # Opcjonalnie: wysyłaj powiadomienie na czat (np. tylko gdy score > 8)
        if score > 8:
            from src.scanner import send_telegram_alert
            msg = (
                f"🤖 *AUTOMATYCZNY SYGNAŁ* (ocena {score}/10)\n"
                f"🚀 {direction} @ {p['entry']}$\n"
                f"🛑 SL: {p['sl']}$ | ✅ TP: {p['tp']}$\n"
                f"📊 Lot: {p['lot']} | {p['logic']}\n"
                f"🧠 Czynniki: {', '.join(factors.keys())}"
            )
            send_telegram_alert(msg)

    except Exception as e:
        print(f"❌ [AUTO-LEARN] Błąd: {e}")

import random

def update_factor_weights(trade_id, outcome):
    """
    Aktualizuje wagi czynników na podstawie wyniku transakcji.
    Działa jak gradient bandit + epsilon-greedy.
    """
    db = NewsDB()
    factors = db.get_trade_factors(trade_id)
    if not factors:
        return

    learning_rate = 0.05
    epsilon = 0.1  # szansa na losową zmianę
    for factor, present in factors.items():
        weight_name = f"weight_{factor}"
        current_weight = db.get_param(weight_name, 1.0)

        # Eksploracja: losowa zmiana z prawdopodobieństwem epsilon
        if random.random() < epsilon:
            delta = random.uniform(-0.1, 0.1)
            new_weight = current_weight + delta
        else:
            # Wykorzystanie: gradient (present * learning_rate)
            if outcome == "PROFIT":
                new_weight = current_weight + learning_rate * present
            else:
                new_weight = current_weight - learning_rate * present

        # Ograniczenie zakresu
        new_weight = max(0.5, min(3.0, new_weight))
        db.set_param(weight_name, new_weight)