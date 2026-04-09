"""
tests/test_macro_data.py — Tests for macro data sources (FRED, seasonality, COT, GPR, events)
"""

import pytest
import sys
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSeasonality:
    def test_returns_valid_signal(self):
        from src.macro_data import get_seasonality_signal
        s = get_seasonality_signal()
        assert "month" in s
        assert "day_of_week" in s
        assert "combined_signal" in s
        assert s["combined_signal"] in (-1, 0, 1)

    def test_month_bias_table_complete(self):
        from src.macro_data import _MONTH_BIAS
        assert len(_MONTH_BIAS) == 12
        for m in range(1, 13):
            assert m in _MONTH_BIAS

    def test_dow_bias_table_complete(self):
        from src.macro_data import _DOW_BIAS
        assert len(_DOW_BIAS) == 7
        for d in range(7):
            assert d in _DOW_BIAS


class TestFredData:
    def test_returns_dict_with_composite(self):
        from src.macro_data import get_fred_data
        result = get_fred_data()
        assert isinstance(result, dict)
        assert "composite_signal" in result

    def test_composite_signal_valid_range(self):
        from src.macro_data import get_fred_data
        result = get_fred_data()
        assert result["composite_signal"] in (-1, 0, 1)


class TestFullMacroSignal:
    def test_returns_all_fields(self):
        from src.macro_data import get_full_macro_signal
        result = get_full_macro_signal()
        assert "composite_signal" in result
        assert "composite_text" in result
        assert "bullish_count" in result
        assert "bearish_count" in result
        assert "fred" in result
        assert "seasonality" in result

    def test_composite_consistent(self):
        from src.macro_data import get_full_macro_signal
        r = get_full_macro_signal()
        if r["bullish_count"] > r["bearish_count"]:
            assert r["composite_signal"] == -1
        elif r["bearish_count"] > r["bullish_count"]:
            assert r["composite_signal"] == 1


class TestCotData:
    def test_returns_dict_or_none(self):
        from src.cot_data import get_gold_cot_signal
        result = get_gold_cot_signal()
        if result is not None:
            assert "spec_net" in result
            assert "signal" in result
            assert result["signal"] in (-1, 0, 1)


class TestGprIndex:
    def test_returns_dict_with_signal(self):
        from src.gpr_index import get_gpr_signal
        result = get_gpr_signal()
        assert isinstance(result, dict)
        assert "signal" in result
        assert result["signal"] in (-1, 0, 1)


class TestEventReactions:
    def test_returns_event_data(self):
        from src.event_reactions import get_event_bias
        result = get_event_bias("CPI")
        assert isinstance(result, dict)

    def test_all_events(self):
        from src.event_reactions import get_all_event_biases
        result = get_all_event_biases()
        assert "CPI" in result
        assert "FOMC" in result
        assert "NFP" in result
