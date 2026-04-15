"""
src/macro_data.py — Macro Economic Data for Gold Trading

Fetches and caches macro indicators with highest gold correlation:

  1. FRED Data (free API key required):
     - DFII10: 10-Year Real Yield (TIPS) — gold correlation -0.82
     - T10YIE: 10-Year Breakeven Inflation Rate
     - DGS10: 10-Year Nominal Treasury Yield
     - GVZCLS: Gold ETF Volatility Index (GVZ)
     - DTWEXBGS: Trade-Weighted Dollar Index

  2. Myfxbook Retail Sentiment (free, 100 req/day):
     - XAUUSD long/short percentage
     - Average long/short price
     - Contrarian signal

  3. Seasonality Features:
     - Month-of-year (January 80% bullish, September 90% bearish)
     - Day-of-week (Monday worst, Friday best)

All data cached to minimize API calls. FRED data updates daily, sentiment hourly.
"""

import os
import time
import datetime
import json
from typing import Optional, Dict
from dotenv import load_dotenv
from src.core.logger import logger

load_dotenv()

_CACHE_DIR = "data"
# JSON cache files (migrated from pickle 2026-04-12: pickle.load on disk-
# backed cache is an arbitrary-code-execution risk if the file gets tampered
# with. Macro cache payloads are plain dicts of floats/strings so JSON is
# a drop-in replacement with no loss of fidelity.)
_FRED_CACHE_FILE = os.path.join(_CACHE_DIR, "fred_cache.json")
_FRED_CACHE_TTL = 14400   # 4 hours (FRED data is daily)


# ═══════════════════════════════════════════════════════════════════════════
#  CACHE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _load_cache(path: str, ttl: int) -> Optional[Dict]:
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if time.time() - cached.get('ts', 0) < ttl:
                return cached.get('data')
    except (FileNotFoundError, json.JSONDecodeError, EOFError, KeyError, UnicodeDecodeError):
        pass
    return None


def _save_cache(path: str, data: Dict):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'data': data, 'ts': time.time()}, f, default=str)
    except (OSError, TypeError, ValueError):
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  1. FRED DATA (Real Yields, Inflation, Dollar, Gold VIX)
# ═══════════════════════════════════════════════════════════════════════════

# Series we fetch — ordered by gold-prediction importance
_FRED_SERIES = {
    "real_yield_10y":     "DFII10",    # 10Y Real Yield (TIPS) — gold #1 predictor
    "breakeven_10y":      "T10YIE",    # 10Y Breakeven Inflation
    "nominal_yield_10y":  "DGS10",     # 10Y Nominal Treasury
    "gold_vix":           "GVZCLS",    # Gold ETF Volatility Index
    "dollar_index":       "DTWEXBGS",  # Trade-Weighted Dollar Index
    "fed_funds":          "FEDFUNDS",  # Fed Funds Effective Rate
}


def get_fred_data() -> Dict:
    """
    Fetch latest values from FRED for gold-relevant macro series.

    Returns dict with latest values and signals:
      {
        "real_yield_10y": {"value": 1.85, "signal": 1},  # positive = bearish gold
        "breakeven_10y": {"value": 2.35, "signal": -1},  # high inflation exp = bullish gold
        ...
        "composite_signal": -1|0|1,  # aggregate macro signal
      }

    Requires FRED_API_KEY in .env (free: https://fred.stlouisfed.org/docs/api/api_key.html)
    """
    # Try cache first
    cached = _load_cache(_FRED_CACHE_FILE, _FRED_CACHE_TTL)
    if cached is not None:
        return cached

    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        logger.debug("[MACRO] FRED_API_KEY not set — FRED data unavailable")
        return {"error": "FRED_API_KEY not configured", "composite_signal": 0}

    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)

        result = {}
        signals = []

        for name, series_id in _FRED_SERIES.items():
            try:
                data = fred.get_series(series_id, observation_start='2024-01-01')
                if data is not None and len(data) > 0:
                    latest = float(data.dropna().iloc[-1])
                    result[name] = {"value": round(latest, 4), "series_id": series_id}

                    # Generate signal based on the value
                    signal = _interpret_fred_signal(name, latest, data)
                    result[name]["signal"] = signal
                    if signal != 0:
                        signals.append(signal)
            except Exception as e:
                logger.debug(f"[MACRO] FRED {series_id} failed: {e}")
                result[name] = {"value": None, "error": str(e)}

        # Composite signal: majority vote of individual signals
        if signals:
            bullish = sum(1 for s in signals if s == -1)
            bearish = sum(1 for s in signals if s == 1)
            if bullish > bearish:
                result["composite_signal"] = -1
            elif bearish > bullish:
                result["composite_signal"] = 1
            else:
                result["composite_signal"] = 0
        else:
            result["composite_signal"] = 0

        result["timestamp"] = datetime.datetime.now().isoformat()
        result["source"] = "FRED"

        _save_cache(_FRED_CACHE_FILE, result)
        logger.info(
            f"[MACRO] FRED data loaded: "
            f"real_yield={result.get('real_yield_10y', {}).get('value', '?')}, "
            f"breakeven={result.get('breakeven_10y', {}).get('value', '?')}, "
            f"composite={result.get('composite_signal', 0)}"
        )
        return result

    except ImportError:
        logger.info("[MACRO] fredapi not installed — pip install fredapi")
        return {"error": "fredapi not installed", "composite_signal": 0}
    except Exception as e:
        logger.warning(f"[MACRO] FRED fetch failed: {e}")
        return {"error": str(e), "composite_signal": 0}


def _interpret_fred_signal(name: str, value: float, series) -> int:
    """
    Interpret a FRED series value as a gold signal.

    Returns: -1 (bullish gold), 0 (neutral), 1 (bearish gold)

    Logic based on research:
    - Real yields UP → gold DOWN (opportunity cost of holding non-yielding asset)
    - Inflation expectations UP → gold UP (inflation hedge)
    - Dollar UP → gold DOWN (inverse relationship)
    - Gold VIX UP → gold volatile (uncertainty = bullish for safe haven)
    """
    import numpy as np

    # Compute z-score vs recent history for dynamic thresholds
    recent = series.dropna().tail(252)  # ~1 year of daily data
    if len(recent) < 20:
        return 0

    mean = float(np.mean(recent))
    std = float(np.std(recent))
    if std == 0:
        return 0

    z = (value - mean) / std

    if name == "real_yield_10y":
        # High real yields = bearish gold (z > 1 = high), low = bullish (z < -1)
        if z > 1.0:
            return 1   # bearish gold
        elif z < -1.0:
            return -1  # bullish gold

    elif name == "breakeven_10y":
        # High inflation expectations = bullish gold
        if z > 1.0:
            return -1  # bullish gold (inflation hedge demand)
        elif z < -1.0:
            return 1   # bearish gold (low inflation = less hedge demand)

    elif name == "nominal_yield_10y":
        # High nominal yields = mildly bearish (but less than real yields)
        if z > 1.5:
            return 1
        elif z < -1.5:
            return -1

    elif name == "dollar_index":
        # Strong dollar = bearish gold
        if z > 1.0:
            return 1
        elif z < -1.0:
            return -1

    elif name == "gold_vix":
        # High gold volatility = uncertainty = bullish for safe haven
        if z > 1.5:
            return -1  # high fear → gold bullish
        elif z < -1.0:
            return 1   # low vol → complacency → gold bearish

    elif name == "fed_funds":
        # High rates = bearish gold (opportunity cost)
        if z > 1.0:
            return 1
        elif z < -1.0:
            return -1

    return 0


# ═══════════════════════════════════════════════════════════════════════════
#  (REMOVED 2026-04-15) Myfxbook retail sentiment — required broker linking
#  which user did not want. Function get_retail_sentiment() removed. Callers
#  in smc_engine.py and get_full_macro_signal() updated to not reference it.
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  3. SEASONALITY FEATURES
# ═══════════════════════════════════════════════════════════════════════════

# Historical gold seasonal bias (10-year avg, source: Seasonax + ForexGDP)
_MONTH_BIAS = {
    1: -1,   # January: 80% bullish (+5% avg return) → strong bullish
    2: -1,   # February: bullish momentum spillover
    3: 0,    # March: mixed
    4: 0,    # April: mixed
    5: 0,    # May: mixed
    6: 0,    # June: mixed
    7: 0,    # July: mixed
    8: 0,    # August: mixed but often start of seasonal rally
    9: 1,    # September: 90% bearish — worst month
    10: 0,   # October: mixed (but Oct 9 specifically 86% bullish)
    11: -1,  # November: bullish (Indian Diwali demand)
    12: -1,  # December: bullish (year-end safe haven rebalancing)
}

# Day-of-week bias
_DOW_BIAS = {
    0: 1,    # Monday: worst day (weekend hedge liquidation)
    1: 0,    # Tuesday: neutral
    2: 0,    # Wednesday: neutral (often FOMC days — event-driven)
    3: 0,    # Thursday: neutral
    4: -1,   # Friday: best day (pre-weekend safe haven buying)
    5: 0,    # Saturday: market closed
    6: 0,    # Sunday: market closed
}


def get_seasonality_signal() -> Dict:
    """
    Returns current seasonality bias for gold based on month and day-of-week.

    signal: -1 (bullish), 0 (neutral), 1 (bearish)
    """
    now = datetime.datetime.now()
    month = now.month
    dow = now.weekday()

    month_signal = _MONTH_BIAS.get(month, 0)
    dow_signal = _DOW_BIAS.get(dow, 0)

    # Combine: if both agree → stronger signal; if conflict → neutral
    if month_signal == dow_signal:
        combined = month_signal
    elif month_signal != 0 and dow_signal == 0:
        combined = month_signal
    elif dow_signal != 0 and month_signal == 0:
        combined = dow_signal
    else:
        combined = 0  # conflict → neutral

    month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                   7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    return {
        "month": month_names.get(month, "?"),
        "month_signal": month_signal,
        "day_of_week": dow_names.get(dow, "?"),
        "dow_signal": dow_signal,
        "combined_signal": combined,
        "signal_text": {-1: "bullish", 0: "neutral", 1: "bearish"}.get(combined, "neutral"),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  COMBINED MACRO SIGNAL
# ═══════════════════════════════════════════════════════════════════════════

def get_full_macro_signal() -> Dict:
    """
    Aggregate all macro data sources into one comprehensive signal.

    Combines:
      - FRED real yields + inflation + dollar + gold VIX
      - Seasonality (month + day-of-week)
      - COT data (already in smc_engine)

    Myfxbook retail sentiment removed 2026-04-15 — required broker linking
    which user didn't want, and credentials had gone stale causing log spam.
    """
    # Backtest mode: macro data (FRED series) is only available for TODAY —
    # applying it to historical bars = look-ahead. Seasonality is
    # deterministic (month/weekday) so can stay. But to keep backtest
    # behavior comparable to strategy-only signal, we short-circuit the
    # whole thing to neutral.
    if os.environ.get("QUANT_BACKTEST_MODE") == "1":
        return {
            "composite_signal": 0,
            "signal_text": "backtest neutral",
            "signals_aligned": False,
            "data": {"backtest_mode": True},
        }
    fred = get_fred_data()
    seasonality = get_seasonality_signal()

    signals = []

    # FRED composite
    fred_signal = fred.get("composite_signal", 0)
    if fred_signal != 0:
        signals.append(("fred", fred_signal))

    # Seasonality
    season_signal = seasonality.get("combined_signal", 0)
    if season_signal != 0:
        signals.append(("seasonality", season_signal))

    # Aggregate
    bullish = sum(1 for _, s in signals if s == -1)
    bearish = sum(1 for _, s in signals if s == 1)

    if bullish > bearish:
        composite = -1
    elif bearish > bullish:
        composite = 1
    else:
        composite = 0

    return {
        "composite_signal": composite,
        "composite_text": {-1: "bullish", 0: "neutral", 1: "bearish"}.get(composite, "neutral"),
        "signal_count": len(signals),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "signals": dict(signals),
        "fred": fred,
        "seasonality": seasonality,
    }
