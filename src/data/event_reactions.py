"""
src/event_reactions.py — Historical Event Reaction Database for Gold

Maps macro economic events to gold price reactions:
  - CPI release -> gold moved +X% in next 4h
  - Fed rate decision -> gold moved -Y% in next 24h
  - NFP surprise -> gold moved +Z% in next 1h

Data sources:
  - FRED API: CPI (CPIAUCSL), Fed Funds (FEDFUNDS), NFP (PAYEMS)
  - yfinance: Gold price around event dates
  - Computed: surprise direction, gold reaction magnitude

Usage:
    from src.data.event_reactions import get_event_bias
    bias = get_event_bias("CPI")  # returns historical reaction pattern
"""

import os
import datetime
import pickle
from typing import Optional, Dict, List
from dotenv import load_dotenv
from src.core.logger import logger

load_dotenv()

_CACHE_FILE = "data/event_reactions_cache.pkl"
_CACHE_TTL = 86400 * 7  # 7 days (historical data changes slowly)


def _load_cache() -> Optional[Dict]:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'rb') as f:
                cached = pickle.load(f)
            import time
            if time.time() - cached.get('ts', 0) < _CACHE_TTL:
                return cached.get('data')
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        pass
    return None


def _save_cache(data: Dict):
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE) or ".", exist_ok=True)
        with open(_CACHE_FILE, 'wb') as f:
            import time
            pickle.dump({'data': data, 'ts': time.time()}, f)
    except (OSError, pickle.PicklingError):
        pass


def build_event_reaction_database() -> Dict:
    """
    Build a database of macro event -> gold price reaction.

    For each event type (CPI, FOMC, NFP):
      1. Get monthly release dates from FRED
      2. Get gold price at T-1d, T, T+1d from yfinance
      3. Compute reaction (% change on event day)
      4. Classify: positive_surprise / negative_surprise / inline
      5. Aggregate: avg reaction by surprise type

    Returns dict with per-event-type statistics.
    """
    cached = _load_cache()
    if cached is not None:
        return cached

    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        return {"error": "FRED_API_KEY not set"}

    try:
        from fredapi import Fred
        import yfinance as yf
        import numpy as np

        fred = Fred(api_key=api_key)
        logger.info("[EVENTS] Building event reaction database...")

        # Fetch gold daily prices (2 years)
        gold = yf.Ticker("GC=F")
        gold_hist = gold.history(period="2y", interval="1d")
        if gold_hist.empty:
            return {"error": "No gold price data"}

        gold_hist = gold_hist.reset_index()
        col_map = {c: c.lower() for c in gold_hist.columns}
        gold_hist.rename(columns=col_map, inplace=True)
        gold_hist['date'] = gold_hist['date'].dt.date if 'date' in gold_hist.columns else gold_hist.index.date

        results = {}

        # --- CPI Events ---
        results["CPI"] = _analyze_event(
            fred, 'CPIAUCSL', gold_hist, "CPI",
            surprise_fn=lambda curr, prev: (curr - prev) / prev * 100  # MoM % change
        )

        # --- Fed Funds Rate Changes ---
        results["FOMC"] = _analyze_event(
            fred, 'FEDFUNDS', gold_hist, "FOMC",
            surprise_fn=lambda curr, prev: curr - prev  # absolute change in rate
        )

        # --- NFP (Non-Farm Payrolls) ---
        results["NFP"] = _analyze_event(
            fred, 'PAYEMS', gold_hist, "NFP",
            surprise_fn=lambda curr, prev: (curr - prev)  # absolute change in thousands
        )

        _save_cache(results)
        logger.info(f"[EVENTS] Database built: CPI={results['CPI'].get('count', 0)}, "
                     f"FOMC={results['FOMC'].get('count', 0)}, NFP={results['NFP'].get('count', 0)} events")
        return results

    except ImportError as e:
        logger.debug(f"[EVENTS] Missing dependency: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.warning(f"[EVENTS] Build failed: {e}")
        return {"error": str(e)}


def _analyze_event(fred, series_id: str, gold_hist, event_name: str,
                   surprise_fn=None) -> Dict:
    """
    Analyze gold's reaction to a specific FRED series event.

    For each data release:
      - Compute surprise (current vs previous)
      - Find gold price change on release day
      - Classify as positive_surprise / negative_surprise / inline
      - Aggregate statistics
    """
    import numpy as np

    try:
        data = fred.get_series(series_id, observation_start='2024-01-01')
        data = data.dropna()

        if len(data) < 3:
            return {"count": 0, "error": "insufficient data"}

        reactions = {"positive_surprise": [], "negative_surprise": [], "inline": []}
        all_reactions = []

        for i in range(1, len(data)):
            event_date = data.index[i].date()
            prev_val = float(data.iloc[i - 1])
            curr_val = float(data.iloc[i])

            if surprise_fn:
                surprise = surprise_fn(curr_val, prev_val)
            else:
                surprise = curr_val - prev_val

            # Find gold price around event date (T-1, T, T+1)
            gold_before = gold_hist[gold_hist['date'] <= event_date].tail(2)
            gold_after = gold_hist[gold_hist['date'] >= event_date].head(2)

            if len(gold_before) < 1 or len(gold_after) < 1:
                continue

            price_before = float(gold_before['close'].iloc[-1])
            price_on_day = float(gold_after['close'].iloc[0])

            if price_before <= 0:
                continue

            gold_reaction_pct = (price_on_day - price_before) / price_before * 100

            # Classify surprise
            if abs(surprise) < 0.01:
                category = "inline"
            elif surprise > 0:
                category = "positive_surprise"
            else:
                category = "negative_surprise"

            reactions[category].append(gold_reaction_pct)
            all_reactions.append({
                "date": event_date.isoformat(),
                "value": round(curr_val, 2),
                "prev": round(prev_val, 2),
                "surprise": round(surprise, 4),
                "gold_reaction_pct": round(gold_reaction_pct, 3),
                "category": category,
            })

        # Aggregate
        result = {
            "event": event_name,
            "series_id": series_id,
            "count": len(all_reactions),
        }

        for cat in ["positive_surprise", "negative_surprise", "inline"]:
            vals = reactions[cat]
            if vals:
                result[cat] = {
                    "count": len(vals),
                    "avg_gold_reaction_pct": round(float(np.mean(vals)), 3),
                    "median_gold_reaction_pct": round(float(np.median(vals)), 3),
                    "std": round(float(np.std(vals)), 3),
                    "bullish_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
                }
            else:
                result[cat] = {"count": 0}

        # Recent events (last 5)
        result["recent"] = all_reactions[-5:]

        return result

    except Exception as e:
        return {"count": 0, "error": str(e)}


def get_event_bias(event_type: str = "CPI") -> Dict:
    """
    Get historical gold reaction bias for a specific event type.

    Args:
        event_type: "CPI", "FOMC", or "NFP"

    Returns:
        {
            "event": "CPI",
            "positive_surprise": {"avg_gold_reaction_pct": -0.35, "count": 8},
            "negative_surprise": {"avg_gold_reaction_pct": +0.52, "count": 6},
            "bias_text": "CPI above forecast -> gold drops 0.35% avg"
        }
    """
    db = build_event_reaction_database()
    if "error" in db:
        return db

    event = db.get(event_type.upper(), {})
    if not event or event.get("count", 0) == 0:
        return {"event": event_type, "error": "no data"}

    # Generate human-readable bias
    pos = event.get("positive_surprise", {})
    neg = event.get("negative_surprise", {})

    bias_parts = []
    if pos.get("count", 0) >= 3:
        avg = pos.get("avg_gold_reaction_pct", 0)
        direction = "rises" if avg > 0 else "drops"
        bias_parts.append(f"{event_type} above forecast -> gold {direction} {abs(avg):.2f}% avg ({pos['count']} events)")
    if neg.get("count", 0) >= 3:
        avg = neg.get("avg_gold_reaction_pct", 0)
        direction = "rises" if avg > 0 else "drops"
        bias_parts.append(f"{event_type} below forecast -> gold {direction} {abs(avg):.2f}% avg ({neg['count']} events)")

    event["bias_text"] = " | ".join(bias_parts) if bias_parts else "insufficient data"
    return event


def get_all_event_biases() -> Dict:
    """Get bias summary for all tracked events."""
    return {
        "CPI": get_event_bias("CPI"),
        "FOMC": get_event_bias("FOMC"),
        "NFP": get_event_bias("NFP"),
    }
