"""
indicators.py — zaawansowane wskaźniki techniczne.
"""

import pandas as pd
import numpy as np

def ichimoku(df: pd.DataFrame, tenkan=9, kijun=26, senkou=52):
    """Oblicza wskaźnik Ichimoku."""
    tenkan_sen = (df['high'].rolling(tenkan).max() + df['low'].rolling(tenkan).min()) / 2
    kijun_sen = (df['high'].rolling(kijun).max() + df['low'].rolling(kijun).min()) / 2
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(kijun)
    senkou_span_b = ((df['high'].rolling(senkou).max() + df['low'].rolling(senkou).min()) / 2).shift(kijun)
    chikou_span = df['close'].shift(-kijun)
    return pd.DataFrame({
        'tenkan_sen': tenkan_sen,
        'kijun_sen': kijun_sen,
        'senkou_span_a': senkou_span_a,
        'senkou_span_b': senkou_span_b,
        'chikou_span': chikou_span
    })

def volume_profile(df: pd.DataFrame, num_bins=20):
    """Oblicza Volume Profile – POC, VA High, VA Low.
    Dla forex (volume=0) używa tick-count (1 per bar) zamiast wolumenu."""
    price_range = df['high'].max() - df['low'].min()
    if price_range <= 0:
        return {'poc': df['close'].iloc[-1], 'vah': df['high'].max(), 'val': df['low'].min()}
    bin_width = price_range / num_bins
    bins = np.arange(df['low'].min(), df['high'].max() + bin_width, bin_width)

    # Sprawdź czy wolumen jest dostępny i niezerowy
    has_volume = 'volume' in df.columns and df['volume'].sum() > 0

    vol_by_price = {}
    for idx, row in df.iterrows():
        price = row['close']
        vol = float(row['volume']) if has_volume else 1.0  # tick-count fallback
        bin_idx = int((price - bins[0]) / bin_width)
        if 0 <= bin_idx < len(bins)-1:
            price_level = round(bins[bin_idx] + bin_width/2, 2)
            vol_by_price[price_level] = vol_by_price.get(price_level, 0) + vol
    if not vol_by_price:
        return {'poc': df['close'].iloc[-1], 'vah': df['high'].max(), 'val': df['low'].min()}
    poc = max(vol_by_price, key=vol_by_price.get)
    sorted_vol = sorted(vol_by_price.items(), key=lambda x: x[1], reverse=True)
    total_vol = sum(vol_by_price.values())
    cum_vol = 0
    vah, val = poc, poc
    if total_vol > 0:
        for price, vol in sorted_vol:
            cum_vol += vol
            if cum_vol / total_vol <= 0.35:
                val = min(val, price)
                vah = max(vah, price)
    return {'poc': poc, 'vah': vah, 'val': val}
