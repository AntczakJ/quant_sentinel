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
  - Caching wyników (TTL 60 sekund) dla optymalizacji wydajności
  - Session awareness (Asian/London/NY killzones)
  - Multi-timeframe confluence scoring
"""

import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timezone
from src.cache import cached_with_key
from src.logger import logger


# ==================== SESSION / KILLZONE DETECTION ====================

def get_active_session(utc_hour: int = None) -> dict:
    """
    Określa aktywną sesję tradingową i killzone na podstawie godziny UTC.

    Killzones (godziny UTC):
    - Asian:   00:00-06:00 (niska zmienność na złocie)
    - London:  07:00-10:00 (wysoka zmienność — otwarcie Europy)
    - NY:      12:00-15:00 (najwyższa zmienność — otwarcie USA)
    - Overlap: 12:00-16:00 (London+NY — max płynność)

    XAU/USD: weekend zamknięty, przerwa 23:00-00:00 UTC.
    """
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour

    if 0 <= utc_hour < 6:
        session = 'asian'
        is_killzone = False
    elif 6 <= utc_hour < 7:
        session = 'london_pre'
        is_killzone = False
    elif 7 <= utc_hour < 10:
        session = 'london'
        is_killzone = True  # London killzone
    elif 10 <= utc_hour < 12:
        session = 'london'
        is_killzone = False
    elif 12 <= utc_hour < 15:
        session = 'new_york'
        is_killzone = True  # NY killzone
    elif 15 <= utc_hour < 17:
        session = 'new_york'
        is_killzone = False
    elif 17 <= utc_hour < 20:
        session = 'new_york_late'
        is_killzone = False
    elif 20 <= utc_hour < 23:
        session = 'off_hours'
        is_killzone = False
    else:
        session = 'off_hours'
        is_killzone = False

    return {
        'session': session,
        'is_killzone': is_killzone,
        'utc_hour': utc_hour,
        'volatility_expected': 'high' if is_killzone else ('medium' if session in ('london', 'new_york') else 'low'),
    }


def _get_data_provider():
    """Lazy import aby uniknąć cyklicznych importów."""
    from src.data_sources import get_provider
    return get_provider()


def get_usdjpy_history(tf: str, length: int = 30) -> tuple:
    """
    Pobiera historyczne dane USD/JPY przez DataProvider (rate limited, cached).
    Zwraca (lista cen, ostatnia cena).
    """
    try:
        provider = _get_data_provider()
        df = provider.get_candles('USD/JPY', tf, length)
        if df is None or df.empty:
            return [], 0
        prices = df['close'].tolist()
        current = prices[-1] if prices else 0
        return prices, current
    except Exception as e:
        logger.error(f"Błąd pobierania USD/JPY: {e}")
        return [], 0


def calculate_atr(df: pd.DataFrame, length: int = 14) -> float:
    """Oblicza ATR na podstawie danych OHLC. Zapisuje kolumnę 'tr' w df."""
    # True Range
    high = df['high']
    low = df['low']
    close = df['close']
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['tr'] = tr  # Zapisz TR do DataFrame — używane potem do obliczenia atr_mean
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
        if all(highs[i] >= highs[j] for j in range(i-window, i+window+1) if j != i):
            swing_highs.append((i, highs[i]))
        if all(lows[i] <= lows[j] for j in range(i-window, i+window+1) if j != i):
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
    Dla trendu bull: ostatnia świeca spadkowa przed silną świecą wzrostową (body > 1.5 * avg_body).
    Dla trendu bear: ostatnia świeca wzrostowa przed silną świecą spadkową.
    Sprawdza też, czy OB nie został już „zmitigowany" (cena przeszła przez niego).
    Zwraca cenę OB (low dla bull, high dla bear).
    """
    body = abs(df['close'] - df['open'])
    avg_body = body.tail(20).mean()
    ob_price = df['close'].iloc[-1]  # fallback
    impulse_mult = 1.5  # Silniejszy filtr — wymaga 1.5x średniego body

    for i in range(len(df)-2, max(0, len(df)-30), -1):
        if trend == "bull":
            if df['close'].iloc[i] < df['open'].iloc[i] and body.iloc[i+1] > avg_body * impulse_mult:
                if df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    candidate = df['low'].iloc[i]
                    # Sprawdź, czy OB nie został zmitigowany (cena spadła poniżej)
                    mitigated = any(df['low'].iloc[j] < candidate for j in range(i+2, len(df)))
                    if not mitigated:
                        ob_price = candidate
                        break
        else:
            if df['close'].iloc[i] > df['open'].iloc[i] and body.iloc[i+1] > avg_body * impulse_mult:
                if df['close'].iloc[i+1] < df['open'].iloc[i+1]:
                    candidate = df['high'].iloc[i]
                    mitigated = any(df['high'].iloc[j] > candidate for j in range(i+2, len(df)))
                    if not mitigated:
                        ob_price = candidate
                        break
    return round(ob_price, 2)


def detect_fvg(df: pd.DataFrame, atr: float = None) -> dict:
    """
    Wykrywa Fair Value Gap (FVG) – luka między świecą i-2 a i.
    Filtruje szum: FVG musi mieć rozmiar >= 0.3 * ATR (jeśli ATR dostępny).
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

    min_gap = atr * 0.3 if atr and atr > 0 else 0  # Filtr szumu

    c1_high = df['high'].iloc[-3]
    c1_low = df['low'].iloc[-3]
    c3_high = df['high'].iloc[-1]
    c3_low = df['low'].iloc[-1]

    if c3_low > c1_high:
        gap_size = c3_low - c1_high
        if gap_size >= min_gap:
            fvg["type"] = "bullish"
            fvg["lower"] = c1_high
            fvg["upper"] = c3_low
            fvg["size"] = round(gap_size, 2)
            fvg["description"] = f"Bullish (+{fvg['size']}$)"
    elif c3_high < c1_low:
        gap_size = c1_low - c3_high
        if gap_size >= min_gap:
            fvg["type"] = "bearish"
            fvg["lower"] = c3_high
            fvg["upper"] = c1_low
            fvg["size"] = round(gap_size, 2)
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
    Pobiera aktualny kurs wymiany walut przez DataProvider (rate limited).
    """
    try:
        provider = _get_data_provider()
        rate = provider.get_exchange_rate(base, to)
        return rate
    except Exception as e:
        logger.error(f"❌ Błąd w get_exchange_rate: {e}")
        return None
# ================== NOWE FUNKCJE ==================

def find_order_blocks(df: pd.DataFrame, trend: str, max_blocks: int = 3) -> list:
    """
    Wyszukuje kilka ostatnich Order Blocków (OB) dla danego trendu.
    Zwraca listę słowników: [{'price': float, 'type': 'bullish'/'bearish'}, ...]
    """
    body = abs(df['close'] - df['open'])
    avg_body = body.tail(20).mean()
    blocks = []

    for i in range(len(df)-2, max(0, len(df)-50), -1):
        if len(blocks) >= max_blocks:
            break
        if trend == "bull":
            # Szukamy świecy spadkowej (close < open) przed silną wzrostową
            if df['close'].iloc[i] < df['open'].iloc[i] and body.iloc[i+1] > avg_body:
                if df['close'].iloc[i+1] > df['open'].iloc[i+1]:
                    ob_price = df['low'].iloc[i]
                    blocks.append({'price': round(ob_price, 2), 'type': 'bullish'})
        else:
            # Szukamy świecy wzrostowej przed silną spadkową
            if df['close'].iloc[i] > df['open'].iloc[i] and body.iloc[i+1] > avg_body:
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
        if all(highs[i] >= highs[j] for j in range(i-window, i+window+1) if j != i):
            swing_highs.append(i)
        if all(lows[i] <= lows[j] for j in range(i-window, i+window+1) if j != i):
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



def find_ob_confluence(df: pd.DataFrame, trend: str, threshold: float = 0.005) -> int:
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
        # Sprawdzenie, czy punkt i jest lokalnym maksimum (bez porównania z samym sobą)
        if all(values[i] >= values[j] for j in range(i - lookback, i + lookback + 1) if j != i):
            swing_highs.append(i)
        # Sprawdzenie, czy punkt i jest lokalnym minimum
        if all(values[i] <= values[j] for j in range(i - lookback, i + lookback + 1) if j != i):
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


@cached_with_key(lambda tf: f"smc_analysis_{tf}", ttl=60)
def get_smc_analysis(tf: str) -> dict | None:
    """
    Główna funkcja – rozszerzona o nowe wskaźniki SMC, candlestick patterns, Ichimoku i makro.

    Wyniki są cachowane przez 60 sekund dla optymalizacji wydajności.
    Klucz cache: "smc_analysis_<interwał>"
    """
    try:
        # === Import dodatkowych modułów detekcji ===
        from src.candlestick_patterns import engulfing, pin_bar, inside_bar
        from src.indicators import ichimoku, volume_profile

        # 1. POBIERANIE DANYCH ZŁOTA (przez DataProvider – rate limited, cached)
        provider = _get_data_provider()
        df = provider.get_candles('XAU/USD', tf, 100)
        if df is None or df.empty:
            logger.warning(f"Brak danych XAU/USD z DataProvider dla {tf}")
            return None


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

        # 9. FAIR VALUE GAP (z filtrem ATR)
        fvg = detect_fvg(df, atr=atr)

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

        # ========== CANDLESTICK PATTERNS ==========
        engulfing_signal = engulfing(df)  # 'bullish'|'bearish'|False
        pin_bar_signal = pin_bar(df)      # 'bullish'|'bearish'|False
        inside_bar_signal = inside_bar(df)  # True|False

        # ========== ICHIMOKU CLOUD ==========
        ichimoku_above_cloud = False
        ichimoku_below_cloud = False
        try:
            ichi_df = ichimoku(df)
            if not ichi_df.empty:
                span_a = ichi_df['senkou_span_a'].iloc[-1]
                span_b = ichi_df['senkou_span_b'].iloc[-1]
                cloud_top = max(span_a, span_b) if pd.notna(span_a) and pd.notna(span_b) else None
                cloud_bottom = min(span_a, span_b) if pd.notna(span_a) and pd.notna(span_b) else None
                if cloud_top and cloud_bottom:
                    ichimoku_above_cloud = price > cloud_top
                    ichimoku_below_cloud = price < cloud_bottom
        except Exception as e:
            logger.debug(f"Ichimoku calc error: {e}")

        # ========== VOLUME PROFILE (POC) ==========
        poc_price = price
        try:
            vp = volume_profile(df)
            poc_price = vp.get('poc', price)
        except Exception as e:
            logger.debug(f"Volume profile calc error: {e}")

        near_poc = abs(price - poc_price) < atr * 0.5  # cena blisko POC

        # ========== SESSION / KILLZONE ==========
        session_info = get_active_session()
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
            # Candlestick patterns
            'engulfing': engulfing_signal,
            'pin_bar': pin_bar_signal,
            'inside_bar': inside_bar_signal,
            # Ichimoku Cloud
            'ichimoku_above_cloud': ichimoku_above_cloud,
            'ichimoku_below_cloud': ichimoku_below_cloud,
            # Volume Profile
            'poc_price': round(poc_price, 2),
            'near_poc': near_poc,
            # Session / Killzone
            'session': session_info['session'],
            'is_killzone': session_info['is_killzone'],
            'volatility_expected': session_info['volatility_expected'],
        }

    except Exception as e:
        logger.error(f"❌ Błąd silnika SMC Master: {e}")
        return None


# ==================== MULTI-TIMEFRAME CONFLUENCE ====================

@cached_with_key(lambda: "mtf_confluence", ttl=120)
def get_mtf_confluence(symbol: str = "XAU/USD") -> dict:
    """
    Analiza SMC na M5/M15/H1/H4 jednocześnie.
    Zwraca zbiorczą konfluencję: wynik 0-100, per-TF breakdown, rekomendację.

    Cache: 120s (dwa razy dłużej niż pojedyncza analiza — oszczędność kredytów).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    timeframes = ["5m", "15m", "1h", "4h"]
    tf_weights = {"5m": 0.10, "15m": 0.25, "1h": 0.35, "4h": 0.30}
    results = {}

    try:
        # Prefetch
        try:
            provider = _get_data_provider()
            provider.prefetch_all_timeframes(symbol)
        except Exception:
            pass

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(get_smc_analysis, tf): tf for tf in timeframes}
            for future in as_completed(futures, timeout=30):
                tf = futures[future]
                try:
                    data = future.result()
                    if data:
                        results[tf] = data
                except Exception as e:
                    logger.debug(f"MTF {tf} error: {e}")
    except Exception as e:
        logger.error(f"MTF confluence error: {e}")

    if not results:
        return {
            "confluence_score": 0,
            "direction": "CZEKAJ",
            "bull_pct": 0,
            "bear_pct": 0,
            "bull_tf_count": 0,
            "bear_tf_count": 0,
            "timeframes": {},
            "session": get_active_session(),
        }

    # Confluence scoring
    bull_score = 0.0
    bear_score = 0.0
    tf_breakdown = {}

    for tf, data in results.items():
        w = tf_weights.get(tf, 0.2)
        tf_signal = {"trend": data.get("trend"), "rsi": data.get("rsi"), "weight": w}

        # Trend
        if data.get("trend") == "bull":
            bull_score += w * 30
        else:
            bear_score += w * 30

        # Liquidity Grab + MSS
        if data.get("liquidity_grab") and data.get("mss"):
            if data.get("liquidity_grab_dir") == "bullish":
                bull_score += w * 40
            else:
                bear_score += w * 40

        # FVG
        if data.get("fvg_type") == "bullish":
            bull_score += w * 15
        elif data.get("fvg_type") == "bearish":
            bear_score += w * 15

        # BOS
        if data.get("bos_bullish"):
            bull_score += w * 10
        if data.get("bos_bearish"):
            bear_score += w * 10

        # Candlestick patterns
        if data.get("engulfing") == "bullish":
            bull_score += w * 5
        elif data.get("engulfing") == "bearish":
            bear_score += w * 5

        tf_breakdown[tf] = tf_signal

    total = max(bull_score + bear_score, 1)
    bull_pct = round(bull_score / total * 100)
    bear_pct = round(bear_score / total * 100)

    if bull_pct >= 65:
        direction = "STRONG_BULL"
    elif bull_pct >= 55:
        direction = "BULL"
    elif bear_pct >= 65:
        direction = "STRONG_BEAR"
    elif bear_pct >= 55:
        direction = "BEAR"
    else:
        direction = "MIXED"

    confluence_score = max(bull_pct, bear_pct)

    return {
        "confluence_score": confluence_score,
        "direction": direction,
        "bull_pct": bull_pct,
        "bear_pct": bear_pct,
        "bull_tf_count": sum(1 for d in results.values() if d.get("trend") == "bull"),
        "bear_tf_count": sum(1 for d in results.values() if d.get("trend") == "bear"),
        "timeframes": tf_breakdown,
        "session": get_active_session(),
    }
