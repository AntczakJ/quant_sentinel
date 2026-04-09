"""
src/gpr_index.py — Geopolitical Risk Index (GPR)

Free daily data from Caldara & Iacoviello (Federal Reserve economists).
Measures newspaper coverage of geopolitical threats, acts, and risks.

High GPR → geopolitical tension → gold bullish (safe haven demand)
Low GPR → calm markets → gold neutral/bearish

Source: https://www.matteoiacoviello.com/gpr.htm
Data: Daily, updated weekly, ~15k rows since 1985.
"""

import os
import time
import pickle
import requests
from typing import Optional, Dict
from io import BytesIO
from dotenv import load_dotenv
from src.logger import logger

load_dotenv()

_CACHE_FILE = "data/gpr_cache.pkl"
_CACHE_TTL = 86400  # 24 hours (data updates weekly)
_GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"


def get_gpr_signal() -> Dict:
    """
    Fetch GPR Index and generate gold trading signal.

    Returns:
      {
        "gpr_current": float,     # Today's GPR value
        "gpr_ma30": float,        # 30-day moving average
        "gpr_percentile": float,  # Percentile vs last 2 years (0-100)
        "signal": -1|0|1,         # -1=bullish gold (high risk), 1=bearish (calm)
        "signal_text": str,
      }
    """
    # Cache check
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'rb') as f:
                cached = pickle.load(f)
            if time.time() - cached.get('ts', 0) < _CACHE_TTL:
                return cached.get('data', {})
    except (FileNotFoundError, pickle.UnpicklingError, EOFError):
        pass

    try:
        import pandas as pd
        import numpy as np

        logger.info("[GPR] Fetching Geopolitical Risk Index...")
        resp = requests.get(_GPR_URL, timeout=20)
        resp.raise_for_status()

        df = pd.read_excel(BytesIO(resp.content))

        if 'GPRD' not in df.columns:
            return {"signal": 0, "error": "GPR column not found"}

        # Clean data
        df = df.dropna(subset=['GPRD'])
        if len(df) < 30:
            return {"signal": 0, "error": "insufficient GPR data"}

        latest = df.iloc[-1]
        gpr_current = float(latest['GPRD'])
        gpr_ma30 = float(latest.get('GPRD_MA30', gpr_current))
        gpr_act = float(latest.get('GPRD_ACT', 0))
        gpr_threat = float(latest.get('GPRD_THREAT', 0))

        # Percentile vs last 2 years (~500 trading days)
        lookback = min(500, len(df))
        recent = df['GPRD'].tail(lookback)
        percentile = float((recent < gpr_current).sum() / len(recent) * 100)

        # Signal: high GPR = geopolitical risk = safe haven = gold bullish
        if percentile > 80:
            signal = -1   # high risk -> gold bullish
            signal_text = f"bullish (GPR {percentile:.0f}th pct - elevated risk)"
        elif percentile < 20:
            signal = 1    # low risk -> gold bearish (no safe haven demand)
            signal_text = f"bearish (GPR {percentile:.0f}th pct - calm markets)"
        else:
            signal = 0
            signal_text = f"neutral (GPR {percentile:.0f}th pct)"

        result = {
            "gpr_current": round(gpr_current, 1),
            "gpr_ma30": round(gpr_ma30, 1),
            "gpr_act": round(gpr_act, 1),
            "gpr_threat": round(gpr_threat, 1),
            "gpr_percentile": round(percentile, 1),
            "gpr_date": str(latest.get('date', 'unknown')),
            "signal": signal,
            "signal_text": signal_text,
        }

        # Save cache
        try:
            os.makedirs(os.path.dirname(_CACHE_FILE) or ".", exist_ok=True)
            with open(_CACHE_FILE, 'wb') as f:
                pickle.dump({'data': result, 'ts': time.time()}, f)
        except (OSError, pickle.PicklingError):
            pass

        logger.info(f"[GPR] GPR={gpr_current:.0f} ({percentile:.0f}th pct), signal={signal_text}")
        return result

    except ImportError as e:
        logger.debug(f"[GPR] Missing dependency: {e}")
        return {"signal": 0, "error": f"missing: {e}"}
    except requests.RequestException as e:
        logger.warning(f"[GPR] Download failed: {e}")
        return {"signal": 0, "error": str(e)}
    except Exception as e:
        logger.warning(f"[GPR] Failed: {e}")
        return {"signal": 0, "error": str(e)}
