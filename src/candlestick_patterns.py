# src/candlestick_patterns.py
"""
candlestick_patterns.py — wykrywanie formacji świecowych.
"""

import pandas as pd

def engulfing(df: pd.DataFrame, idx=-1):
    """Zwraca 'bullish'|'bearish'|False."""
    if len(df) < 2:
        return False
    prev = df.iloc[idx-1]
    curr = df.iloc[idx]
    if (prev['close'] < prev['open'] and curr['close'] > curr['open'] and
        curr['open'] < prev['close'] and curr['close'] > prev['open']):
        return 'bullish'
    if (prev['close'] > prev['open'] and curr['close'] < curr['open'] and
        curr['open'] > prev['close'] and curr['close'] < prev['open']):
        return 'bearish'
    return False

def pin_bar(df: pd.DataFrame, idx=-1, body_pct=0.3):
    """Zwraca 'bullish'|'bearish'|False."""
    candle = df.iloc[idx]
    high_low = candle['high'] - candle['low']
    if high_low == 0:
        return False
    body = abs(candle['close'] - candle['open'])
    if body / high_low > body_pct:
        return False
    lower_shadow = candle['open'] - candle['low'] if candle['close'] > candle['open'] else candle['close'] - candle['low']
    upper_shadow = candle['high'] - candle['close'] if candle['close'] > candle['open'] else candle['high'] - candle['open']
    if lower_shadow > 2 * upper_shadow and lower_shadow > body:
        return 'bullish'
    if upper_shadow > 2 * lower_shadow and upper_shadow > body:
        return 'bearish'
    return False

def inside_bar(df: pd.DataFrame, idx=-1):
    """Zwraca True jeśli świeca jest Inside Bar."""
    if len(df) < 2:
        return False
    prev = df.iloc[idx-1]
    curr = df.iloc[idx]
    return curr['high'] <= prev['high'] and curr['low'] >= prev['low']