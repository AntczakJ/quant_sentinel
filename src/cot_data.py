"""
src/cot_data.py — CFTC Commitment of Traders (COT) Data for Gold

Fetches weekly COT reports from CFTC public data (free, no API key).
Calculates positioning signals for Gold (commodity code 088691):
  - Managed Money net position (speculative sentiment)
  - Commercial net position (hedging activity)
  - Percentile rank (52-week lookback for extremes)
  - Week-over-week change (momentum)

Data is released every Friday 3:30 PM ET (reflects Tuesday positions).
Cached for 24h since data only updates weekly.

Usage:
    from src.cot_data import get_gold_cot_signal
    signal = get_gold_cot_signal()
    # Returns: {"signal": -1|0|1, "mm_net": int, "mm_percentile": float, ...}
"""

import os
import time
import pickle
import requests
import io
import zipfile
from typing import Optional, Dict
from src.logger import logger

# Cache COT data for 24h (data only updates weekly on Fridays)
_COT_CACHE_TTL = 86400  # 24 hours
_COT_CACHE_FILE = "data/cot_cache.pkl"

# Gold commodity code on COMEX
_GOLD_MARKET_NAME = "GOLD - COMMODITY EXCHANGE INC."

# CFTC disaggregated report URL (current year)
_CFTC_BASE_URL = "https://www.cftc.gov/files/dea/history"


def _fetch_cot_dataframe():
    """
    Download current year's legacy COT report from CFTC (futures + options combined).
    Legacy format has Noncommercial/Commercial positions — simpler and more reliable.
    Returns pandas DataFrame or None on failure.
    """
    import pandas as pd
    from datetime import datetime

    year = datetime.now().year
    url = f"{_CFTC_BASE_URL}/deahistfo{year}.zip"

    try:
        logger.info(f"[COT] Fetching CFTC legacy report: {year}")
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, low_memory=False)

        logger.info(f"[COT] Loaded {len(df)} rows from CFTC legacy report")
        return df

    except requests.RequestException as e:
        logger.warning(f"[COT] Failed to fetch CFTC data: {e}")
        return None
    except (zipfile.BadZipFile, KeyError, IndexError) as e:
        logger.warning(f"[COT] Failed to parse CFTC zip: {e}")
        return None


def _extract_gold_cot(df) -> Optional[Dict]:
    """
    Extract Gold-specific COT data from legacy CFTC report and compute trading signals.

    Legacy report columns (spaces in names):
      - 'Noncommercial Positions-Long (All)' — speculators long (proxy for managed money)
      - 'Noncommercial Positions-Short (All)' — speculators short
      - 'Commercial Positions-Long (All)' — hedgers long
      - 'Commercial Positions-Short (All)' — hedgers short
      - 'Open Interest (All)' — total open contracts
    """
    import numpy as np

    # Find name column (varies: 'Market and Exchange Names' or 'Market_and_Exchange_Names')
    name_col = None
    for candidate in ['Market and Exchange Names', 'Market_and_Exchange_Names']:
        if candidate in df.columns:
            name_col = candidate
            break
    if name_col is None:
        logger.warning("[COT] Cannot find market name column")
        return None

    # Filter for COMEX Gold specifically (not Micro Gold or Coinbase)
    gold = df[df[name_col].str.strip() == 'GOLD - COMMODITY EXCHANGE INC.'].copy()
    if gold.empty:
        # Fallback: any Gold on COMEX
        gold = df[
            df[name_col].str.contains('GOLD', case=False, na=False) &
            df[name_col].str.contains('COMMODITY EXCHANGE', case=False, na=False) &
            ~df[name_col].str.contains('MICRO', case=False, na=False)
        ].copy()
    if gold.empty:
        logger.warning("[COT] No COMEX Gold data found in CFTC report")
        return None

    # Find date column
    date_col = None
    for candidate in ['As of Date in Form YYYY-MM-DD', 'Report_Date_as_YYYY-MM-DD',
                       'As_of_Date_In_Form_YYYY-MM-DD']:
        if candidate in gold.columns:
            date_col = candidate
            break
    if date_col is None:
        # Fallback: use numeric date
        date_col = [c for c in gold.columns if 'Date' in c and 'YYYY' in c]
        date_col = date_col[0] if date_col else None

    if date_col:
        gold = gold.sort_values(date_col).reset_index(drop=True)

    # Find position columns dynamically (legacy format uses spaces)
    def _find_col(patterns: list) -> Optional[str]:
        for p in patterns:
            matches = [c for c in gold.columns if p.lower() in c.lower()]
            if matches:
                return matches[0]
        return None

    nc_long = _find_col(['Noncommercial Positions-Long (All)', 'NonComm_Positions_Long_All'])
    nc_short = _find_col(['Noncommercial Positions-Short (All)', 'NonComm_Positions_Short_All'])
    comm_long = _find_col(['Commercial Positions-Long (All)', 'Comm_Positions_Long_All'])
    comm_short = _find_col(['Commercial Positions-Short (All)', 'Comm_Positions_Short_All'])
    oi_col_name = _find_col(['Open Interest (All)', 'Open_Interest_All'])

    if not nc_long or not nc_short:
        logger.warning(f"[COT] Cannot find speculator position columns")
        return None

    # Calculate net positions
    gold['spec_net'] = gold[nc_long].astype(float) - gold[nc_short].astype(float)

    if comm_long and comm_short:
        gold['commercial_net'] = gold[comm_long].astype(float) - gold[comm_short].astype(float)
    else:
        gold['commercial_net'] = 0

    # Week-over-week change
    gold['spec_net_change'] = gold['spec_net'].diff()

    # Percentile rank (52-week lookback)
    lookback = min(52, len(gold))
    recent = gold.tail(lookback)
    net_min = float(recent['spec_net'].min())
    net_max = float(recent['spec_net'].max())
    net_range = net_max - net_min

    latest = gold.iloc[-1]
    latest_net = float(latest['spec_net'])

    percentile = ((latest_net - net_min) / net_range * 100) if net_range > 0 else 50.0

    # Open interest
    try:
        open_interest = int(float(latest[oi_col_name])) if oi_col_name else 0
    except (ValueError, TypeError):
        open_interest = 0

    # Signal: contrarian positioning
    if percentile > 80:
        signal = 1   # extreme speculator long → bearish for gold (crowded)
    elif percentile < 20:
        signal = -1  # extreme speculator short → bullish for gold (contrarian)
    else:
        signal = 0

    result = {
        "report_date": str(latest.get(date_col, 'unknown')) if date_col else 'unknown',
        "spec_net": int(latest_net),
        "spec_long": int(float(latest.get(nc_long, 0))),
        "spec_short": int(float(latest.get(nc_short, 0))),
        "spec_net_change": int(float(latest.get('spec_net_change', 0) or 0)),
        "spec_percentile": round(percentile, 1),
        "commercial_net": int(float(latest.get('commercial_net', 0))),
        "open_interest": open_interest,
        "signal": signal,
        "signal_text": {-1: "bullish (extreme short)", 0: "neutral", 1: "bearish (extreme long)"}.get(signal, "neutral"),
        "lookback_weeks": lookback,
    }

    return result


def _load_cache() -> Optional[Dict]:
    """Load cached COT data if fresh enough."""
    try:
        if os.path.exists(_COT_CACHE_FILE):
            with open(_COT_CACHE_FILE, 'rb') as f:
                cached = pickle.load(f)
            if time.time() - cached.get('ts', 0) < _COT_CACHE_TTL:
                return cached.get('data')
    except (FileNotFoundError, pickle.UnpicklingError, EOFError, KeyError):
        pass
    return None


def _save_cache(data: Dict):
    """Save COT data to cache."""
    try:
        os.makedirs(os.path.dirname(_COT_CACHE_FILE) or ".", exist_ok=True)
        with open(_COT_CACHE_FILE, 'wb') as f:
            pickle.dump({'data': data, 'ts': time.time()}, f)
    except (OSError, pickle.PicklingError):
        pass


def get_gold_cot_signal() -> Optional[Dict]:
    """
    Get Gold COT positioning signal.

    Returns dict with:
      signal: -1 (bullish — extreme short), 0 (neutral), 1 (bearish — extreme long)
      mm_net: Managed Money net contracts
      mm_percentile: 52-week percentile (0-100)
      mm_net_change: Week-over-week change
      report_date: Date of the COT report
      commercial_net: Commercial hedger net position

    Cached for 24h. Returns None if data unavailable.
    """
    # Try cache first
    cached = _load_cache()
    if cached is not None:
        logger.debug(f"[COT] Using cached data from {cached.get('report_date', '?')}")
        return cached

    # Fetch fresh data
    df = _fetch_cot_dataframe()
    if df is None:
        return None

    result = _extract_gold_cot(df)
    if result is None:
        return None

    # Cache result
    _save_cache(result)

    logger.info(
        f"[COT] Gold: spec net={result['spec_net']:+,} ({result['spec_percentile']:.0f}th pct), "
        f"change={result['spec_net_change']:+,}, signal={result['signal_text']}"
    )

    return result
