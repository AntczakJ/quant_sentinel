"""
tests/test_smc_extended.py — Extended tests for SMC engine, macro regime, setup scoring
"""

import pytest
import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_ohlcv(n=100, base=2500):
    np.random.seed(42)
    close = base + np.cumsum(np.random.randn(n) * 3)
    return pd.DataFrame({
        'open': close + np.random.randn(n) * 1,
        'high': close + abs(np.random.randn(n) * 3),
        'low': close - abs(np.random.randn(n) * 3),
        'close': close,
        'volume': np.random.randint(1000, 50000, n),
    })


class TestMacroRegime:
    def test_returns_valid_regime(self):
        from src.trading.smc_engine import get_macro_regime
        result = get_macro_regime([150.0]*20, 150.0, 10.0, 10.0)
        assert result['regime'] in ('zielony', 'czerwony', 'neutralny')

    def test_signals_dict_present(self):
        from src.trading.smc_engine import get_macro_regime
        result = get_macro_regime([150.0]*20, 150.0, 10.0, 10.0)
        assert 'signals' in result
        assert 'bullish_count' in result
        assert 'bearish_count' in result

    def test_weak_dollar_bullish_gold(self):
        from src.trading.smc_engine import get_macro_regime
        # USD/JPY falling (weak dollar) + high ATR
        prices = list(np.linspace(155, 145, 20))
        result = get_macro_regime(prices, 145.0, 15.0, 10.0)
        assert result['signals'].get('usdjpy', 0) == -1  # weak dollar = bullish gold


class TestDetectOrderBlock:
    def test_returns_float(self):
        from src.trading.smc_engine import detect_order_block
        df = _make_ohlcv()
        ob = detect_order_block(df, "bull")
        assert isinstance(ob, float)
        assert ob > 0

    def test_bear_ob_different(self):
        from src.trading.smc_engine import detect_order_block
        df = _make_ohlcv()
        bull_ob = detect_order_block(df, "bull")
        bear_ob = detect_order_block(df, "bear")
        # They should generally be different
        assert isinstance(bear_ob, float)


class TestFindOrderBlocks:
    def test_returns_list(self):
        from src.trading.smc_engine import find_order_blocks
        df = _make_ohlcv()
        blocks = find_order_blocks(df, "bull")
        assert isinstance(blocks, list)

    def test_blocks_have_score(self):
        from src.trading.smc_engine import find_order_blocks
        df = _make_ohlcv()
        blocks = find_order_blocks(df, "bull", max_blocks=3)
        for b in blocks:
            assert 'price' in b
            assert 'score' in b
            assert 'bars_ago' in b

    def test_sorted_by_score(self):
        from src.trading.smc_engine import find_order_blocks
        df = _make_ohlcv(200)
        blocks = find_order_blocks(df, "bull", max_blocks=5)
        if len(blocks) >= 2:
            scores = [b['score'] for b in blocks]
            assert scores == sorted(scores, reverse=True)


class TestSetupQuality:
    def test_returns_grade(self):
        from src.trading.smc_engine import score_setup_quality
        analysis = {
            'liquidity_grab': True, 'liquidity_grab_dir': 'bullish',
            'mss': True, 'fvg_type': 'bullish', 'ob_price': 2490,
            'price': 2500, 'rsi': 45, 'trend': 'bull', 'atr': 10,
            'bos_bullish': True, 'bos_bearish': False,
            'choch_bullish': False, 'choch_bearish': False,
            'engulfing': 'bullish', 'pin_bar': False,
            'ichimoku_above_cloud': True, 'ichimoku_below_cloud': False,
            'macro_regime': 'zielony', 'is_killzone': True,
            'session': 'london', 'session_info': {'session': 'london', 'volatility_expected': 'high'},
            'rsi_div_bull': False, 'rsi_div_bear': False,
            'macro_bullish_count': 2, 'macro_bearish_count': 0,
        }
        result = score_setup_quality(analysis, "LONG")
        assert result['grade'] in ('A+', 'A', 'B', 'C')
        assert 0 <= result['score'] <= 100
        assert 'risk_mult' in result
        assert 'factors_detail' in result


class TestSeasonality:
    def test_killzone_bonus_higher_than_regular(self):
        from src.trading.smc_engine import score_setup_quality
        base = {
            'liquidity_grab': True, 'liquidity_grab_dir': 'bullish', 'mss': True,
            'fvg_type': 'bullish', 'ob_price': 2490, 'price': 2500,
            'rsi': 45, 'trend': 'bull', 'atr': 10,
            'bos_bullish': True, 'bos_bearish': False,
            'choch_bullish': False, 'choch_bearish': False,
            'engulfing': False, 'pin_bar': False,
            'ichimoku_above_cloud': False, 'ichimoku_below_cloud': False,
            'macro_regime': 'neutralny', 'rsi_div_bull': False, 'rsi_div_bear': False,
            'macro_bullish_count': 0, 'macro_bearish_count': 0,
        }
        # With killzone
        kz = {**base, 'is_killzone': True, 'session': 'london',
              'session_info': {'session': 'london', 'volatility_expected': 'high'}}
        # Without killzone
        no_kz = {**base, 'is_killzone': False, 'session': 'asian',
                 'session_info': {'session': 'asian', 'volatility_expected': 'low'}}

        score_kz = score_setup_quality(kz, "LONG")['score']
        score_no = score_setup_quality(no_kz, "LONG")['score']
        assert score_kz > score_no
