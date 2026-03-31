"""
smc_engine.py — silnik analizy technicznej Smart Money Concepts.

Odpowiada za:
  - Pobieranie danych OHLCV złota (XAU/USD) z Twelve Data API
  - Obliczanie wskaźników: RSI (14) i EMA (20)
  - Wyznaczanie trendu (bull/bear) na podstawie relacji ceny do EMA
  - Wykrywanie Fair Value Gap (FVG) — luki płynności między świecami
  - Obliczanie poziomu Equilibrium (EQ) z ostatnich 20 świec
  - Pobieranie kursu USD/JPY jako proxy siły dolara (zamiast DXY)
  - Pobieranie dowolnego kursu walutowego (np. USD/PLN) dla finance.py
"""

import requests
import pandas as pd
import pandas_ta as ta
from src.config import TD_API_KEY


def get_smc_analysis(tf: str) -> dict | None:
    """
    SMC MASTER VERSION: Pobiera dane z Twelve Data i wykonuje pełną analizę strukturalną.
    """
    try:
        # Konwersja interwału dla Twelve Data
        td_tf = tf if "min" in tf else tf.replace("m", "min")

        # 1. POBIERANIE DANYCH (ZŁOTO + USD/JPY)
        url_gold = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={td_tf}&apikey={TD_API_KEY}&outputsize=100"
        data_gold = requests.get(url_gold, timeout=10).json()

        url_usdjpy = f"https://api.twelvedata.com/price?symbol=USD/JPY&apikey={TD_API_KEY}"
        data_usdjpy = requests.get(url_usdjpy, timeout=10).json()
        usdjpy_price = float(data_usdjpy.get('price', 0))

        if 'values' not in data_gold:
            print(f"Błąd Twelve Data: {data_gold.get('message')}")
            return None

        # 2. PRZETWARZANIE DATAFRAME
        df = pd.DataFrame(data_gold['values'])
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].apply(pd.to_numeric)
        df = df.iloc[::-1].reset_index(drop=True)

        # 3. WSKAŹNIKI (RSI i EMA do trendu)
        df['rsi'] = ta.rsi(df['close'], length=14)
        ema20 = ta.ema(df['close'], length=20)

        price = df['close'].iloc[-1]
        current_rsi = df['rsi'].iloc[-1]
        current_ema = ema20.iloc[-1]
        trend = "bull" if price > current_ema else "bear"

        # --- [TUTAJ MASZ JUŻ OBLICZONE df, price, rsi, ema20] ---

        # 3. WSTĘPNY TREND (Z EMA20)
        trend = "bull" if price > current_ema else "bear"

        # 1. Definiujemy poziomy Swing (ostatnie 30 świec)
        recent_lows = df['low'].tail(30)
        last_major_low = recent_lows.min()
        recent_highs = df['high'].tail(30)
        last_major_high = recent_highs.max()

        # 2. Logika LIQUIDITY SWEEP (Wybicie płynności)
        # Cena przebiła dołek knotem, ale wróciła (Close jest powyżej dołka)
        is_bullish_sweep = (df['low'].iloc[-1] < last_major_low) and (df['close'].iloc[-1] > last_major_low)
        is_bearish_sweep = (df['high'].iloc[-1] > last_major_high) and (df['close'].iloc[-1] < last_major_high)

        market_structure = "Stable"

        # 3. Inteligentne sprawdzanie Trendu i Struktury
        if df['close'].iloc[-1] < last_major_low:
            # To jest prawdziwe przebicie (zamknięcie pod dołkiem)
            market_structure = "⚠️ ChoCH Bearish (Zmiana na SPADKI)"
            trend = "bear"
        elif df['close'].iloc[-1] > last_major_high:
            # Prawdziwe przebicie góry
            market_structure = "⚠️ ChoCH Bullish (Zmiana na WZROSTY)"
            trend = "bull"
        elif is_bullish_sweep:
            # Pułapka na Shortujących! Smart Money zebrało płynność
            market_structure = "⚡ LIQUIDITY SWEEP (Bullish Reversal)"
            trend = "bull"
        elif is_bearish_sweep:
            market_structure = "⚡ LIQUIDITY SWEEP (Bearish Reversal)"
            trend = "bear"
        else:
            # Jeśli nic się nie dzieje, trzymaj trend z EMA
            trend = "bull" if price > current_ema else "bear"

        # 4. NOWA LOGIKA: WYKRYWANIE ZMIANY STRUKTURY (ChoCH)
        # To zapobiegnie braniu Longów, gdy cena zaczyna sypać się w dół
        recent_lows = df['low'].tail(30)
        last_major_low = recent_lows.min()
        recent_highs = df['high'].tail(30)
        last_major_high = recent_highs.max()

        market_structure = "Stable"

        if trend == "bull" and price < last_major_low:
            market_structure = "⚠️ ChoCH Bearish (Zmiana na SPADKI)"
            trend = "bear"  # Wymuszamy zmianę, nawet jeśli cena jest nad EMA
        elif trend == "bear" and price > last_major_high:
            market_structure = "⚠️ ChoCH Bullish (Zmiana na WZROSTY)"
            trend = "bull"

        # --- [DALSZA CZĘŚĆ: EQUILIBRIUM, ORDER BLOCK, FVG...] ---

        # 4. EQUILIBRIUM (Premium vs Discount)
        # Szukamy swingu z ostatnich 50 świec
        swing_high = df['high'].tail(50).max()
        swing_low = df['low'].tail(50).min()
        eq_level = round((swing_high + swing_low) / 2, 2)
        is_discount = price < eq_level
        is_premium = price > eq_level

        # 5. ORDER BLOCK (OB) - Szukamy ostatniej świecy przed impulsem
        ob_price = price
        df['body_size'] = (df['close'] - df['open']).abs()
        avg_body = df['body_size'].tail(20).mean()

        for i in range(len(df) - 2, len(df) - 20, -1):
            # Bullish OB: ostatnia czerwona przed zielonym wystrzałem
            if trend == "bull" and df['close'].iloc[i + 1] > df['open'].iloc[i + 1] and df['body_size'].iloc[
                i + 1] > avg_body:
                if df['close'].iloc[i] < df['open'].iloc[i]:
                    ob_price = df['low'].iloc[i]
                    break
            # Bearish OB: ostatnia zielona przed czerwonym spadkiem
            elif trend == "bear" and df['close'].iloc[i + 1] < df['open'].iloc[i + 1] and df['body_size'].iloc[
                i + 1] > avg_body:
                if df['close'].iloc[i] > df['open'].iloc[i]:
                    ob_price = df['high'].iloc[i]
                    break

        # 6. FAIR VALUE GAP (FVG)
        c1_high, c1_low = df['high'].iloc[-3], df['low'].iloc[-3]
        c3_high, c3_low = df['high'].iloc[-1], df['low'].iloc[-1]

        fvg_result = "None"
        fvg_size = 0
        if c3_low > c1_high:  # Bullish
            fvg_size = round(c3_low - c1_high, 2)
            fvg_result = f"Bullish (+{fvg_size}$)"
        elif c3_high < c1_low:  # Bearish
            fvg_size = round(c1_low - c3_high, 2)
            fvg_result = f"Bearish (-{fvg_size}$)"

        # 7. SMT DIVERGENCE (Uproszczone)
        smt_warning = "Brak"
        if trend == "bull" and usdjpy_price > df['close'].iloc[-10]:  # Dolar rośnie ze złotem
            smt_warning = "⚠️ SMT Divergence (Dolar rośnie ze złotem!)"

        return {
            "price": round(price, 2),
            "rsi": round(current_rsi, 1),
            "dxy": usdjpy_price,
            "trend": trend,
            "structure": market_structure,
            "fvg": fvg_result,
            "fvg_size": fvg_size,
            "eq_level": eq_level,
            "ob_price": round(ob_price, 2),
            "is_discount": is_discount,
            "is_premium": is_premium,
            "smt": smt_warning
        }

    except Exception as e:
        print(f"❌ Błąd silnika SMC Master: {e}")
        return None

    # Pozostałe funkcje pomocnicze (get_exchange_rate itp.) zostają bez zmian

    except Exception as e:
        print(f"Błąd silnika SMC: {e}")
        return None


def get_exchange_rate(base: str = "USD", to: str = "PLN") -> float | None:
    """
    Pobiera aktualny kurs wymiany walut z Twelve Data.

    Parametry:
        base — waluta bazowa (np. "USD")
        to   — waluta docelowa (np. "PLN")

    Zwraca:
        Kurs wymiany jako float, lub None jeśli API nie odpowiedziało poprawnie.

    Używane przez finance.py do przeliczania kapitału użytkownika na USD.
    """
    symbol = f"{base}/{to}"
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TD_API_KEY}"

    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'price' not in data:
            print(f"⚠️ Błąd pobierania kursu {symbol}: {data.get('message')}")
            return None
        return float(data['price'])
    except Exception as e:
        print(f"❌ Błąd w get_exchange_rate: {e}")
        return None


def detect_smt_divergence(gold_prices, usdjpy_prices):
    """
    Wykrywa SMT: Jeśli Złoto robi wyższy szczyt (HH),
    a USD/JPY (Dolar) NIE robi niższego dołka (LL), mamy dywergencję.
    To sygnał, że wzrost złota jest fałszywy (Manipulation).
    """
    # Logika porównania ostatnich szczytów/dołków
    # Jeśli Złoto rośnie, a Dolar też rośnie = SMT Divergence (Sygnał ostrzegawczy)
    if gold_prices[-1] > gold_prices[-2] and usdjpy_prices[-1] > usdjpy_prices[-2]:
        return "⚠️ WYKRYTO SMT DIVERGENCE: Dolar i Złoto rosną razem! To pułapka."
    return "Brak anomalii SMT."

def find_order_block(df):
    """Szuka ostatniej świecy spadkowej przed impulsem wzrostowym (BULL OB)
    lub wzrostowej przed spadkowym (BEAR OB)."""
    # Logika szukania OB na ostatnich 20 świecach
    last_candles = df.tail(20)
    # ... (skrócona logika dla przykładu) ...
    ob_price = last_candles['low'].min() if trend == 'bull' else last_candles['high'].max()
    return ob_price

def get_equilibrium(df):
    """Oblicza poziom 0.5 (50%) ostatniego znaczącego ruchu (Swing High/Low)."""
    high = df['high'].tail(50).max()
    low = df['low'].tail(50).min()
    eq_level = (high + low) / 2
    return {
        "eq": round(eq_level, 2),
        "is_discount": df['close'].iloc[-1] < eq_level, # Taniej niż 50% - kupuj
        "is_premium": df['close'].iloc[-1] > eq_level   # Drożej niż 50% - sprzedawaj
    }