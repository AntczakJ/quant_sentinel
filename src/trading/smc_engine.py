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
from src.core.cache import cached_with_key
from src.core.logger import logger


# ==================== SESSION / KILLZONE DETECTION ====================

def _get_cet_tz():
    """Return Europe/Warsaw (CET/CEST) tzinfo — handles DST automatically."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('Europe/Warsaw')
    except ImportError:
        try:
            import pytz
            return pytz.timezone('Europe/Warsaw')
        except ImportError:
            # Minimal fallback: CET (UTC+1), no DST awareness
            from datetime import timedelta, tzinfo as _tzinfo
            class _CET(_tzinfo):
                def utcoffset(self, dt): return timedelta(hours=1)
                def dst(self, dt): return timedelta(0)
                def tzname(self, dt): return "CET"
            return _CET()

_CET_TZ = _get_cet_tz()


def is_market_open(dt_cet=None) -> bool:
    """
    Sprawdza czy rynek XAU/USD jest otwarty.

    Godziny rynku (CET/CEST):
      Otwarcie:   niedziela 23:00
      Zamknięcie: piątek    22:00
      Weekend (pt 22:00 → nd 23:00): ZAMKNIĘTY
    """
    if dt_cet is None:
        dt_cet = datetime.now(_CET_TZ)
    wd = dt_cet.weekday()   # Mon=0 … Sun=6
    h = dt_cet.hour

    if wd == 5:                        # Saturday — always closed
        return False
    if wd == 4 and h >= 22:            # Friday ≥22:00 — closed
        return False
    if wd == 6 and h < 23:             # Sunday <23:00 — closed
        return False
    return True


def get_active_session(utc_hour: int = None) -> dict:
    """
    Określa aktywną sesję tradingową XAU/USD na podstawie czasu CET/CEST.
    Automatycznie obsługuje zmianę czasu letniego/zimowego (DST).

    Sesje (czas CET/CEST — źródło: TradingBeasts, liteforex.pl):
      Asian  (Tokyo/Sydney):  00:00 – 08:00  (niska zmienność)
      London (Europa):        08:00 – 17:00  (wysoka zmienność od otwarcia)
      NY     (Ameryka):       14:00 – 23:00  (najwyższa zmienność)
      Overlap (London+NY):    14:00 – 17:00  (max płynność — najlepszy czas)

    Killzones (godziny UTC):
    - Asian:   00:00-06:00 (niska zmienność na złocie)
    - London:  07:00-10:00 (wysoka zmienność — otwarcie Europy)
    - NY:      12:00-15:00 (najwyższa zmienność — otwarcie USA)
    - Overlap: 12:00-16:00 (London+NY — max płynność)

    Rynek XAU/USD:
      Otwarcie:   niedziela 23:00 CET
      Zamknięcie: piątek    22:00 CET
      Weekend (pt 22:00 → nd 23:00): ZAMKNIĘTY
    """
    # ── Get current CET/CEST time ──
    if utc_hour is not None:
        # Legacy / testing: approximate conversion from UTC hour
        utc_now = datetime.now(timezone.utc).replace(hour=utc_hour, minute=0, second=0)
        cet_now = utc_now.astimezone(_CET_TZ)
    else:
        cet_now = datetime.now(_CET_TZ)

    cet_hour = cet_now.hour
    weekday = cet_now.weekday()  # Mon=0 … Sun=6

    # ── Weekend / market closed ──
    if not is_market_open(cet_now):
        return {
            'session': 'weekend',
            'is_killzone': False,
            'utc_hour': cet_now.astimezone(timezone.utc).hour,
            'cet_hour': cet_hour,
            'weekday': weekday,
            'market_open': False,
            'volatility_expected': 'none',
        }

    # ── Session detection (CET/CEST) ──
    if 0 <= cet_hour < 8:
        session = 'asian'
        is_killzone = False
    elif 8 <= cet_hour < 10:
        session = 'london'
        is_killzone = True       # London open killzone — wzrost zmienności
    elif 10 <= cet_hour < 14:
        session = 'london'
        is_killzone = False
    elif 14 <= cet_hour < 17:
        session = 'overlap'      # London+NY overlap — max płynność
        is_killzone = True
    elif 17 <= cet_hour < 23:
        session = 'new_york'
        is_killzone = False
    else:  # 23:xx
        session = 'off_hours'
        is_killzone = False

    # Volatility expectations
    if is_killzone:
        vol = 'high'
    elif session in ('london', 'new_york', 'overlap'):
        vol = 'medium'
    else:
        vol = 'low'

    return {
        'session': session,
        'is_killzone': is_killzone,
        'utc_hour': cet_now.astimezone(timezone.utc).hour,
        'cet_hour': cet_hour,
        'weekday': weekday,
        'market_open': True,
        'volatility_expected': vol,
    }


def _get_data_provider():
    """Lazy import aby uniknąć cyklicznych importów."""
    from src.data.data_sources import get_provider
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


def get_macro_quotes() -> dict:
    """
    Fetch macro indicators for regime detection via Twelve Data ETF proxies.

    Symbols (1 credit each, cached by data provider):
      - UUP  (Invesco DB USD Index Bull ETF) — dollar strength proxy
      - TLT  (iShares 20+ Year Treasury Bond ETF) — INVERSE yield proxy
             TLT goes DOWN when yields go UP, so high TLT = low yields = gold bullish
      - VIXY (ProShares VIX Short-Term Futures ETF) — volatility/fear proxy

    Returns dict with raw prices. Caller interprets direction.
    Falls back gracefully if any symbol unavailable.
    """
    result = {"uup": None, "tlt": None, "vixy": None}

    # Map: Twelve Data symbol → result key
    symbols = {
        "UUP": "uup",    # Dollar strength ETF (up = strong dollar)
        "TLT": "tlt",    # Treasury bond ETF (up = low yields = gold bullish)
        "VIXY": "vixy",  # VIX ETF proxy (up = high fear = gold bullish)
    }

    try:
        provider = _get_data_provider()

        for td_symbol, key in symbols.items():
            try:
                data = provider.get_current_price(td_symbol)
                if data and 'price' in data:
                    result[key] = float(data['price'])
            except (AttributeError, TypeError, ValueError):
                pass

    except (ImportError, AttributeError) as e:
        logger.debug(f"Macro quotes fetch skipped: {e}")

    return result


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
    Multi-indicator macro regime detection.

    Uses up to 5 independent signals (require 2+ to agree for regime flip):
      1. USD/JPY Z-score (dollar strength proxy)
      2. ATR regime (volatility — high vol favors gold)
      3. DXY (Dollar Index) — broad dollar strength
      4. US10Y (Treasury Yield) — inverse gold correlation
      5. VIX (Fear Index) — risk-off favors gold

    Regimes:
      "zielony"   (green)  = bullish for gold (weak USD, high vol, low yields)
      "czerwony"  (red)    = bearish for gold (strong USD, low vol, high yields)
      "neutralny" (neutral) = mixed signals
    """
    signals = {}

    # --- Signal 1: USD/JPY Z-score (inverse correlation with gold) ---
    usdjpy_zscore = 0.0
    if len(usdjpy_prices) >= 20:
        mean = np.mean(usdjpy_prices[-20:])
        std = np.std(usdjpy_prices[-20:])
        usdjpy_zscore = (current_usdjpy - mean) / std if std > 0 else 0
        if usdjpy_zscore < -1.0:
            signals["usdjpy"] = -1  # weak dollar → gold bullish
        elif usdjpy_zscore > 1.0:
            signals["usdjpy"] = 1   # strong dollar → gold bearish
        else:
            signals["usdjpy"] = 0

    # --- Signal 2: Volatility regime (ATR vs mean) ---
    atr_ratio = atr / atr_mean if atr_mean > 0 else 1.0
    if atr_ratio > 1.2:
        signals["volatility"] = -1   # high vol → gold rises (safe haven)
    elif atr_ratio < 0.8:
        signals["volatility"] = 1    # low vol → gold consolidates
    else:
        signals["volatility"] = 0

    # --- Signals 3-5: ETF proxies from Twelve Data ---
    macro_quotes = get_macro_quotes()

    # UUP (Dollar Bull ETF): UUP up = strong dollar = bearish gold
    uup = macro_quotes.get("uup")
    if uup is not None:
        # UUP typical range 25-30. Above 28 = strong $, below 26 = weak $
        if uup > 28.0:
            signals["dollar"] = 1     # strong dollar → bearish gold
        elif uup < 26.0:
            signals["dollar"] = -1    # weak dollar → bullish gold
        else:
            signals["dollar"] = 0

    # TLT (Treasury Bond ETF — INVERSE yield proxy):
    #   TLT UP = yields DOWN = low opportunity cost = gold BULLISH
    #   TLT DOWN = yields UP = high opportunity cost = gold BEARISH
    tlt = macro_quotes.get("tlt")
    if tlt is not None:
        # TLT typical range 80-110. Above 95 = low yields = gold bullish
        if tlt > 95.0:
            signals["yields"] = -1   # low yields → bullish gold
        elif tlt < 85.0:
            signals["yields"] = 1    # high yields → bearish gold
        else:
            signals["yields"] = 0

    # VIXY (VIX ETF proxy): VIXY up = high fear = risk-off = gold BULLISH
    vixy = macro_quotes.get("vixy")
    if vixy is not None:
        # VIXY typical range 15-60. Above 35 = high fear, below 20 = complacency
        if vixy > 35.0:
            signals["fear"] = -1    # high fear → risk-off → gold bullish
        elif vixy < 20.0:
            signals["fear"] = 1     # low fear → risk-on → gold bearish
        else:
            signals["fear"] = 0

    # --- Signal 6: COT (Commitment of Traders) — weekly, contrarian ---
    try:
        from src.data.cot_data import get_gold_cot_signal
        cot = get_gold_cot_signal()
        if cot and cot.get("signal") is not None:
            signals["cot"] = cot["signal"]
    except (ImportError, AttributeError):
        pass

    # --- Signal 7: FRED real yields — gold's #1 predictor (correlation -0.82) ---
    try:
        from src.data.macro_data import get_fred_data
        fred = get_fred_data()
        fred_signal = fred.get("composite_signal", 0)
        if fred_signal != 0:
            signals["real_yields"] = fred_signal
    except (ImportError, AttributeError):
        pass

    # --- Signal 8: Retail sentiment — contrarian (Myfxbook) ---
    try:
        from src.data.macro_data import get_retail_sentiment
        retail = get_retail_sentiment()
        retail_signal = retail.get("signal", 0)
        if retail_signal != 0:
            signals["retail_sentiment"] = retail_signal
    except (ImportError, AttributeError):
        pass

    # --- Signal 9: Seasonality — month + day-of-week historical bias ---
    try:
        from src.data.macro_data import get_seasonality_signal
        season = get_seasonality_signal()
        season_signal = season.get("combined_signal", 0)
        if season_signal != 0:
            signals["seasonality"] = season_signal
    except (ImportError, AttributeError):
        pass

    # --- Signal 10: Finnhub news sentiment — real-time headlines ---
    try:
        from src.data.news_feed import get_gold_news_signal
        news = get_gold_news_signal()
        news_signal = news.get("signal", 0)
        if news_signal != 0:
            signals["news"] = news_signal
    except (ImportError, AttributeError):
        pass

    # --- Signal 11: Geopolitical Risk Index (GPR) ---
    try:
        from src.data.gpr_index import get_gpr_signal
        gpr = get_gpr_signal()
        gpr_signal = gpr.get("signal", 0)
        if gpr_signal != 0:
            signals["geopolitical"] = gpr_signal
    except (ImportError, AttributeError):
        pass

    # --- Combine: require 2+ signals to agree for regime flip ---
    signal_values = list(signals.values())
    bullish_count = sum(1 for s in signal_values if s == -1)
    bearish_count = sum(1 for s in signal_values if s == 1)
    total_signals = len(signal_values)

    if bullish_count >= 2 and bullish_count > bearish_count:
        regime = "zielony"
    elif bearish_count >= 2 and bearish_count > bullish_count:
        regime = "czerwony"
    else:
        regime = "neutralny"

    return {
        "regime": regime,
        "usdjpy": current_usdjpy,
        "usdjpy_zscore": round(usdjpy_zscore, 2),
        "atr": atr,
        "atr_mean": round(atr_mean, 2),
        "atr_ratio": round(atr_ratio, 2),
        "uup": uup,
        "tlt": tlt,
        "vixy": vixy,
        "signals": signals,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "total_signals": total_signals,
    }


def detect_swing_points(df: pd.DataFrame, window: int = 5) -> dict:
    """
    Wykrywa Swing Highs i Swing Lows na podstawie lokalnych ekstremów.
    window -- liczba świec po obu stronach do porównania.
    Zwraca ostatni znaczący Swing High i Swing Low.

    Accelerated: uses Numba JIT when available (10-50x faster on large datasets).
    """
    from src.analysis.compute import _swing_points_numba

    highs = np.ascontiguousarray(df['high'].values, dtype=np.float64)
    lows = np.ascontiguousarray(df['low'].values, dtype=np.float64)
    n = len(df)

    if n <= 2 * window:
        return {
            "swing_high": round(float(highs.max()), 2),
            "swing_low": round(float(lows.min()), 2),
            "swing_high_idx": n - 1,
            "swing_low_idx": n - 1
        }

    last_sh, last_sh_idx, last_sl, last_sl_idx = _swing_points_numba(highs, lows, window)

    # Fallback if no swings found (numba returns initial values)
    if last_sh_idx == 0 and last_sl_idx == 0:
        last_sh = float(highs.max())
        last_sh_idx = n - 1
        last_sl = float(lows.min())
        last_sl_idx = n - 1

    return {
        "swing_high": round(float(last_sh), 2),
        "swing_low": round(float(last_sl), 2),
        "swing_high_idx": int(last_sh_idx),
        "swing_low_idx": int(last_sl_idx)
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
    Enhanced Order Block detection with volume weighting and time decay.

    For bull: last bearish candle before a strong bullish candle (body > 1.5 * avg).
    For bear: last bullish candle before a strong bearish candle.
    Checks mitigation (price swept through OB).

    Scoring: volume_weight * freshness_decay → picks highest-scoring OB.
    Returns OB price (low for bull, high for bear).
    """
    body = abs(df['close'] - df['open'])
    avg_body = body.tail(20).mean()
    ob_price = df['close'].iloc[-1]  # fallback
    impulse_mult = 1.5

    has_volume = 'volume' in df.columns
    avg_volume = df['volume'].tail(20).mean() if has_volume else 1.0
    n = len(df)
    best_score = -1.0

    for i in range(n - 2, max(0, n - 30), -1):
        candidate = None
        if trend == "bull":
            if df['close'].iloc[i] < df['open'].iloc[i] and body.iloc[i + 1] > avg_body * impulse_mult:
                if df['close'].iloc[i + 1] > df['open'].iloc[i + 1]:
                    candidate = df['low'].iloc[i]
                    mitigated = any(df['low'].iloc[j] < candidate for j in range(i + 2, n))
                    if mitigated:
                        candidate = None
        else:
            if df['close'].iloc[i] > df['open'].iloc[i] and body.iloc[i + 1] > avg_body * impulse_mult:
                if df['close'].iloc[i + 1] < df['open'].iloc[i + 1]:
                    candidate = df['high'].iloc[i]
                    mitigated = any(df['high'].iloc[j] > candidate for j in range(i + 2, n))
                    if mitigated:
                        candidate = None

        if candidate is not None:
            # Volume weight: higher volume at OB = stronger level
            vol_weight = (df['volume'].iloc[i] / avg_volume) if has_volume and avg_volume > 0 else 1.0
            vol_weight = min(vol_weight, 3.0)  # cap at 3x

            # Time decay: fresher OB = more relevant (exponential decay)
            bars_ago = n - 1 - i
            decay_rate = 0.05  # ~60% weight at 10 bars ago, ~36% at 20 bars
            freshness = np.exp(-decay_rate * bars_ago)

            score = vol_weight * freshness

            if score > best_score:
                best_score = score
                ob_price = candidate

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

    # Filtr szumu: FVG musi mieć rozmiar >= 0.4 * ATR (zaostrzony z 0.3)
    # i absolutne minimum 0.5$ (żeby nie łapać mikro-luk)
    min_gap = max(atr * 0.4, 0.5) if atr and atr > 0 else 0.5

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
    Wyszukuje Order Blocki z volume weighting i time decay.
    Sortuje po score (volume * freshness) — najsilniejsze pierwsze.
    Zwraca listę: [{'price': float, 'type': str, 'score': float, 'bars_ago': int}, ...]
    """
    body = abs(df['close'] - df['open'])
    avg_body = body.tail(20).mean()
    has_volume = 'volume' in df.columns
    avg_volume = df['volume'].tail(20).mean() if has_volume else 1.0
    n = len(df)
    candidates = []

    for i in range(n - 2, max(0, n - 50), -1):
        ob_price = None
        ob_type = None
        if trend == "bull":
            if df['close'].iloc[i] < df['open'].iloc[i] and body.iloc[i + 1] > avg_body:
                if df['close'].iloc[i + 1] > df['open'].iloc[i + 1]:
                    ob_price = df['low'].iloc[i]
                    ob_type = 'bullish'
        else:
            if df['close'].iloc[i] > df['open'].iloc[i] and body.iloc[i + 1] > avg_body:
                if df['close'].iloc[i + 1] < df['open'].iloc[i + 1]:
                    ob_price = df['high'].iloc[i]
                    ob_type = 'bearish'

        if ob_price is not None:
            bars_ago = n - 1 - i
            vol_weight = min((df['volume'].iloc[i] / avg_volume) if has_volume and avg_volume > 0 else 1.0, 3.0)
            freshness = np.exp(-0.05 * bars_ago)
            score = vol_weight * freshness
            candidates.append({
                'price': round(ob_price, 2),
                'type': ob_type,
                'score': round(score, 3),
                'bars_ago': bars_ago,
            })

    # Sort by score (strongest first) and return top N
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:max_blocks]


def detect_bos(df: pd.DataFrame, swing_points: dict) -> tuple:
    """
    Wykrywa Break of Structure (BOS) z potwierdzeniem.
    Wymaga 2 kolejnych zamknięć powyżej/poniżej swing point (confirmation candle).
    Zwraca (bos_bullish, bos_bearish) – bool.
    """
    if len(df) < 2:
        return False, False
    close_now = df['close'].iloc[-1]
    close_prev = df['close'].iloc[-2]
    # BOS bullish: dwa kolejne zamknięcia powyżej swing high
    bullish = close_now > swing_points['swing_high'] and close_prev > swing_points['swing_high']
    # BOS bearish: dwa kolejne zamknięcia poniżej swing low
    bearish = close_now < swing_points['swing_low'] and close_prev < swing_points['swing_low']
    return bullish, bearish


def detect_choch(df: pd.DataFrame, window: int = 10) -> tuple:
    """
    Wykrywa Change of Character (CHoCH) na podstawie ostatnich swingów.
    Zwraca (choch_bullish, choch_bearish) -- bool.

    Accelerated: uses Numba JIT for swing detection.
    """
    from src.analysis.compute import _find_all_swings_numba

    highs = np.ascontiguousarray(df['high'].values, dtype=np.float64)
    lows = np.ascontiguousarray(df['low'].values, dtype=np.float64)
    n = len(df)

    if n <= 2 * window:
        return False, False

    swing_highs, _ = _find_all_swings_numba(highs, window)
    _, swing_lows = _find_all_swings_numba(lows, window)

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

def find_swings(values, lookback: int = 5, min_swings: int = 2):
    """
    Zwraca indeksy lokalnych minimów i maksimów w liście wartości.
    lookback -- liczba świec po obu stronach do porównania.
    Zwraca (swing_highs, swing_lows) -- listy indeksów.

    Accelerated: uses Numba JIT when available.
    """
    from src.analysis.compute import _find_all_swings_numba

    arr = np.ascontiguousarray(values, dtype=np.float64)
    if len(arr) <= 2 * lookback:
        return [], []
    sh, sl = _find_all_swings_numba(arr, lookback)
    return list(sh), list(sl)


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
        from src.analysis.candlestick_patterns import engulfing, pin_bar, inside_bar
        from src.analysis.indicators import ichimoku, volume_profile

        # 1. POBIERANIE DANYCH ZŁOTA (przez DataProvider – rate limited, cached)
        provider = _get_data_provider()
        df = provider.get_candles('XAU/USD', tf, 100)
        if df is None or df.empty:
            logger.warning(f"Brak danych XAU/USD z DataProvider dla {tf}")
            return None

        # 1b. WALIDACJA DANYCH OHLC — odrzuć uszkodzone świece
        ohlc_cols = ['open', 'high', 'low', 'close']
        if not all(c in df.columns for c in ohlc_cols):
            logger.warning(f"Brak kolumn OHLC w danych {tf}")
            return None
        # Usuń świece z ujemnymi cenami lub high < low
        bad_mask = (
            (df['high'] < df['low']) |
            (df[ohlc_cols] <= 0).any(axis=1) |
            df[ohlc_cols].isna().any(axis=1)
        )
        if bad_mask.any():
            n_bad = bad_mask.sum()
            logger.warning(f"⚠️ Usunięto {n_bad} uszkodzonych świec z danych {tf}")
            df = df[~bad_mask].reset_index(drop=True)
            if len(df) < 30:
                logger.warning(f"Za mało danych po walidacji ({len(df)} < 30) dla {tf}")
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
            "atr_ratio": macro.get("atr_ratio", 1.0),
            "uup": macro.get("uup"),
            "tlt": macro.get("tlt"),
            "vixy": macro.get("vixy"),
            "macro_signals": macro.get("signals", {}),
            "macro_bullish_count": macro.get("bullish_count", 0),
            "macro_bearish_count": macro.get("bearish_count", 0),
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
            'session_info': session_info,  # full session dict for score_setup_quality
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
        except (ImportError, AttributeError):
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

        # Trend (najważniejszy sygnał)
        if data.get("trend") == "bull":
            bull_score += w * 30
        else:
            bear_score += w * 30

        # Liquidity Grab + MSS (premium setup)
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

        # BOS (z potwierdzeniem — wymaga 2 świec)
        if data.get("bos_bullish"):
            bull_score += w * 12
        if data.get("bos_bearish"):
            bear_score += w * 12

        # CHoCH — zmiana charakteru (silny sygnał odwrócenia)
        if data.get("choch_bullish"):
            bull_score += w * 18
        if data.get("choch_bearish"):
            bear_score += w * 18

        # RSI Divergence — silne sygnały kontrtrendowe
        if data.get("rsi_div_bull"):
            bull_score += w * 20
        if data.get("rsi_div_bear"):
            bear_score += w * 20

        # Candlestick patterns
        if data.get("engulfing") == "bullish":
            bull_score += w * 8
        elif data.get("engulfing") == "bearish":
            bear_score += w * 8
        if data.get("pin_bar") == "bullish":
            bull_score += w * 6
        elif data.get("pin_bar") == "bearish":
            bear_score += w * 6

        # Ichimoku cloud
        if data.get("ichimoku_above_cloud"):
            bull_score += w * 10
        if data.get("ichimoku_below_cloud"):
            bear_score += w * 10

        # DBR/RBD
        if data.get("dbr_rbd_type") == "DBR":
            bull_score += w * 25
        elif data.get("dbr_rbd_type") == "RBD":
            bear_score += w * 25

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


# ==================== SETUP QUALITY SCORING ====================

def score_setup_quality(analysis: dict, direction: str) -> dict:
    """
    Ocenia jakość setupu tradingowego na podstawie wagowanych konfluencji.

    Zwraca:
        {
            'grade': 'A+' | 'A' | 'B' | 'C',
            'score': float (0-100),
            'factors_detail': dict,  # per-factor breakdown
            'risk_mult': float,      # mnożnik ryzyka (0.5-1.5)
            'target_rr': float,      # sugerowany R:R
        }

    Progi (zbalansowane — nie za rygorystyczne):
        A+ : score >= 75  → pełna pozycja, agresywny TP
        A  : score >= 55  → standardowa pozycja
        B  : score >= 35  → zmniejszona pozycja
        C  : score < 35   → pominięty (zbyt ryzykowny)
    """
    score = 0.0
    factors_detail = {}

    # --- CZYNNIKI STRUKTURALNE (najważniejsze) ---

    # Liquidity Grab + MSS — premium setup (max 25 pkt)
    has_grab_mss = analysis.get('liquidity_grab') and analysis.get('mss')
    if has_grab_mss:
        grab_dir = analysis.get('liquidity_grab_dir', '')
        if (direction == "LONG" and grab_dir == "bullish") or \
           (direction == "SHORT" and grab_dir == "bearish"):
            score += 25
            factors_detail['grab_mss'] = 25
        else:
            score += 8  # grab+mss w przeciwnym kierunku — mniejsza wartość
            factors_detail['grab_mss_opposite'] = 8

    # DBR/RBD — silny pattern (max 20 pkt)
    dbr_type = analysis.get('dbr_rbd_type')
    if (direction == "LONG" and dbr_type == "DBR") or \
       (direction == "SHORT" and dbr_type == "RBD"):
        score += 20
        factors_detail['dbr_rbd'] = 20

    # BOS — Break of Structure (max 12 pkt)
    if (direction == "LONG" and analysis.get('bos_bullish')) or \
       (direction == "SHORT" and analysis.get('bos_bearish')):
        score += 12
        factors_detail['bos'] = 12

    # CHoCH — Change of Character (max 15 pkt)
    if (direction == "LONG" and analysis.get('choch_bullish')) or \
       (direction == "SHORT" and analysis.get('choch_bearish')):
        score += 15
        factors_detail['choch'] = 15

    # --- CZYNNIKI POTWIERDZAJĄCE ---

    # FVG w kierunku (max 10 pkt)
    fvg_type = analysis.get('fvg_type')
    if (direction == "LONG" and fvg_type == "bullish") or \
       (direction == "SHORT" and fvg_type == "bearish"):
        score += 10
        factors_detail['fvg'] = 10

    # Order Block (max 8 pkt)
    ob_price = analysis.get('ob_price')
    price = analysis.get('price', 0)
    if ob_price and price:
        if (direction == "LONG" and ob_price < price) or \
           (direction == "SHORT" and ob_price > price):
            score += 8
            factors_detail['order_block'] = 8

    # RSI Divergence (max 10 pkt)
    if (direction == "LONG" and analysis.get('rsi_div_bull')) or \
       (direction == "SHORT" and analysis.get('rsi_div_bear')):
        score += 10
        factors_detail['rsi_divergence'] = 10

    # RSI w optymalnej strefie (max 5 pkt)
    rsi = analysis.get('rsi', 50)
    if direction == "LONG" and 35 <= rsi <= 55:
        score += 5
        factors_detail['rsi_optimal'] = 5
    elif direction == "SHORT" and 45 <= rsi <= 65:
        score += 5
        factors_detail['rsi_optimal'] = 5

    # --- CZYNNIKI DODATKOWE ---

    # Engulfing pattern (max 6 pkt)
    eng = analysis.get('engulfing', False)
    if (direction == "LONG" and eng == 'bullish') or \
       (direction == "SHORT" and eng == 'bearish'):
        score += 6
        factors_detail['engulfing'] = 6

    # Pin bar (max 5 pkt)
    pb = analysis.get('pin_bar', False)
    if (direction == "LONG" and pb == 'bullish') or \
       (direction == "SHORT" and pb == 'bearish'):
        score += 5
        factors_detail['pin_bar'] = 5

    # Ichimoku cloud (max 6 pkt)
    if (direction == "LONG" and analysis.get('ichimoku_above_cloud')) or \
       (direction == "SHORT" and analysis.get('ichimoku_below_cloud')):
        score += 6
        factors_detail['ichimoku'] = 6

    # Makro regime alignment (max 12 pkt — scales with signal count)
    macro = analysis.get('macro_regime', 'neutralny')
    macro_bullish = analysis.get('macro_bullish_count', 0)
    macro_bearish = analysis.get('macro_bearish_count', 0)
    if (direction == "LONG" and macro == "zielony") or \
       (direction == "SHORT" and macro == "czerwony"):
        # Scale bonus by how many macro signals agree (2=base, 3-5=stronger)
        aligned_count = macro_bullish if direction == "LONG" else macro_bearish
        macro_pts = min(4 + aligned_count * 2, 12)  # 4+2n, max 12
        score += macro_pts
        factors_detail['macro'] = macro_pts
        factors_detail['macro_signals_aligned'] = aligned_count

    # Session-aware scoring
    session_name = analysis.get('session', 'unknown')
    if analysis.get('is_killzone'):
        # Killzone (London open / NY overlap) — highest probability setups
        score += 8
        factors_detail['killzone'] = 8
    elif session_name == 'overlap':
        # London+NY overlap — good liquidity even outside killzone
        score += 4
        factors_detail['session_overlap'] = 4
    elif session_name == 'asian':
        # Asian session — low vol, higher failure rate for breakouts
        score -= 3
        factors_detail['session_asian_penalty'] = -3

    # --- DYNAMICZNA KOREKTA Z BAZY (historyczna skuteczność grade'a) ---
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        # Korekta per-pattern z self-learning
        pattern = f"{direction}_{analysis.get('structure', 'unknown')}_{fvg_type}"
        stats = db.get_pattern_stats(pattern)
        if stats['count'] >= 10:
            # Jeśli pattern historycznie ma >60% WR → bonus, <40% → kara
            if stats['win_rate'] > 0.60:
                bonus = min(10, (stats['win_rate'] - 0.5) * 40)
                score += bonus
                factors_detail['history_bonus'] = round(bonus, 1)
            elif stats['win_rate'] < 0.40:
                penalty = min(10, (0.5 - stats['win_rate']) * 40)
                score -= penalty
                factors_detail['history_penalty'] = round(-penalty, 1)
    except (TypeError, KeyError, AttributeError, ImportError):
        pass

    # --- PENALTIES (reduce score for risky conditions) ---

    # Penalty: entry far from nearest OB (weak support/resistance)
    if ob_price and price and abs(price - ob_price) > 0:
        atr_val = analysis.get('atr', 5.0)
        ob_distance_atr = abs(price - ob_price) / atr_val if atr_val > 0 else 0
        if ob_distance_atr > 2.0:
            penalty = min(8, (ob_distance_atr - 2.0) * 4)
            score -= penalty
            factors_detail['ob_distance_penalty'] = round(-penalty, 1)

    # Penalty: RSI extreme against direction (likely reversal zone)
    if direction == "LONG" and rsi > 75:
        score -= 8
        factors_detail['rsi_extreme_penalty'] = -8
    elif direction == "SHORT" and rsi < 25:
        score -= 8
        factors_detail['rsi_extreme_penalty'] = -8

    # Penalty: opposing macro regime (scales with signal count)
    if (direction == "LONG" and macro == "czerwony") or \
       (direction == "SHORT" and macro == "zielony"):
        opposing_count = macro_bearish if direction == "LONG" else macro_bullish
        macro_penalty = min(4 + opposing_count * 2, 14)  # 4+2n, max 14
        score -= macro_penalty
        factors_detail['macro_opposing_penalty'] = -macro_penalty

    # Penalty: off-hours / low liquidity session
    session_info = analysis.get('session_info', {})
    if session_info.get('volatility_expected') == 'low' or \
       session_info.get('session') in ('off_hours',):
        score -= 5
        factors_detail['low_liquidity_penalty'] = -5

    # Clamp score to 0-100
    score = max(0, min(100, score))

    # --- GRADE ASSIGNMENT (tightened thresholds) ---
    if score >= 75:
        grade = "A+"
        risk_mult = 1.5
        target_rr = 3.0
    elif score >= 55:
        grade = "A"
        risk_mult = 1.0
        target_rr = 2.5
    elif score >= 40:
        grade = "B"
        risk_mult = 0.5
        target_rr = 2.0
    else:
        grade = "C"
        risk_mult = 0.0  # nie handluj
        target_rr = 0.0

    return {
        'grade': grade,
        'score': round(score, 1),
        'factors_detail': factors_detail,
        'risk_mult': risk_mult,
        'target_rr': target_rr,
    }
