"""
features_v2.py — Multi-asset, multi-TF feature engineering.

Extends current features (compute.py FEATURE_COLS = 36) with:
  - Cross-asset features: silver, EURUSD, TLT (treasury), SPY, BTC, VIX
  - Multi-TF features: 15m/1h/4h/1d top features for a 5m entry signal
  - Sequence features: rolling N-bar windows for LSTM/Transformer

Backwards compatibility:
  - Original `compute_features` in compute.py UNTOUCHED (production live).
  - This module is opt-in for v2 training pipeline.

Usage:
    from src.analysis.features_v2 import compute_features_v2

    features = compute_features_v2(
        df_xau,
        higher_tf_dfs={'1h': df_xau_1h, '4h': df_xau_4h, '1d': df_xau_1d},
        cross_asset_dfs={'TLT': df_tlt, 'SPY': df_spy, 'BTC/USD': df_btc, ...},
    )
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.analysis.compute import compute_features, FEATURE_COLS

logger = logging.getLogger("quant_sentinel.features_v2")

WAREHOUSE_DIR = Path("data/historical")

# ─────────────────────────────────────────────────────────────────────
# CROSS-ASSET FEATURE LIST
# ─────────────────────────────────────────────────────────────────────

CROSS_ASSET_FEATURES = [
    # Silver — gold's twin (correlation typically 0.85+)
    "xag_corr_20",
    "xag_ret_5",
    "xag_zscore_20",
    # EURUSD — inverse USD strength proxy (alt to USDJPY)
    "eurusd_corr_20",
    "eurusd_ret_5",
    # Treasury (TLT 20yr ETF) — gold has strong inverse correlation with real yields
    "tlt_ret_20",
    "tlt_zscore_60",
    # SPY — risk on/off regime
    "spy_ret_60",
    "spy_zscore_60",
    # BTC — alternative store of value, risk asset
    "btc_ret_60",
    "btc_zscore_60",
    # VIX — volatility regime
    "vix_level",
    "vix_zscore_20",
]

MULTI_TF_FEATURES = [
    # 1h features projected onto 5m entry
    "h1_rsi", "h1_atr", "h1_above_ema20", "h1_trend_strength",
    "h1_macd", "h1_volatility_percentile",
    # 4h features
    "h4_rsi", "h4_atr", "h4_above_ema20", "h4_trend_strength",
    # Daily features
    "d1_rsi", "d1_above_ema20", "d1_trend_strength",
]

ALL_V2_FEATURE_COLS = list(FEATURE_COLS) + CROSS_ASSET_FEATURES + MULTI_TF_FEATURES


# ─────────────────────────────────────────────────────────────────────
# CROSS-ASSET FEATURE COMPUTATION
# ─────────────────────────────────────────────────────────────────────

def _safe_returns(s: pd.Series, periods: int) -> pd.Series:
    """Pct change with NaN/inf guard."""
    r = s.pct_change(periods=periods)
    return r.replace([np.inf, -np.inf], np.nan).fillna(0)


def _safe_zscore(s: pd.Series, window: int) -> pd.Series:
    """Rolling z-score with NaN/0 guard."""
    mean = s.rolling(window, min_periods=max(2, window // 4)).mean()
    std = s.rolling(window, min_periods=max(2, window // 4)).std()
    z = (s - mean) / std.replace(0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0)


def _safe_corr(a: pd.Series, b: pd.Series, window: int) -> pd.Series:
    """Rolling correlation with NaN guard."""
    c = a.rolling(window, min_periods=max(2, window // 4)).corr(b)
    return c.replace([np.inf, -np.inf], np.nan).fillna(0)


def _align_to_index(other_df: pd.DataFrame, target_index: pd.DatetimeIndex,
                    col: str = "close") -> pd.Series:
    """
    Reindex other_df[col] to target_index using forward-fill.
    Critical: never use future bars. The asof reindex uses last value
    available AT each timestamp.
    """
    if col not in other_df.columns:
        return pd.Series(np.nan, index=target_index)
    if "datetime" in other_df.columns:
        s = other_df.set_index("datetime")[col].sort_index()
    else:
        s = other_df[col].sort_index()
    # Make tz-naive UTC for comparison if needed
    if s.index.tz is not None and target_index.tz is None:
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    elif s.index.tz is None and target_index.tz is not None:
        s.index = s.index.tz_localize("UTC")
    return s.reindex(target_index, method="ffill")


def add_cross_asset_features(
    df: pd.DataFrame,
    cross_asset_dfs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Add cross-asset features. Modifies df in place.

    Args:
        df: main symbol df, must have datetime index or 'datetime' column
        cross_asset_dfs: dict like {'XAG/USD': df_xag, 'TLT': df_tlt, ...}
    """
    if df.index.name != "datetime" and "datetime" in df.columns:
        df = df.set_index("datetime")

    main_close = df["close"]

    # Silver
    if "XAG/USD" in cross_asset_dfs:
        xag = _align_to_index(cross_asset_dfs["XAG/USD"], df.index)
        df["xag_corr_20"] = _safe_corr(main_close, xag, 20)
        df["xag_ret_5"] = _safe_returns(xag, 5)
        df["xag_zscore_20"] = _safe_zscore(xag, 20)
    else:
        for c in ["xag_corr_20", "xag_ret_5", "xag_zscore_20"]:
            df[c] = 0.0

    # EURUSD
    if "EUR/USD" in cross_asset_dfs:
        eur = _align_to_index(cross_asset_dfs["EUR/USD"], df.index)
        df["eurusd_corr_20"] = _safe_corr(main_close, eur, 20)
        df["eurusd_ret_5"] = _safe_returns(eur, 5)
    else:
        df["eurusd_corr_20"] = 0.0
        df["eurusd_ret_5"] = 0.0

    # TLT — treasury proxy (gold inverse correlates with real yields)
    if "TLT" in cross_asset_dfs:
        tlt = _align_to_index(cross_asset_dfs["TLT"], df.index)
        df["tlt_ret_20"] = _safe_returns(tlt, 20)
        df["tlt_zscore_60"] = _safe_zscore(tlt, 60)
    else:
        df["tlt_ret_20"] = 0.0
        df["tlt_zscore_60"] = 0.0

    # SPY
    if "SPY" in cross_asset_dfs:
        spy = _align_to_index(cross_asset_dfs["SPY"], df.index)
        df["spy_ret_60"] = _safe_returns(spy, 60)
        df["spy_zscore_60"] = _safe_zscore(spy, 60)
    else:
        df["spy_ret_60"] = 0.0
        df["spy_zscore_60"] = 0.0

    # BTC
    if "BTC/USD" in cross_asset_dfs:
        btc = _align_to_index(cross_asset_dfs["BTC/USD"], df.index)
        df["btc_ret_60"] = _safe_returns(btc, 60)
        df["btc_zscore_60"] = _safe_zscore(btc, 60)
    else:
        df["btc_ret_60"] = 0.0
        df["btc_zscore_60"] = 0.0

    # VIX
    if "VIX" in cross_asset_dfs:
        vix = _align_to_index(cross_asset_dfs["VIX"], df.index)
        df["vix_level"] = vix.fillna(20.0)
        df["vix_zscore_20"] = _safe_zscore(vix, 20)
    else:
        df["vix_level"] = 20.0
        df["vix_zscore_20"] = 0.0

    return df


# ─────────────────────────────────────────────────────────────────────
# MULTI-TF FEATURES
# ─────────────────────────────────────────────────────────────────────

def add_multi_tf_features(
    df: pd.DataFrame,
    higher_tf_dfs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Add features from higher TFs projected onto current df's timestamps.

    Args:
        df: current TF dataframe (typically 5m)
        higher_tf_dfs: dict like {'1h': df_1h, '4h': df_4h, '1d': df_1d}.
            Each df should ALREADY have features computed via compute_features.
    """
    if df.index.name != "datetime" and "datetime" in df.columns:
        df = df.set_index("datetime")

    tf_prefix_map = {"1h": "h1", "4h": "h4", "1d": "d1"}

    for tf_label, tf_df in higher_tf_dfs.items():
        prefix = tf_prefix_map.get(tf_label, tf_label)
        if tf_df is None or len(tf_df) == 0:
            continue
        if "datetime" in tf_df.columns:
            tf_indexed = tf_df.set_index("datetime").sort_index()
        else:
            tf_indexed = tf_df.sort_index()

        # Features to project (must already exist in tf_indexed)
        target_features = {
            "h1": ["rsi", "atr", "above_ema20", "trend_strength",
                   "macd", "volatility_percentile"],
            "h4": ["rsi", "atr", "above_ema20", "trend_strength"],
            "d1": ["rsi", "above_ema20", "trend_strength"],
        }.get(prefix, [])

        for feat in target_features:
            col_name = f"{prefix}_{feat}"
            if feat in tf_indexed.columns:
                projected = tf_indexed[feat].reindex(df.index, method="ffill")
                df[col_name] = projected.fillna(0)
            else:
                df[col_name] = 0.0

    return df


# ─────────────────────────────────────────────────────────────────────
# WAREHOUSE LOADERS
# ─────────────────────────────────────────────────────────────────────

def load_warehouse(symbol: str, interval: str) -> pd.DataFrame | None:
    """Load symbol/interval from data warehouse parquet store."""
    safe_label = symbol.replace("/", "_")
    path = WAREHOUSE_DIR / safe_label / f"{interval}.parquet"
    if not path.exists():
        logger.warning(f"Warehouse miss: {path}")
        return None
    try:
        return pd.read_parquet(path)
    except Exception as e:
        logger.warning(f"Warehouse load error {path}: {e}")
        return None


def load_cross_asset_warehouse(interval: str = "1h") -> dict[str, pd.DataFrame]:
    """Load all cross-asset symbols at given TF from warehouse.

    VIX fallback: if direct VIX unavailable on TwelveData, use VIXY ETF
    (ProShares VIX Short-Term Futures ETF) as proxy. Loaded under "VIX" key
    so downstream code is symbol-agnostic.
    """
    symbols = ["XAG/USD", "EUR/USD", "TLT", "SPY", "BTC/USD", "VIX"]
    result = {}
    for sym in symbols:
        df = load_warehouse(sym, interval)
        if df is not None:
            result[sym] = df
        elif sym == "VIX":
            # Fallback to VIXY ETF
            df = load_warehouse("VIXY", interval)
            if df is not None:
                result["VIX"] = df
                logger.info(f"VIX fallback: using VIXY ETF data ({len(df)} rows)")
    return result


def load_higher_tf_warehouse(symbol: str = "XAU/USD") -> dict[str, pd.DataFrame]:
    """Load higher TFs for the main symbol from warehouse, with features."""
    higher = {}
    for tf in ["1h", "4h", "1day"]:
        df = load_warehouse(symbol, tf)
        if df is not None:
            # Compute features for the higher TF
            try:
                df_with_features = compute_features(df.copy())
                higher[tf if tf != "1day" else "1d"] = df_with_features
            except Exception as e:
                logger.warning(f"Feature compute failed for {symbol} {tf}: {e}")
    return higher


# ─────────────────────────────────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────────────────────────────────

def compute_features_v2(
    df: pd.DataFrame,
    higher_tf_dfs: dict[str, pd.DataFrame] | None = None,
    cross_asset_dfs: dict[str, pd.DataFrame] | None = None,
    usdjpy_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Full v2 feature pipeline:
      1. Run base compute_features (36 features incl. USDJPY+VWAP)
      2. Add cross-asset features (silver, EURUSD, TLT, SPY, BTC, VIX)
      3. Add multi-TF features (1h, 4h, 1d projected onto 5m bars)

    All optional inputs default to "load from data warehouse if available".
    Missing data → feature defaults to 0.0 (graceful degrade).
    """
    if higher_tf_dfs is None:
        higher_tf_dfs = load_higher_tf_warehouse("XAU/USD")
    if cross_asset_dfs is None:
        cross_asset_dfs = load_cross_asset_warehouse("1h")

    # Step 1: base v1 features (this writes to df in place + returns it)
    features = compute_features(df, usdjpy_df=usdjpy_df)

    # Make sure index is datetime for cross-asset alignment
    if "datetime" in features.columns:
        features = features.set_index("datetime")

    # Step 2: cross-asset
    features = add_cross_asset_features(features, cross_asset_dfs)

    # Step 3: multi-TF
    features = add_multi_tf_features(features, higher_tf_dfs)

    # Sanity: make sure all v2 columns present
    for col in ALL_V2_FEATURE_COLS:
        if col not in features.columns:
            features[col] = 0.0

    return features


__all__ = [
    "compute_features_v2",
    "ALL_V2_FEATURE_COLS",
    "CROSS_ASSET_FEATURES",
    "MULTI_TF_FEATURES",
    "load_warehouse",
    "load_cross_asset_warehouse",
    "load_higher_tf_warehouse",
]
