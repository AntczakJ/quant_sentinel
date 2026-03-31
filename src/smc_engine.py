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

import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from src.config import TD_API_KEY


def get_usdjpy_history(tf: str, length: int = 30) -> tuple:
    """
    Pobiera historyczne dane USD/JPY z Twelve Data i zwraca (lista cen, ostatnia cena).
    """
    try:
        td_tf = tf if "min" in tf else tf.replace("m", "min")
        url = f"https://api.twelvedata.com/time_series?symbol=USD/JPY&interval={td_tf}&apikey={TD_API_KEY}&outputsize={length}"
        data = requests.get(url, timeout=10).json()
        if 'values' not in data:
            return [], 0
        df = pd.DataFrame(data['values'])
        df['close'] = pd.to_numeric(df['close'])
        df = df.iloc[::-1].reset_index(drop=True)
        prices = df['close'].tolist()
        current = prices[-1] if prices else 0
        return prices, current
    except Exception as e:
        print(f"Błąd pobierania USD/JPY: {e}")
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
            print(f"⚠️ Błąd pobierania kursu {symbol}: {data.get('message')}")
            return None
        return float(data['price'])
    except Exception as e:
        print(f"❌ Błąd w get_exchange_rate: {e}")
        return None


def get_smc_analysis(tf: str) -> dict | None:
    """
    Główna funkcja – rozszerzona o nowe wskaźniki SMC i makro.
    """
    try:
        td_tf = tf if "min" in tf else tf.replace("m", "min")

        # 1. POBIERANIE DANYCH ZŁOTA
        url_gold = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval={td_tf}&apikey={TD_API_KEY}&outputsize=100"
        data_gold = requests.get(url_gold, timeout=10).json()
        if 'values' not in data_gold:
            print(f"Błąd Twelve Data: {data_gold.get('message')}")
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
            "structure": structure
        }

    except Exception as e:
        print(f"❌ Błąd silnika SMC Master: {e}")
        return None