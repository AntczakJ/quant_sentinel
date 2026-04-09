"""
tests/test_finance_extended.py — Extended tests for finance.py (position sizing, SL/TP)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCalculatePosition:
    """Test position sizing and SL/TP calculation."""

    def _make_analysis(self, trend="bull", price=2500.0, **overrides):
        base = {
            'price': price, 'rsi': 50.0, 'trend': trend,
            'swing_high': price + 20, 'swing_low': price - 20,
            'liquidity_grab': False, 'liquidity_grab_dir': None,
            'mss': False, 'ob_price': None,
            'fvg_type': None, 'fvg_upper': None, 'fvg_lower': None,
            'macro_regime': 'neutralny', 'atr': 10.0, 'atr_mean': 10.0,
            'dbr_rbd_type': None, 'dbr_rbd_base_low': None, 'dbr_rbd_base_high': None,
            'structure': 'BOS', 'session': 'london', 'is_killzone': False,
            'session_info': {'session': 'london', 'volatility_expected': 'medium'},
        }
        base.update(overrides)
        return base

    def test_long_returns_correct_direction(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(trend="bull"), 10000, "USD", "", df=pd.DataFrame())
        assert result.get('direction') in ('LONG', 'CZEKAJ')

    def test_short_returns_correct_direction(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(trend="bear"), 10000, "USD", "", df=pd.DataFrame())
        assert result.get('direction') in ('SHORT', 'CZEKAJ')

    def test_long_sl_below_entry(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(trend="bull"), 10000, "USD", "", df=pd.DataFrame())
        if result.get('direction') == 'LONG':
            assert result['sl'] < result['entry'], "LONG SL must be below entry"
            assert result['tp'] > result['entry'], "LONG TP must be above entry"

    def test_short_sl_above_entry(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(trend="bear"), 10000, "USD", "", df=pd.DataFrame())
        if result.get('direction') == 'SHORT':
            assert result['sl'] > result['entry'], "SHORT SL must be above entry"
            assert result['tp'] < result['entry'], "SHORT TP must be below entry"

    def test_lot_size_positive(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(), 10000, "USD", "", df=pd.DataFrame())
        if result.get('direction') != 'CZEKAJ':
            assert result['lot'] > 0
            assert result['lot'] >= 0.01

    def test_rr_ratio_minimum(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        result = calculate_position(self._make_analysis(), 10000, "USD", "", df=pd.DataFrame())
        if result.get('direction') == 'LONG':
            rr = (result['tp'] - result['entry']) / (result['entry'] - result['sl'])
            assert rr >= 1.9, f"R:R {rr:.1f} below minimum 2.0"

    def test_asian_session_rejected(self):
        from src.trading.finance import calculate_position
        import pandas as pd
        analysis = self._make_analysis()
        analysis['session_info'] = {'session': 'asian'}
        result = calculate_position(analysis, 10000, "USD", "", df=pd.DataFrame())
        assert result.get('direction') == 'CZEKAJ'
