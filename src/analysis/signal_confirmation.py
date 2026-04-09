"""
signal_confirmation.py — warstwa potwierdzenia sygnalow tradingowych.

Filtruje falszywe sygnaly przez:
  - Multi-timeframe agreement (MTF)
  - Volume confirmation
  - Volatility regime filter
  - Price action confirmation (near S/R levels)
  - Confluence scoring

Kazdy filtr zwraca multiplier (0.0-1.5) na confidence.
Sygnal przechodzi jesli laczny score > threshold.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from src.core.logger import logger


def mtf_agreement(symbol: str = "XAU/USD") -> Dict:
    """Check multi-timeframe trend agreement.

    Returns:
        dict with 'agreement' (0.0-1.0), 'direction' (bull/bear/mixed),
        'bull_count', 'bear_count', 'details' per TF.
    """
    try:
        from src.trading.smc_engine import get_mtf_confluence
        mtf = get_mtf_confluence(symbol)

        bull_pct = mtf.get('bull_pct', 50)
        bear_pct = mtf.get('bear_pct', 50)
        direction = mtf.get('direction', 'MIXED')
        score = mtf.get('confluence_score', 50)

        # Agreement = how strongly TFs agree (0.5 = split, 1.0 = unanimous)
        agreement = max(bull_pct, bear_pct) / 100.0

        trend = 'bull' if bull_pct > bear_pct else 'bear'
        if agreement < 0.55:
            trend = 'mixed'

        return {
            'agreement': agreement,
            'direction': trend,
            'bull_count': mtf.get('bull_tf_count', 0),
            'bear_count': mtf.get('bear_tf_count', 0),
            'confluence_score': score,
            'details': mtf.get('timeframes', {}),
        }
    except Exception as e:
        logger.debug(f"MTF agreement error: {e}")
        return {'agreement': 0.5, 'direction': 'mixed', 'bull_count': 0,
                'bear_count': 0, 'confluence_score': 50, 'details': {}}


def volume_confirms(df: pd.DataFrame, signal_direction: str) -> float:
    """Check if volume confirms the signal direction.

    Returns confidence multiplier:
      1.3 = strong volume confirmation
      1.0 = neutral
      0.6 = volume contradicts signal (fade)
    """
    if 'volume' not in df.columns or df['volume'].sum() == 0:
        return 1.0  # no volume data — neutral

    current_vol = df['volume'].iloc[-1]
    avg_vol = df['volume'].iloc[-20:].mean()
    vol_ratio = current_vol / (avg_vol + 1e-10)

    # Is price moving with or against volume?
    is_green = df['close'].iloc[-1] > df['open'].iloc[-1]

    if signal_direction == "LONG":
        if is_green and vol_ratio > 1.3:
            return 1.3  # green candle + high volume = strong buy confirmation
        elif not is_green and vol_ratio > 1.5:
            return 0.6  # red candle + high volume = selling pressure, bad for long
        elif vol_ratio < 0.7:
            return 0.8  # low volume = weak conviction
    elif signal_direction == "SHORT":
        if not is_green and vol_ratio > 1.3:
            return 1.3  # red candle + high volume = strong sell confirmation
        elif is_green and vol_ratio > 1.5:
            return 0.6  # green candle + high volume = buying, bad for short
        elif vol_ratio < 0.7:
            return 0.8

    return 1.0


def volatility_filter(df: pd.DataFrame, signal_direction: str) -> float:
    """Filter signals based on volatility regime.

    Low vol (percentile < 0.25): prefer mean-reversion, penalize trend-following
    Normal vol (0.25-0.75): all signals OK
    High vol (> 0.75): only trend-following, penalize reversals

    Returns confidence multiplier (0.5-1.3).
    """
    if len(df) < 100:
        return 1.0

    vol = df['close'].pct_change().rolling(20).std().iloc[-1]
    vol_pctile = df['close'].pct_change().rolling(20).std().rank(pct=True).iloc[-1]

    ema20 = df['close'].ewm(span=20).mean().iloc[-1]
    price = df['close'].iloc[-1]
    with_trend = (signal_direction == "LONG" and price > ema20) or \
                 (signal_direction == "SHORT" and price < ema20)

    if vol_pctile < 0.25:
        # Low volatility — mean reversion zone
        if with_trend:
            return 0.7  # trend signal in low vol = likely to fail
        else:
            return 1.2  # counter-trend in low vol = mean reversion likely
    elif vol_pctile > 0.75:
        # High volatility — momentum/breakout zone
        if with_trend:
            return 1.3  # trend signal in high vol = breakout confirmation
        else:
            return 0.5  # counter-trend in high vol = dangerous
    else:
        return 1.0  # normal vol — neutral


def price_action_confirms(df: pd.DataFrame, signal_direction: str) -> float:
    """Check if price is near key support/resistance levels.

    Signals near S/R are higher quality (bounce/break).
    Returns confidence multiplier (0.7-1.4).
    """
    if len(df) < 20:
        return 1.0

    atr = df['high'].iloc[-14:].values - df['low'].iloc[-14:].values
    atr_val = float(np.mean(atr))
    price = df['close'].iloc[-1]

    # Recent swing levels (20-bar)
    swing_high = df['high'].iloc[-20:].max()
    swing_low = df['low'].iloc[-20:].min()

    near_support = (price - swing_low) < atr_val * 0.5
    near_resistance = (swing_high - price) < atr_val * 0.5

    # 2-bar reversal pattern at current position
    prev_close = df['close'].iloc[-2]
    curr_close = df['close'].iloc[-1]
    reversal_bull = (df['low'].iloc[-1] < df['low'].iloc[-2]) and (curr_close > prev_close)
    reversal_bear = (df['high'].iloc[-1] > df['high'].iloc[-2]) and (curr_close < prev_close)

    score = 1.0

    if signal_direction == "LONG":
        if near_support:
            score += 0.3  # buying at support = high quality
        if reversal_bull:
            score += 0.2  # bullish reversal confirmation
        if near_resistance:
            score -= 0.2  # buying at resistance = risky
    elif signal_direction == "SHORT":
        if near_resistance:
            score += 0.3  # selling at resistance = high quality
        if reversal_bear:
            score += 0.2  # bearish reversal confirmation
        if near_support:
            score -= 0.2  # selling at support = risky

    return max(0.5, min(1.5, score))


def confirm_signal(df: pd.DataFrame, signal_direction: str,
                   ensemble_score: float, ensemble_confidence: float,
                   symbol: str = "XAU/USD",
                   use_mtf: bool = True) -> Dict:
    """Main confirmation pipeline. Applies all filters to a signal.

    Args:
        df: OHLCV data
        signal_direction: "LONG", "SHORT", or "CZEKAJ"
        ensemble_score: raw ensemble score (0-1)
        ensemble_confidence: raw confidence (0-1)
        symbol: trading symbol
        use_mtf: whether to check multi-timeframe (costs API credits)

    Returns:
        dict with 'confirmed' (bool), 'final_confidence', 'final_signal',
        'adjustments' (per-filter breakdown), 'reason' (human-readable)
    """
    if signal_direction == "CZEKAJ":
        return {
            'confirmed': False,
            'final_confidence': 0.0,
            'final_signal': 'CZEKAJ',
            'adjustments': {},
            'reason': 'No signal to confirm',
        }

    adjustments = {}
    total_multiplier = 1.0
    reasons = []

    # --- Załaduj historyczną accuracy filtrów z bazy (jeśli dostępne) ---
    filter_accuracy = {}
    try:
        from src.core.database import NewsDB
        _fdb = NewsDB()
        fa_rows = _fdb.get_filter_accuracy()
        for row in fa_rows:
            # row = (filter_name, direction, correct_blocks, incorrect_blocks,
            #        correct_passes, incorrect_passes, accuracy)
            key = f"{row[0]}_{row[1]}"
            total_decisions = (row[2] or 0) + (row[3] or 0) + (row[4] or 0) + (row[5] or 0)
            if total_decisions >= 10:
                filter_accuracy[row[0]] = {
                    'accuracy': row[6] or 0.5,
                    'total': total_decisions,
                    'direction': row[1]
                }
    except Exception:
        pass

    # 1. Volume confirmation
    vol_mult = volume_confirms(df, signal_direction)
    # Korekta na podstawie historycznej accuracy filtra volume
    if 'volume' in filter_accuracy and filter_accuracy['volume']['accuracy'] < 0.45:
        vol_mult = 1.0 + (vol_mult - 1.0) * 0.5  # zmniejsz wpływ słabego filtra
        reasons.append(f'volume dampened (hist acc={filter_accuracy["volume"]["accuracy"]:.0%})')
    adjustments['volume'] = vol_mult
    total_multiplier *= vol_mult
    if vol_mult < 0.8:
        reasons.append('volume contradicts')
    elif vol_mult > 1.2:
        reasons.append('volume confirms')

    # 2. Volatility regime
    vola_mult = volatility_filter(df, signal_direction)
    if 'volatility' in filter_accuracy and filter_accuracy['volatility']['accuracy'] < 0.45:
        vola_mult = 1.0 + (vola_mult - 1.0) * 0.5
        reasons.append(f'vol filter dampened (hist acc={filter_accuracy["volatility"]["accuracy"]:.0%})')
    adjustments['volatility'] = vola_mult
    total_multiplier *= vola_mult
    if vola_mult < 0.7:
        reasons.append('wrong vol regime')
    elif vola_mult > 1.2:
        reasons.append('vol regime aligned')

    # 3. Price action
    pa_mult = price_action_confirms(df, signal_direction)
    if 'price_action' in filter_accuracy and filter_accuracy['price_action']['accuracy'] < 0.45:
        pa_mult = 1.0 + (pa_mult - 1.0) * 0.5
    adjustments['price_action'] = pa_mult
    total_multiplier *= pa_mult
    if pa_mult > 1.2:
        reasons.append('near S/R level')

    # 4. Multi-timeframe (optional — uses API credits)
    if use_mtf:
        try:
            mtf = mtf_agreement(symbol)
            mtf_score = mtf['agreement']
            mtf_dir = mtf['direction']

            if mtf_dir == signal_direction.lower() or (
                mtf_dir == 'bull' and signal_direction == 'LONG') or (
                mtf_dir == 'bear' and signal_direction == 'SHORT'):
                mtf_mult = 0.8 + mtf_score * 0.5  # 0.8-1.3
            elif mtf_dir == 'mixed':
                mtf_mult = 0.9
            else:
                mtf_mult = max(0.5, 1.0 - mtf_score * 0.5)  # 0.5-1.0

            adjustments['mtf'] = mtf_mult
            total_multiplier *= mtf_mult
            if mtf_mult < 0.7:
                reasons.append(f'MTF disagrees ({mtf_dir})')
            elif mtf_mult > 1.1:
                reasons.append(f'MTF confirms ({mtf_dir})')
        except Exception as e:
            logger.debug(f"MTF check failed: {e}")
            adjustments['mtf'] = 1.0

    # Apply multiplier to confidence
    final_confidence = ensemble_confidence * total_multiplier
    final_confidence = min(final_confidence, 1.0)

    # Decision: confirm if final confidence high enough
    # Podniesiono z 0.30/0.7 na 0.33/0.65 — umiarkowanie surowszy filtr
    # ale total_multiplier obniżony (0.65) żeby nie blokować przy jednym słabym filtrze
    confirmed = final_confidence >= 0.33 and total_multiplier >= 0.65

    if not confirmed and total_multiplier < 0.65:
        reasons.append('too many filters failed')

    return {
        'confirmed': confirmed,
        'final_confidence': round(final_confidence, 4),
        'final_signal': signal_direction if confirmed else 'CZEKAJ',
        'total_multiplier': round(total_multiplier, 3),
        'adjustments': adjustments,
        'reason': '; '.join(reasons) if reasons else 'standard confirmation',
    }
