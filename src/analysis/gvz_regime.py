"""src/analysis/gvz_regime.py — Gold-VIX (GVZ) term-structure regime gate.

2026-05-06 (Phase A.3): GVZ backwardation predicts directional gold moves.
When GVZ > VIX-equivalent forward (backwardation) → fear is acute, gold
pops. When deep contango → normal regime, no asymmetric pressure.

Source: BIS Working Paper 619 (volatility risk premia and commodities)
+ documented GVZ-XAU regime patterns (medium.com/@crisvelasquez).

Data: FRED GVZCLS (free), already in our project (FRED_API_KEY set).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


# Cache GVZ readings to avoid hammering FRED
_gvz_cache: dict = {"value": None, "ts": None, "term_struct": None}
_CACHE_TTL_SEC = 3600  # 1h


def _fetch_gvz_term_structure() -> Optional[dict]:
    """Pull recent GVZ value + 20d MA. Returns dict or None on failure."""
    try:
        from fredapi import Fred
        import os
        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            return None
        fred = Fred(api_key=api_key)
        # GVZCLS = CBOE Gold ETF Volatility Index, daily close
        gvz_series = fred.get_series("GVZCLS").dropna().tail(30)
        if len(gvz_series) < 20:
            return None
        current = float(gvz_series.iloc[-1])
        ma20 = float(gvz_series.tail(20).mean())
        # Term structure proxy: current vs 20d-ma
        # backwardation = current > ma (recent stress higher than baseline)
        # contango = current < ma (calmer than baseline)
        term_pct = (current - ma20) / ma20 if ma20 > 0 else 0.0
        return {
            "current": current,
            "ma20": ma20,
            "term_pct": round(term_pct * 100, 2),  # +X% backwardation, -X% contango
        }
    except Exception:
        return None


def get_gvz_regime() -> dict:
    """Return current GVZ regime classification with caching.

    Returns:
        regime: 'backwardation' | 'contango' | 'neutral' | 'unknown'
        term_pct: float (current vs 20d ma, %)
        gold_bias: -1 (bearish) | 0 (neutral) | +1 (bullish gold)
    """
    global _gvz_cache
    now = dt.datetime.now(dt.timezone.utc)
    if (_gvz_cache["ts"] is not None
            and (now - _gvz_cache["ts"]).total_seconds() < _CACHE_TTL_SEC
            and _gvz_cache["term_struct"] is not None):
        ts = _gvz_cache["term_struct"]
    else:
        ts = _fetch_gvz_term_structure()
        if ts is not None:
            _gvz_cache = {"value": ts["current"], "ts": now, "term_struct": ts}

    if ts is None:
        return {"regime": "unknown", "term_pct": None, "gold_bias": 0,
                "current": None, "ma20": None}

    term_pct = ts["term_pct"]

    # Thresholds:
    # > +5% — backwardation (acute stress, gold safe-haven bid reliable) → +1
    # < -5% — deep contango (calmer than baseline, no asymmetric pressure) → 0
    # otherwise neutral
    if term_pct > 5.0:
        regime = "backwardation"
        gold_bias = 1
    elif term_pct < -5.0:
        regime = "contango"
        gold_bias = 0  # not bearish, just no edge
    else:
        regime = "neutral"
        gold_bias = 0

    return {
        "regime": regime,
        "term_pct": term_pct,
        "current": ts["current"],
        "ma20": ts["ma20"],
        "gold_bias": gold_bias,
    }


def reset_cache() -> None:
    """Force-refresh on next get_gvz_regime() call (for tests)."""
    global _gvz_cache
    _gvz_cache = {"value": None, "ts": None, "term_struct": None}
