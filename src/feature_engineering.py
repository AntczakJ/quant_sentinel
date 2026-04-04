"""
feature_engineering.py — Advanced feature engineering for trading signals.

This module provides:
- Wavelet transforms for volatility analysis
- Williams %R indicator
- CCI (Commodity Channel Index)
- Volume-weighted indicators
- Price action patterns (Higher High/Low, Double Top/Bottom)
- Correlation features (XAU/USD vs USD/JPY)
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from scipy import signal
from src.logger import logger

def add_wavelet_features(df, wavelet='db4', level=3):
    """
    Add wavelet transform features for volatility analysis.

    Wavelets detect changes in volatility at multiple time scales.
    """
    try:
        from pywt import wavedec

        close = df['close'].values
        coeffs = wavedec(close, wavelet, level=level)

        # High-frequency details (noise/volatility)
        df['wavelet_volatility'] = pd.Series(
            coeffs[-1][:len(df)],
            index=df.index
        ).fillna(0)

        # Trend (low-frequency)
        df['wavelet_trend'] = pd.Series(
            coeffs[0][:len(df)],
            index=df.index
        ).fillna(0)

        logger.debug("Wavelet features added")
        return df
    except ImportError:
        logger.warning("PyWavelets not installed, skipping wavelet features")
        return df


def add_williams_r(df, period=14):
    """
    Williams %R indicator - Momentum indicator (range: -100 to 0).

    Readings:
    - Above -20: Overbought
    - Below -80: Oversold
    """
    high = df['high'].rolling(period).max()
    low = df['low'].rolling(period).min()
    df['williams_r'] = -100 * (high - df['close']) / (high - low + 1e-10)
    return df


def add_cci(df, period=20):
    """
    Commodity Channel Index - Measures deviation from average price.

    Signals:
    - Above +100: Overbought
    - Below -100: Oversold
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    sma = typical_price.rolling(period).mean()
    mad = typical_price.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean())
    df['cci'] = (typical_price - sma) / (0.015 * mad + 1e-10)
    return df


def add_volume_weighted_features(df):
    """Add volume-weighted moving average and volume momentum."""
    if 'volume' not in df.columns or df['volume'].sum() == 0:
        logger.warning("Volume data not available, skipping volume features")
        return df

    # Volume-Weighted Moving Average
    df['vwma_20'] = (df['close'] * df['volume']).rolling(20).sum() / df['volume'].rolling(20).sum()

    # Volume Rate of Change
    df['vroc_10'] = df['volume'].pct_change(10)

    # Money Flow Index (like RSI but with volume)
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    money_flow = typical_price * df['volume']

    positive_flow = np.where(typical_price > typical_price.shift(1), money_flow, 0)
    negative_flow = np.where(typical_price < typical_price.shift(1), money_flow, 0)

    df['positive_mf'] = pd.Series(positive_flow).rolling(14).sum()
    df['negative_mf'] = pd.Series(negative_flow).rolling(14).sum()
    df['mfi'] = 100 * df['positive_mf'] / (df['positive_mf'] + df['negative_mf'] + 1e-10)

    return df


def detect_price_patterns(df, lookback=5):
    """
    Detect price action patterns:
    - Higher Highs / Lower Lows
    - Double Top / Bottom
    - Support/Resistance breaks
    """
    df['higher_high'] = (df['high'].rolling(lookback).max().shift(1) < df['high'])
    df['lower_low'] = (df['low'].rolling(lookback).min().shift(1) > df['low'])

    # Double Top pattern (2 highs at similar level)
    df['double_top'] = 0
    for i in range(lookback + 1, len(df)):
        highs = df['high'].iloc[i-lookback:i]
        if len(highs[highs > highs.mean() + highs.std() * 0.5]) >= 2:
            df.loc[i, 'double_top'] = 1

    # Double Bottom pattern
    df['double_bottom'] = 0
    for i in range(lookback + 1, len(df)):
        lows = df['low'].iloc[i-lookback:i]
        if len(lows[lows < lows.mean() - lows.std() * 0.5]) >= 2:
            df.loc[i, 'double_bottom'] = 1

    return df


def add_correlation_features(df, corr_data, lookback=20):
    """
    Add correlation features between XAU/USD and USD/JPY.

    Correlation shifts reveal potential reversals in gold prices.
    """
    if corr_data is None or len(corr_data) == 0:
        return df

    # Calculate rolling correlation
    df['xau_usdjpy_corr'] = df['close'].rolling(lookback).corr(
        corr_data['close'] if isinstance(corr_data, pd.DataFrame) else pd.Series(corr_data)
    )

    # Correlation momentum
    df['corr_momentum'] = df['xau_usdjpy_corr'].diff(5)

    return df


def add_advanced_features(df, corr_data=None):
    """
    Add all advanced features to dataframe.

    This is the main entry point for feature engineering.
    """
    try:
        # Price action patterns
        df = detect_price_patterns(df)

        # Wavelet features
        df = add_wavelet_features(df)

        # Momentum indicators
        df = add_williams_r(df)
        df = add_cci(df)

        # Volume features
        df = add_volume_weighted_features(df)

        # Correlation features
        if corr_data is not None:
            df = add_correlation_features(df, corr_data)

        logger.info("All advanced features added successfully")
        return df

    except Exception as e:
        logger.error(f"Error adding advanced features: {e}")
        return df


def get_feature_importance(model, feature_names):
    """
    Extract feature importance from trained XGBoost model.

    Helps understand which features drive predictions.
    """
    try:
        if hasattr(model, 'feature_importances_'):
            importance = model.feature_importances_
            feature_importance = dict(zip(feature_names, importance))
            sorted_features = sorted(feature_importance.items(), key=lambda x: x[1], reverse=True)
            return dict(sorted_features[:10])  # Top 10
    except Exception as e:
        logger.error(f"Error extracting feature importance: {e}")

    return {}


# Test feature engineering
if __name__ == "__main__":
    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='5min')
    sample_data = pd.DataFrame({
        'open': np.random.uniform(2300, 2400, 100),
        'high': np.random.uniform(2300, 2400, 100),
        'low': np.random.uniform(2300, 2400, 100),
        'close': np.random.uniform(2300, 2400, 100),
        'volume': np.random.uniform(1e6, 5e6, 100),
    }, index=dates)

    # Add features
    sample_data = add_advanced_features(sample_data)
    print(f"Added features: {sample_data.columns.tolist()}")
    print(sample_data.head())

