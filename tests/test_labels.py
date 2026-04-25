"""Tests for labels (triple-barrier + R-multiple + binary)."""
import numpy as np
import pandas as pd
import pytest

from src.learning.labels import triple_barrier_labels, r_multiple_labels, binary_labels


def _make_df(close, atr=2.0):
    n = len(close)
    return pd.DataFrame({
        "close": close,
        "high": np.array(close) + 0.5,
        "low": np.array(close) - 0.5,
        "atr": np.full(n, atr),
    })


class TestTripleBarrier:
    def test_long_clean_uptrend_hits_tp(self):
        # Steady uptrend +1/bar, ATR=2 → TP at +4 should hit at bar 4
        close = list(range(2400, 2450))
        df = _make_df(close, atr=2.0)
        # Make highs touch TP
        df["high"] = df["close"] + 4.0
        df["low"] = df["close"] - 0.5
        result = triple_barrier_labels(df, "long", tp_atr=2.0, sl_atr=1.0,
                                       max_horizon_bars=10)
        # Bar 0 entry at 2400, TP=2404. high[1]=2405. Should label 1.
        assert result["label"].iloc[0] == 1

    def test_long_clean_downtrend_hits_sl(self):
        close = list(range(2400, 2350, -1))
        df = _make_df(close, atr=2.0)
        df["low"] = df["close"] - 4.0
        df["high"] = df["close"] + 0.5
        result = triple_barrier_labels(df, "long", tp_atr=2.0, sl_atr=1.0,
                                       max_horizon_bars=10)
        assert result["label"].iloc[0] == -1

    def test_short_clean_downtrend_hits_tp(self):
        close = list(range(2400, 2350, -1))
        df = _make_df(close, atr=2.0)
        df["low"] = df["close"] - 4.0
        df["high"] = df["close"] + 0.5
        result = triple_barrier_labels(df, "short", tp_atr=2.0, sl_atr=1.0,
                                       max_horizon_bars=10)
        # SHORT: TP is below entry. close[1] is lower → low[1] should hit TP
        assert result["label"].iloc[0] == 1

    def test_time_barrier_returns_zero(self):
        # Sideways → neither TP nor SL — should be 0
        close = [2400.0] * 50
        df = _make_df(close, atr=2.0)
        result = triple_barrier_labels(df, "long", tp_atr=2.0, sl_atr=1.0,
                                       max_horizon_bars=10)
        assert result["label"].iloc[0] == 0

    def test_zero_atr_handled(self):
        df = _make_df([2400.0] * 5, atr=0.0)
        result = triple_barrier_labels(df, "long")
        assert all(result["label"] == 0)

    def test_both_direction_returns_combined(self):
        df = _make_df(list(range(2400, 2450)))
        result = triple_barrier_labels(df, "both")
        assert "label_long" in result.columns
        assert "label_short" in result.columns


class TestRMultiple:
    def test_winning_long_positive_r(self):
        # Strong uptrend, ATR=2, SL_R=1, holds for full horizon
        close = [2400 + i * 0.5 for i in range(50)]
        df = _make_df(close, atr=2.0)
        df["high"] = df["close"] + 0.5
        df["low"] = df["close"] - 0.5  # never hits SL
        result = r_multiple_labels(df, "long", sl_atr=1.0, max_horizon_bars=20)
        # After 20 bars, price moved +10 → r_realized = +10/2 = 5.0
        assert result["r_realized"].iloc[0] > 0
        assert result["r_mfe"].iloc[0] > 0
        # MAE should be small/zero (no adverse excursion)
        assert result["r_mae"].iloc[0] >= -0.5

    def test_losing_long_returns_minus_one(self):
        # Drop fast, hit SL
        close = [2400 - i * 1.0 for i in range(20)]
        df = _make_df(close, atr=2.0)
        df["low"] = df["close"] - 4.0  # ensures SL hit
        df["high"] = df["close"] + 0.5
        result = r_multiple_labels(df, "long", sl_atr=1.0, max_horizon_bars=10)
        assert result["r_realized"].iloc[0] == -1.0
        assert result["bars_to_sl"].iloc[0] > 0

    def test_short_winning(self):
        close = [2400 - i * 0.5 for i in range(50)]
        df = _make_df(close, atr=2.0)
        df["high"] = df["close"] + 0.5  # no SL hit (above entry)
        df["low"] = df["close"] - 0.5
        result = r_multiple_labels(df, "short", sl_atr=1.0, max_horizon_bars=20)
        assert result["r_realized"].iloc[0] > 0


class TestBinary:
    def test_long_uptrend_labels_1(self):
        close = list(range(2400, 2450))
        df = _make_df(close, atr=2.0)
        df["high"] = df["close"] + 2.0  # ensures threshold_atr=0.5 hit (1.0 above entry)
        labels = binary_labels(df, "long", horizon_bars=5, threshold_atr=0.5)
        assert labels.iloc[0] == 1

    def test_long_downtrend_labels_0(self):
        close = list(range(2400, 2350, -1))
        df = _make_df(close, atr=2.0)
        df["high"] = df["close"] + 0.1
        labels = binary_labels(df, "long", horizon_bars=5, threshold_atr=0.5)
        assert labels.iloc[0] == 0

    def test_short_downtrend_labels_1(self):
        close = list(range(2400, 2350, -1))
        df = _make_df(close, atr=2.0)
        df["low"] = df["close"] - 2.0
        labels = binary_labels(df, "short", horizon_bars=5, threshold_atr=0.5)
        assert labels.iloc[0] == 1
