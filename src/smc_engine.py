# smc_engine.py
"""
smc_engine.py — silnik analizy technicznej Smart Money Concepts.

Odpowiada za:
  - Pobieranie danych OHLCV złota (XAU/USD) z Twelve Data API
  - Obliczanie wskaźników: RSI (14) i EMA (20)
  - Wyznaczanie trendu (bull/bear) na podstawie relacji ceny do EMA
  - Wykrywanie Fair Value Gap (FVG) — luki płynności między świecami
  - Obliczanie poziomu Equilibrium (EQ) z ostatnich 20 świec
  - Pobieranie kursu USD/JPY jako proxy siły dolara
  - Detekcja Swing High/Low, Liquidity Grab, Market Structure Shift, Order Blocks, DBR/RBD
  - Obliczanie reżimu makro na podstawie USD/JPY Z-score i ATR
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from src.config import TD_API_KEY

# src/smc_engine.py – dodaj na początku, po importach
import time
import requests
from src.logger import logger


def request_with_retry(url, max_retries=3, backoff=2):
    """Wykonuje zapytanie GET z obsługą rate limit (429)."""
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 429:
                wait = backoff ** attempt
                logger.warning(f"Rate limit (429) – czekam {wait}s...")
                time.sleep(wait)
                continue
            return response.json()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff ** attempt)
    return {}


def get_usdjpy_history(tf: str, length: int = 30) -> tuple:
    """
    Pobiera historyczne dane USD/JPY z Twelve Data i zwraca (lista cen, ostatnia cena).
    """
    try:
        td_tf = tf if "min" in tf else tf.replace("m", "min")
        url = f"https://api.twelvedata.com/time_series?symbol=USD/JPY&interval={td_tf}&apikey={TD_API_KEY}&outputsize={length}"
        data = request_with_retry(url)
        if 'values' not in data:
            return [], 0
        df = pd.DataFrame(data['values'])
        df['close'] = pd.to_numeric(df['close'])
        df = df.iloc[::-1].reset_index(drop=True)
        prices = df['close'].tolist()
        current = prices[-1] if prices else 0
        return prices, current
    except Exception as e:
        logger.error(f"Błąd pobierania USD/JPY: {e}")
        return [], 0


def calculate_atr(df: pd.DataFrame, length: int = 14) -> float:
    """Oblicza ATR na podstawie danych OHLC."""
    # True Range
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=length).mean().iloc[-1]
    return round(atr, 2)


def get_macro_regime(usdjpy_prices: list, current_usdjpy: float, atr: float, atr_mean: float) -> dict:
    """
    Określa reżim makro na podstawie Z-score USD/JPY i porównania ATR z jego średnią.
    """
    if len(usdjpy_prices) >= 20:
        mean = np.mean(usdjpy_prices[-20:])
        std = np.std(usdjpy_prices[-20:])
        zscore = (current_usdjpy - mean) / std if std != 0 else 0
    else:
        zscore = 0

    if zscore < -1 and atr > atr_mean:
        regime = "zielony"
    elif zscore > 1 and atr < atr_mean:
        regime = "czerwony"
    else:
        regime = "neutralny"

    return {
        "regime": regime,
        "usdjpy": current_usdjpy,
        "usdjpy_zscore": round(zscore, 2),
        "atr": atr,
        "atr_mean": round(atr_mean, 2)
    }


def detect_swing_points(df: pd.DataFrame, window: int = 5) -> dict:
    """
    Wykrywa Swing Highs i Swing Lows na podstawie lokalnych ekstremów.
    window – liczba świec po obu stronach do porównania.
    Zwraca ostatni znaczący Swing High i Swing Low.
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    swing_highs = []
    swing_lows = []
    for i in range(window, n - window):
        if all(highs[i] >= highs[i-window:i+window+1]):
            swing_highs.append((i, highs[i]))
        if all(lows[i] <= lows[i-window:i+window+1]):
            swing_lows.append((i, lows[i]))
    if swing_highs:
        last_swing_high = swing_highs[-1][1]
        last_swing_high_idx = swing_highs[-1][0]
    else:
        last_swing_high = df['high'].max()
        last_swing_high_idx = n-1
    if swing_lows:
        last_swing_low = swing_lows[-1][1]
        last_swing_low_idx = swing_lows[-1][0]
    else:
        last_swing_low = df['low'].min()
        last_swing_low_idx = n-1
    return {
        "swing_high": round(last_swing_high, 2),
        "swing_low": round(last_swing_low, 2),
        "swing_high_idx": last_swing_high_idx,
        "swing_low_idx": last_swing_low_idx
    }


def detect_liquidity_grab(df: pd.DataFrame, swing_points: dict) -> tuple:
    """
    Sprawdza, czy cena przebiła ostatni Swing Low (dla bull) lub Swing High (dla bear)
    i wróciła powyżej/poniżej (Liquidity Grab). Zwraca (czy_grab, kierunek_grabu).
    """
    last_swing_low = swing_points["swing_low"]
    last_swing_high = swing_points["swing_high"]
    current_low = df['low'].iloc[-1]
    current_high = df['high'].iloc[-1]
    close = df['close'].iloc[-1]

    # Bullish grab: cena spadła poniżej last_swing_low, ale zamknęła powyżej
    if current_low < last_swing_low and close > last_swing_low:
        return True, "bullish"
    # Bearish grab: cena wzrosła powyżej last_swing_high, ale zamknęła poniżej
    if current_high > last_swing_high and close < last_swing_high:
        return True, "bearish"
    return False, None


def detect_market_structure_shift(df: pd.DataFrame, swing_points: dict, liquidity_grab: tuple) -> bool:
    """
    Sprawdza, czy po Liquidity Grab nastąpiła zmiana struktury (MSS).
    MSS = cena zamknęła powyżej ostatniego Swing High (dla bull) lub poniżej Swing Low (dla bear).
    """
    grab, grab_dir = liquidity_grab
    if not grab:
        return False
    close = df['close'].iloc[-1]
    if grab_dir == "bullish" and close > swing_points["swing_high"]:
        return True
    if grab_dir == "bearish" and close < swing_points["swing_low"]:
        return True
    return False


def detect_order_block(df: pd.DataFrame, trend: str) -> float:
    """
    Ulepszona detekcja Order Block.
    Dla trendu bull: ostatnia świeca spadkowa przed silną świecą wzrostową (body > avg_body).
    Dla trendu bear: ostatnia świeca wzrostowa przed silną świecą spadkową.
    Zwraca cenę OB (low dla bull, high dla bear).
    """
    df['body'] = abs(df['close'] - df['open'])
    avg_body = df['body'].tail(20).mean()
    ob_price = df['close'].iloc[-1]  # fallback

    for i in range(len(df)-2, max(0, len(df)-30), -1):
        if trend == "bull":
            # Szukamy świecy spadkowej (close < open) przed dużą wzrostową (i+1)
            if df['close'].iloc[i] < df['open'].iloc[i] and df['body'].iloc[i+1] > avg_body:
                if df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    ob_price = df['low'].iloc[i]
                    break
        else:
            # Szukamy świecy wzrostowej przed dużą spadkową
            if df['close'].iloc[i] > df['open'].iloc[i] and df['body'].iloc[i+1] > avg_body:
                if df['close'].iloc[i+1] < df['open'].iloc[i+1]:
                    ob_price = df['high'].iloc[i]
                    break
    return round(ob_price, 2)


def detect_fvg(df: pd.DataFrame) -> dict:
    """
    Wykrywa Fair Value Gap (FVG) – luka między świecą i-2 a i.
    Zwraca słownik: typ (bullish/bearish), górna/dolna granica, wielkość.
    """
    fvg = {
        "type": None,
        "upper": None,
        "lower": None,
        "size": 0,
        "description": "None"
    }
    if len(df) < 3:
        return fvg
    c1_high = df['high'].iloc[-3]
    c1_low = df['low'].iloc[-3]
    c3_high = df['high'].iloc[-1]
    c3_low = df['low'].iloc[-1]

    if c3_low > c1_high:
        fvg["type"] = "bullish"
        fvg["lower"] = c1_high
        fvg["upper"] = c3_low
        fvg["size"] = round(c3_low - c1_high, 2)
        fvg["description"] = f"Bullish (+{fvg['size']}$)"
    elif c3_high < c1_low:
        fvg["type"] = "bearish"
        fvg["lower"] = c3_high
        fvg["upper"] = c1_low
        fvg["size"] = round(c1_low - c3_high, 2)
        fvg["description"] = f"Bearish (-{fvg['size']}$)"
    return fvg


def detect_dbr_rbd(df: pd.DataFrame, window: int = 5) -> dict:
    """
    Wykrywa formacje DBR (Drop-Base-Rally) i RBD (Rally-Base-Drop) na ostatnich świecach.
    Zwraca słownik z typem i strefą bazy.
    """
    result = {"type": None, "base_low": None, "base_high": None}
    if len(df) < 20:
        return result

    # Sprawdzamy ostatnie 15 świec
    recent = df.tail(15)
    # Drop (spadek)
    drop_start = recent['close'].iloc[0]
    drop_end = recent['close'].iloc[5]
    drop_pct = (drop_end - drop_start) / drop_start
    if drop_pct < -0.01:  # spadek > 1%
        # Sprawdzamy konsolidację (zakres ostatnich 5 świec)
        base_low = recent['low'].iloc[6:11].min()
        base_high = recent['high'].iloc[6:11].max()
        base_range = (base_high - base_low) / base_low
        if base_range < 0.005:  # zakres < 0.5%
            # Rally
            rally_start = recent['close'].iloc[11]
            rally_end = recent['close'].iloc[-1]
            rally_pct = (rally_end - rally_start) / rally_start
            if rally_pct > 0.01:
                result["type"] = "DBR"
                result["base_low"] = round(base_low, 2)
                result["base_high"] = round(base_high, 2)
    # Podobnie dla RBD (wzrost -> konsolidacja -> spadek)
    # Sprawdzamy wzrost
    rise_start = recent['close'].iloc[0]
    rise_end = recent['close'].iloc[5]
    rise_pct = (rise_end - rise_start) / rise_start
    if rise_pct > 0.01:
        base_low = recent['low'].iloc[6:11].min()
        base_high = recent['high'].iloc[6:11].max()
        base_range = (base_high - base_low) / base_low
        if base_range < 0.005:
            drop_start2 = recent['close'].iloc[11]
            drop_end2 = recent['close'].iloc[-1]
            drop_pct2 = (drop_end2 - drop_start2) / drop_start2
            if drop_pct2 < -0.01:
                result["type"] = "RBD"
                result["base_low"] = round(base_low, 2)
                result["base_high"] = round(base_high, 2)

    return result


def get_exchange_rate(base: str = "USD", to: str = "PLN") -> float | None:
    """
    Pobiera aktualny kurs wymiany walut z Twelve Data.
    """
    symbol = f"{base}/{to}"
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TD_API_KEY}"

    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if 'price' not in data:
            logger.warning(f"⚠️ Błąd pobierania kursu {symbol}: {data.get('message')}")
            return None
        return float(data['price'])
    except Exception as e:
        logger.error(f"❌ Błąd w get_exchange_rate: {e}")
        return None
# ================== NOWE FUNKCJE ==================

def find_order_blocks(df: pd.DataFrame, trend: str, max_blocks: int = 3) -> list:
    """
    Wyszukuje kilka ostatnich Order Blocków (OB) dla danego trendu.
    Zwraca listę słowników: [{'price': float, 'type': 'bullish'/'bearish'}, ...]
    """
    df['body'] = abs(df['close'] - df['open'])
    avg_body = df['body'].tail(20).mean()
    blocks = []

    for i in range(len(df)-2, max(0, len(df)-50), -1):
        if len(blocks) >= max_blocks:
            break
        if trend == "bull":
            # Szukamy świecy spadkowej (close < open) przed silną wzrostową
            if df['close'].iloc[i] < df['open'].iloc[i] and df['body'].iloc[i+1] > avg_body:
                if df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    ob_price = df['low'].iloc[i]
                    blocks.append({'price': round(ob_price, 2), 'type': 'bullish'})
        else:
            # Szukamy świecy wzrostowej przed silną spadkową
            if df['close'].iloc[i] > df['open'].iloc[i] and df['body'].iloc[i+1] > avg_body:
                if df['close'].iloc[i+1] < df['open'].iloc[i+1]:
                    ob_price = df['high'].iloc[i]
                    blocks.append({'price': round(ob_price, 2), 'type': 'bearish'})
    return blocks


def detect_bos(df: pd.DataFrame, swing_points: dict) -> tuple:
    """
    Wykrywa Break of Structure (BOS).
    Zwraca (bos_bullish, bos_bearish) – bool.
    BOS bullish: zamknięcie powyżej ostatniego Swing High.
    BOS bearish: zamknięcie poniżej ostatniego Swing Low.
    """
    close = df['close'].iloc[-1]
    bullish = close > swing_points['swing_high']
    bearish = close < swing_points['swing_low']
    return bullish, bearish


def detect_choch(df: pd.DataFrame, window: int = 10) -> tuple:
    """
    Wykrywa Change of Character (CHoCH) na podstawie ostatnich swingów.
    Zwraca (choch_bullish, choch_bearish) – bool.
    Uproszczona wersja: porównuje dwa ostatnie swing high i swing low.
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)
    swing_highs = []
    swing_lows = []
    for i in range(window, n - window):
        if all(highs[i] >= highs[i-window:i+window+1]):
            swing_highs.append(i)
        if all(lows[i] <= lows[i-window:i+window+1]):
            swing_lows.append(i)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False, False

    last_high_idx = swing_highs[-1]
    prev_high_idx = swing_highs[-2]
    last_low_idx = swing_lows[-1]
    prev_low_idx = swing_lows[-2]

    # Bullish CHoCH: wyższy dołek i wyższy szczyt niż poprzednie
    bullish = (df['low'].iloc[last_low_idx] > df['low'].iloc[prev_low_idx] and
               df['high'].iloc[last_high_idx] > df['high'].iloc[prev_high_idx])

    # Bearish CHoCH: niższy szczyt i niższy dołek niż poprzednie
    bearish = (df['high'].iloc[last_high_idx] < df['high'].iloc[prev_high_idx] and
               df['low'].iloc[last_low_idx] < df['low'].iloc[prev_low_idx])

    return bullish, bearish

# ================== NOWE FUNKCJE (doklej na końcu pliku) ==================



def detect_advanced_choch(df_main: pd.DataFrame, df_higher: pd.DataFrame, window: int = 10) -> tuple:
    """
    Wykrywa Change of Character na podstawie dwóch interwałów.
    Zwraca (choch_bullish, choch_bearish) – bool dla interwału głównego,
    oraz (choch_higher_bullish, choch_higher_bearish) dla H1.
    """
    # CHoCH na głównym (uproszczone, ale możemy użyć istniejącej funkcji)
    choch_main_bull, choch_main_bear = detect_choch(df_main, window)

    # CHoCH na H1 (wywołaj detect_choch dla wyższego interwału)
    choch_higher_bull, choch_higher_bear = detect_choch(df_higher, window)

    # Łączymy: jeżeli którykolwiek z interwałów ma CHoCH, uznajemy za sygnał
    # (można osobno dodać jako czynnik)
    return (choch_main_bull, choch_main_bear, choch_higher_bull, choch_higher_bear)

def find_ob_confluence(df: pd.DataFrame, trend: str, threshold: float = 0.5) -> int:
    """
    Wykrywa konfluencję Order Blocków – ile OB znajduje się w pobliżu (w granicach threshold %).
    Zwraca liczbę OB w tym samym obszarze (max 3).
    """
    blocks = find_order_blocks(df, trend, max_blocks=5)
    if len(blocks) < 2:
        return 0
    # Grupowanie OB o zbliżonych cenach (np. w granicach 0.5% ceny)
    groups = []
    for b in blocks:
        price = b['price']
        found = False
        for g in groups:
            if abs(g[0] - price) / price < threshold:
                g.append(price)
                found = True
                break
        if not found:
            groups.append([price])
    max_confluence = max(len(g) for g in groups)
    return min(max_confluence, 3)

def detect_choch_h1(df_h1: pd.DataFrame, df_current: pd.DataFrame) -> tuple:
    """
    Wykrywa Change of Character na H1 na podstawie ostatnich swingów.
    Zwraca (choch_bullish_h1, choch_bearish_h1).
    """
    # Używamy funkcji detect_choch ale na danych H1
    # Można też zrobić własną, porównując ostatnie dwa swingi na H1
    bullish, bearish = detect_choch(df_h1, window=10)
    return bullish, bearish

def detect_supply_demand(df: pd.DataFrame) -> dict:
    """
    Wykrywa klasyczne strefy Supply (opór) i Demand (wsparcie) na podstawie lokalnych szczytów/dołków.
    Zwraca słownik z kluczami 'supply' (list) i 'demand' (list).
    """
    # Uproszczona wersja: znajdujemy swing high i low, które były poprzedzone ruchem
    swings = detect_swing_points(df)
    # Strefa Supply: ostatni swing high
    supply = [swings['swing_high']] if swings['swing_high'] else []
    # Strefa Demand: ostatni swing low
    demand = [swings['swing_low']] if swings['swing_low'] else []
    # Można dodać więcej stref (np. wcześniejsze)
    return {'supply': supply, 'demand': demand}

# ================== FUNKCJE POMOCNICZE DLA DYWERGENCJI RSI ==================

def find_swings(values: list, lookback: int = 5, min_swings: int = 2):
    """
    Zwraca indeksy lokalnych minimów i maksimów w liście wartości.
    lookback – liczba świec po obu stronach do porównania.
    Zwraca (swing_highs, swing_lows) – listy indeksów.
    """
    n = len(values)
    swing_highs = []
    swing_lows = []
    for i in range(lookback, n - lookback):
        # Sprawdzenie, czy punkt i jest lokalnym maksimum
        if all(values[i] >= values[i - lookback:i + lookback + 1]):
            swing_highs.append(i)
        # Sprawdzenie, czy punkt i jest lokalnym minimum
        if all(values[i] <= values[i - lookback:i + lookback + 1]):
            swing_lows.append(i)
    return swing_highs, swing_lows


def detect_rsi_divergence(df: pd.DataFrame, lookback: int = 20, swing_lookback: int = 5) -> tuple:
    """
    Wykrywa regularną dywergencję RSI (byczą i niedźwiedzią).
    Zwraca (bullish_div, bearish_div) – bool.
    """
    if len(df) < lookback:
        return False, False

    # Pobieramy ostatnie 'lookback' świec
    recent = df.tail(lookback)
    close = recent['close'].values
    rsi = recent['rsi'].values

    # Znajdź swing high i swing low dla ceny i RSI
    price_highs, price_lows = find_swings(close, swing_lookback)
    rsi_highs, rsi_lows = find_swings(rsi, swing_lookback)

    bullish_div = False
    bearish_div = False

    # Dywergencja bycza: cena robi niższy dołek, RSI wyższy dołek
    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        last_price_low = price_lows[-1]
        prev_price_low = price_lows[-2]
        last_rsi_low = rsi_lows[-1]
        prev_rsi_low = rsi_lows[-2]

        if (close[last_price_low] < close[prev_price_low] and
            rsi[last_rsi_low] > rsi[prev_rsi_low]):
            bullish_div = True

    # Dywergencja niedźwiedzia: cena robi wyższy szczyt, RSI niższy szczyt
    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        last_price_high = price_highs[-1]
        prev_price_high = price_highs[-2]
        last_rsi_high = rsi_highs[-1]
        prev_rsi_high = rsi_highs[-2]

        if (close[last_price_high] > close[prev_price_high] and
            rsi[last_rsi_high] < rsi[prev_rsi_high]):
            bearish_div = True

    return bullish_div, bearish_div

# ================== MODYFIKACJA get_smc_analysis ==================
# W funkcji get_smc_analysis, po wywołaniu detect_swing_points(df), dodaj:

# order_blocks = find_order_blocks(df, trend)
# bos_bullish, bos_bearish = detect_bos(df, swings)
# choch_bullish, choch_bearish = detect_choch(df)

# Następnie w słowniku zwracanym dodaj nowe klucze:


from src.cache import cached_with_key

def _smc_cache_key(tf: str) -> str:
    return f"smc_{tf}"

@cached_with_key(_smc_cache_key, ttl=10)

def get_smc_analysis(tf: str) -> dict | None:
    """
    Główna funkcja – rozszerzona o nowe wskaźniki SMC i makro.
    """
    try:
        td_tf = tf if "min" in tf else tf.replace("m", "min")

        # 1. POBIERANIE DANYCH ZŁOTA
        url_gold = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={td_tf}&apikey={TD_API_KEY}&outputsize=100"
        data_gold = request_with_retry(url_gold)
        if 'values' not in data_gold:
            logger.warning(f"Błąd Twelve Data: {data_gold.get('message')}")
            return None

        df = pd.DataFrame(data_gold['values'])
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].apply(pd.to_numeric)
        df = df.iloc[::-1].reset_index(drop=True)

        # 2. POBIERANIE HISTORYCZNEGO USD/JPY
        usdjpy_prices, current_usdjpy = get_usdjpy_history(tf, length=30)

        # 3. WSKAŹNIKI TECHNICZNE
        df['rsi'] = ta.rsi(df['close'], length=14)
        ema20 = ta.ema(df['close'], length=20)
        price = df['close'].iloc[-1]
        current_rsi = df['rsi'].iloc[-1]
        current_ema = ema20.iloc[-1]
        trend = "bull" if price > current_ema else "bear"

        # 4. ATR i reżim makro
        atr = calculate_atr(df)
        # Średnia ATR z całego dostępnego okresu (lub ostatnich 14 wartości)
        atr_mean = df['tr'].rolling(window=14).mean().mean() if 'tr' in df.columns else atr
        macro = get_macro_regime(usdjpy_prices, current_usdjpy, atr, atr_mean)

        # 5. SWING POINTS
        swings = detect_swing_points(df)

        # 6. LIQUIDITY GRAB
        grab, grab_dir = detect_liquidity_grab(df, swings)

        # 7. MARKET STRUCTURE SHIFT
        mss = detect_market_structure_shift(df, swings, (grab, grab_dir))

        # 8. ORDER BLOCK
        ob_price = detect_order_block(df, trend)

        # 9. FAIR VALUE GAP
        fvg = detect_fvg(df)

        # 10. EQUILIBRIUM
        swing_high = swings["swing_high"]
        swing_low = swings["swing_low"]
        eq_level = round((swing_high + swing_low) / 2, 2)
        is_discount = price < eq_level
        is_premium = price > eq_level

        # 11. DBR/RBD
        dbr_rbd = detect_dbr_rbd(df)

        # 12. SMT DIVERGENCE (uproszczone)
        smt_warning = "Brak"
        if usdjpy_prices and len(usdjpy_prices) >= 10:
            usdjpy_recent = usdjpy_prices[-10:]
            if trend == "bull" and usdjpy_recent[-1] > usdjpy_recent[0]:
                smt_warning = "⚠️ SMT Divergence (Dolar rośnie ze złotem!)"
            elif trend == "bear" and usdjpy_recent[-1] < usdjpy_recent[0]:
                smt_warning = "⚠️ SMT Divergence (Dolar spada ze złotem!)"

        # 13. OKREŚLENIE STRUKTURY (dla czytelności)
        if grab and mss:
            if grab_dir == "bullish":
                structure = f"Liquidity Grab (Bull) + MSS → trend bull"
            else:
                structure = f"Liquidity Grab (Bear) + MSS → trend bear"
        elif grab:
            structure = f"Liquidity Grab ({grab_dir}) – oczekuj MSS"
        elif mss:
            structure = "Market Structure Shift"
        else:
            structure = "Stable"

        # ========== NOWE DETEKCJE ==========
        order_blocks = find_order_blocks(df, trend)
        bos_bullish, bos_bearish = detect_bos(df, swings)
        choch_bullish, choch_bearish = detect_choch(df)
        ob_confluence = find_ob_confluence(df, trend)  # liczba OB w klastrze
        supply_demand = detect_supply_demand(df)  # klasyczne strefy
        rsi_div_bull, rsi_div_bear = detect_rsi_divergence(df)  # dywergencja RSI
        # ===================================

        return {
            "price": round(price, 2),
            "rsi": round(current_rsi, 1),
            "trend": trend,
            "swing_high": swings["swing_high"],
            "swing_low": swings["swing_low"],
            "liquidity_grab": grab,
            "liquidity_grab_dir": grab_dir,
            "mss": mss,
            "macro_regime": macro["regime"],
            "usdjpy": macro["usdjpy"],
            "usdjpy_zscore": macro["usdjpy_zscore"],
            "atr": macro["atr"],
            "atr_mean": macro["atr_mean"],
            "fvg_type": fvg["type"],
            "fvg_upper": fvg["upper"],
            "fvg_lower": fvg["lower"],
            "fvg_size": fvg["size"],
            "fvg": fvg["description"],
            "ob_price": ob_price,
            "eq_level": eq_level,
            "is_discount": is_discount,
            "is_premium": is_premium,
            "dbr_rbd_type": dbr_rbd["type"],
            "dbr_rbd_base_low": dbr_rbd.get("base_low"),
            "dbr_rbd_base_high": dbr_rbd.get("base_high"),
            "smt": smt_warning,
            "structure": structure,
            'order_blocks': order_blocks,
            'bos_bullish': bos_bullish,
            'bos_bearish': bos_bearish,
            'choch_bullish': choch_bullish,
            'choch_bearish': choch_bearish,
            'ob_confluence': ob_confluence,
            'supply': supply_demand['supply'],
            'demand': supply_demand['demand'],
            'rsi_div_bull': rsi_div_bull,
            'rsi_div_bear': rsi_div_bear,
        }

    except Exception as e:
        logger.error(f"❌ Błąd silnika SMC Master: {e}")
        return None

