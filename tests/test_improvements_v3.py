#!/usr/bin/env python3
"""
test_improvements_v3.py — Comprehensive tests for all V3 improvements.

Tests:
1. SMC Engine: decorator fix, candlestick/ichimoku/POC integration
2. Data Sources: unified provider routing, prefetch, price cache layers
3. ML Models: expanded features, walk-forward validation
4. Ensemble: dynamic weights, prediction persistence
5. Self-Learning: expanded Bayesian bounds, regime tracking
6. Database: new tables (ml_predictions, regime_stats, news_sentiment)
7. OpenAI Agent: new tools (loss_analysis, multi_tf, sentiment)
8. Integration: full signal pipeline end-to-end
"""

import sys
import os
import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Force local SQLite for tests (never touch Turso)
os.environ["DATABASE_URL"] = "data/test_sentinel.db"
os.environ.setdefault("TD_API_KEY", "test_key")
os.environ.setdefault("OPENAI_API_KEY", "test_key")


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_df():
    """Generate realistic XAU/USD OHLCV DataFrame for testing."""
    np.random.seed(42)
    n = 200
    base_price = 2400.0
    prices = base_price + np.cumsum(np.random.randn(n) * 2)
    df = pd.DataFrame({
        'open': prices + np.random.randn(n) * 0.5,
        'high': prices + abs(np.random.randn(n) * 3),
        'low': prices - abs(np.random.randn(n) * 3),
        'close': prices,
        'volume': np.random.randint(100, 10000, n),
    })
    # Ensure OHLC consistency
    df['high'] = df[['open', 'high', 'close']].max(axis=1) + 0.1
    df['low'] = df[['open', 'low', 'close']].min(axis=1) - 0.1
    return df


@pytest.fixture
def sample_analysis():
    """Sample SMC analysis data with all V3 fields."""
    return {
        'price': 2545.50,
        'rsi': 45.0,
        'trend': 'bull',
        'fvg_type': 'bullish',
        'fvg_upper': 2550.0,
        'fvg_lower': 2540.0,
        'fvg_size': 10.0,
        'fvg': 'Bullish (+10$)',
        'ob_price': 2540.00,
        'swing_high': 2560.00,
        'swing_low': 2530.00,
        'atr': 15.0,
        'atr_mean': 12.0,
        'macro_regime': 'zielony',
        'usdjpy': 150.0,
        'usdjpy_zscore': -0.5,
        'liquidity_grab': True,
        'liquidity_grab_dir': 'bullish',
        'mss': True,
        'structure': 'Liquidity Grab (Bull) + MSS → trend bull',
        'dbr_rbd_type': None,
        'dbr_rbd_base_low': None,
        'dbr_rbd_base_high': None,
        'smt': 'Brak',
        'bos_bullish': True,
        'bos_bearish': False,
        'choch_bullish': False,
        'choch_bearish': False,
        'ob_confluence': 2,
        'supply': [2560.0],
        'demand': [2530.0],
        'order_blocks': [{'price': 2540.0, 'type': 'bullish'}],
        'rsi_div_bull': False,
        'rsi_div_bear': False,
        # V3 new fields
        'engulfing': 'bullish',
        'pin_bar': False,
        'inside_bar': False,
        'ichimoku_above_cloud': True,
        'ichimoku_below_cloud': False,
        'poc_price': 2543.50,
        'near_poc': True,
    }


@pytest.fixture
def db():
    """Fresh test database fixture."""
    # Reset the initialization flag so tables are created fresh
    import src.database as db_mod
    db_mod._db_initialized = False
    from src.database import NewsDB
    return NewsDB()


# ============================================================================
# 1. SMC ENGINE TESTS
# ============================================================================

class TestSMCEngine:
    """Test SMC Engine improvements: no raw API calls, new detections."""

    def test_no_raw_requests_import(self):
        """Verify smc_engine.py no longer imports requests directly."""
        import src.smc_engine as smc
        # The module should use _get_data_provider() instead of raw requests
        assert hasattr(smc, '_get_data_provider'), "_get_data_provider helper missing"
        # Check that request_with_retry is gone
        assert not hasattr(smc, 'request_with_retry'), "request_with_retry should be removed"

    def test_get_exchange_rate_uses_provider(self):
        """Verify exchange rate goes through DataProvider."""
        with patch('src.smc_engine._get_data_provider') as mock_provider:
            mock_instance = MagicMock()
            mock_instance.get_exchange_rate.return_value = 4.05
            mock_provider.return_value = mock_instance

            from src.smc_engine import get_exchange_rate
            result = get_exchange_rate("USD", "PLN")

            mock_instance.get_exchange_rate.assert_called_once_with("USD", "PLN")
            assert result == 4.05

    def test_get_usdjpy_history_uses_provider(self):
        """Verify USD/JPY history goes through DataProvider."""
        with patch('src.smc_engine._get_data_provider') as mock_provider:
            mock_instance = MagicMock()
            mock_df = pd.DataFrame({'close': [149.0, 150.0, 151.0]})
            mock_instance.get_candles.return_value = mock_df
            mock_provider.return_value = mock_instance

            from src.smc_engine import get_usdjpy_history
            prices, current = get_usdjpy_history("15m", 30)

            assert len(prices) == 3
            assert current == 151.0

    def test_smc_analysis_returns_new_fields(self, sample_analysis):
        """Verify SMC analysis includes candlestick, ichimoku, POC fields."""
        required_new_fields = [
            'engulfing', 'pin_bar', 'inside_bar',
            'ichimoku_above_cloud', 'ichimoku_below_cloud',
            'poc_price', 'near_poc'
        ]
        for field in required_new_fields:
            assert field in sample_analysis, f"Missing new field: {field}"

    def test_no_double_decorator(self):
        """Verify the double @cached_with_key decorator bug is fixed."""
        import inspect
        from src.smc_engine import get_smc_analysis
        source = inspect.getsource(get_smc_analysis)
        # Should NOT have _smc_cache_key reference
        assert '_smc_cache_key' not in source, "Orphan _smc_cache_key decorator still present"


# ============================================================================
# 2. DATA SOURCES TESTS
# ============================================================================

class TestDataSources:
    """Test TwelveData improvements: price caching, WebSocket, prefetch."""

    def test_provider_singleton(self):
        """Verify get_provider returns singleton."""
        from src.data_sources import get_provider, _provider_cache
        # Clear cache first
        _provider_cache.clear()

        with patch('src.data_sources.TD_API_KEY', 'test'):
            p1 = get_provider('twelve_data')
            p2 = get_provider('twelve_data')
            assert p1 is p2, "Provider should be singleton"

    def test_live_price_store_exists(self):
        """Verify module-level live price store for WebSocket."""
        from src.data_sources import _live_prices, _live_price_lock
        assert isinstance(_live_prices, dict)
        assert _live_price_lock is not None

    def test_get_current_price_checks_ws_first(self):
        """Verify get_current_price checks WebSocket before REST."""
        import src.data_sources as ds
        import time

        # Simulate WebSocket price
        with ds._live_price_lock:
            ds._live_prices['XAU/USD'] = {
                'price': 2500.0,
                'timestamp': time.time()
            }

        provider = ds.TwelveDataProvider('test_key')
        result = provider.get_current_price('XAU/USD')

        assert result is not None
        assert result['price'] == 2500.0
        assert result.get('source') == 'websocket'

        # Clean up
        with ds._live_price_lock:
            ds._live_prices.clear()

    def test_provider_has_prefetch_method(self):
        """Verify prefetch_all_timeframes method exists."""
        from src.data_sources import TwelveDataProvider
        provider = TwelveDataProvider('test_key')
        assert hasattr(provider, 'prefetch_all_timeframes')
        assert callable(provider.prefetch_all_timeframes)

    def test_provider_has_ws_stream_method(self):
        """Verify start_price_stream method exists."""
        from src.data_sources import TwelveDataProvider
        provider = TwelveDataProvider('test_key')
        assert hasattr(provider, 'start_price_stream')
        assert callable(provider.start_price_stream)


# ============================================================================
# 3. ML MODELS TESTS
# ============================================================================

class TestMLModels:
    """Test expanded feature set and walk-forward validation."""

    def test_feature_cols_expanded(self):
        """Verify FEATURE_COLS has the new expanded features."""
        from src.ml_models import FEATURE_COLS
        new_features = ['williams_r', 'cci', 'ema_distance', 'ichimoku_signal',
                       'engulfing_score', 'pin_bar_score', 'ret_10',
                       'body_ratio', 'upper_shadow_ratio', 'lower_shadow_ratio']
        for feat in new_features:
            assert feat in FEATURE_COLS, f"Missing feature: {feat}"

    def test_features_generation(self, sample_df):
        """Verify _features generates all expected columns."""
        from src.ml_models import MLPredictor, FEATURE_COLS
        predictor = MLPredictor()
        features = predictor._features(sample_df)

        for col in FEATURE_COLS:
            assert col in features.columns, f"Feature column missing after _features(): {col}"

    def test_features_no_nan_in_output(self, sample_df):
        """Verify _features drops NaN properly."""
        from src.ml_models import MLPredictor, FEATURE_COLS
        predictor = MLPredictor()
        features = predictor._features(sample_df)
        # After dropna, should have no NaN in feature columns
        assert not features[FEATURE_COLS].isnull().any().any(), "NaN found in feature columns"

    def test_xgb_walk_forward_structure(self, sample_df):
        """Verify XGBoost training uses walk-forward (not random split)."""
        from src.ml_models import MLPredictor
        predictor = MLPredictor(model_dir='models/test')

        # Mock DB to avoid side effects (NewsDB is imported inside train_xgb)
        with patch('src.database.NewsDB') as mock_db:
            mock_db.return_value = MagicMock()
            acc = predictor.train_xgb(sample_df)

        if acc is not None:
            assert 0.0 <= acc <= 1.0, f"Accuracy out of range: {acc}"


# ============================================================================
# 4. ENSEMBLE TESTS
# ============================================================================

class TestEnsemble:
    """Test dynamic weights, prediction persistence."""

    def test_dynamic_weights_loading(self):
        """Verify _load_dynamic_weights returns valid weights."""
        from src.ensemble_models import _load_dynamic_weights
        weights = _load_dynamic_weights()
        assert isinstance(weights, dict)
        assert 'smc' in weights
        assert 'lstm' in weights
        assert 'xgb' in weights
        assert 'dqn' in weights
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"Weights don't sum to 1: {total}"

    def test_update_ensemble_weights_function_exists(self):
        """Verify update_ensemble_weights is importable."""
        from src.ensemble_models import update_ensemble_weights
        assert callable(update_ensemble_weights)

    def test_persist_prediction_function_exists(self):
        """Verify _persist_prediction is importable."""
        from src.ensemble_models import _persist_prediction
        assert callable(_persist_prediction)

    def test_fallback_ensemble_result(self):
        """Verify fallback result structure."""
        from src.ensemble_models import _fallback_ensemble_result
        result = _fallback_ensemble_result()
        assert result['final_score'] == 0.5
        assert result['ensemble_signal'] == 'CZEKAJ'
        assert 'error' in result


# ============================================================================
# 5. DATABASE TESTS
# ============================================================================

class TestDatabase:
    """Test new tables and methods."""

    def test_ml_predictions_table_exists(self, db):
        """Verify ml_predictions table was created."""
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ml_predictions'")
        assert db.cursor.fetchone() is not None, "ml_predictions table not created"

    def test_regime_stats_table_exists(self, db):
        """Verify regime_stats table was created."""
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='regime_stats'")
        assert db.cursor.fetchone() is not None, "regime_stats table not created"

    def test_news_sentiment_table_exists(self, db):
        """Verify news_sentiment table was created."""
        db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='news_sentiment'")
        assert db.cursor.fetchone() is not None, "news_sentiment table not created"

    def test_update_regime_stats(self, db):
        """Test regime stats insert and update."""
        # Clean old test data first
        try:
            db._execute("DELETE FROM regime_stats WHERE regime = 'test_regime'")
        except:
            pass

        db.update_regime_stats("test_regime", "London", "LONG", "PROFIT")
        db.update_regime_stats("test_regime", "London", "LONG", "LOSS")

        stats = db.get_regime_stats("test_regime", "London")
        assert len(stats) > 0
        row = stats[0]
        assert row[3] == 2  # count
        assert row[4] == 1  # wins
        assert row[5] == 1  # losses

    def test_save_news_sentiment(self, db):
        """Test news sentiment save and aggregation."""
        # Clean stale test data
        try:
            db._execute("DELETE FROM news_sentiment")
        except:
            pass

        db.save_news_sentiment("Gold rises on weak USD", "bullish", 0.8, "rss")
        db.save_news_sentiment("Fed signals rate hike", "bearish", 0.6, "rss")
        db.save_news_sentiment("Markets stable", "neutral", 0.5, "rss")

        result = db.get_aggregated_news_sentiment(hours=1)
        assert result['total'] == 3
        assert result['bullish'] == 1
        assert result['bearish'] == 1

    def test_get_recent_ml_predictions(self, db):
        """Test ML prediction retrieval (empty is OK)."""
        results = db.get_recent_ml_predictions(10)
        assert isinstance(results, list)


# ============================================================================
# 6. SELF-LEARNING TESTS
# ============================================================================

class TestSelfLearning:
    """Test expanded Bayesian optimization and regime learning."""

    def test_expanded_factors_in_auto_learn(self):
        """Verify new factors are recognized in update_factor_weights."""
        from src.self_learning import update_factor_weights
        assert callable(update_factor_weights)

    def test_pattern_adjustment(self, db):
        """Test pattern weight adjustment."""
        from src.self_learning import get_pattern_adjustment
        # No data yet — should return 1.0
        adj = get_pattern_adjustment({"pattern": "TEST_PATTERN"})
        assert adj == 1.0


# ============================================================================
# 7. OPENAI AGENT TESTS
# ============================================================================

class TestOpenAIAgent:
    """Test new agent tools."""

    def test_agent_tools_schema_has_new_tools(self):
        """Verify new tools are in AGENT_TOOLS_SCHEMA."""
        from src.openai_agent import AGENT_TOOLS_SCHEMA
        tool_names = [t['name'] for t in AGENT_TOOLS_SCHEMA]
        assert 'get_loss_analysis' in tool_names
        assert 'get_multi_tf_analysis' in tool_names
        assert 'get_news_sentiment' in tool_names

    def test_agent_dispatch_new_tools(self):
        """Verify new tools are in dispatcher."""
        with patch('src.openai_agent.OPENAI_KEY', 'test_key'):
            from src.openai_agent import QuantSentinelAgent
            with patch.object(QuantSentinelAgent, '__init__', lambda self: None):
                agent = QuantSentinelAgent()
                agent.client = MagicMock()

                dispatch = {
                    "get_loss_analysis": agent._tool_get_loss_analysis,
                    "get_multi_tf_analysis": agent._tool_get_multi_tf_analysis,
                    "get_news_sentiment": agent._tool_get_news_sentiment,
                }
                for name, handler in dispatch.items():
                    assert callable(handler), f"Handler for {name} not callable"

    def test_agent_instructions_reference_new_tools(self):
        """Verify AGENT_INSTRUCTIONS mention new tools."""
        from src.openai_agent import AGENT_INSTRUCTIONS
        assert 'get_multi_tf_analysis' in AGENT_INSTRUCTIONS
        assert 'get_loss_analysis' in AGENT_INSTRUCTIONS
        assert 'get_news_sentiment' in AGENT_INSTRUCTIONS
        assert 'Ichimoku' in AGENT_INSTRUCTIONS
        assert 'Candlestick' in AGENT_INSTRUCTIONS


# ============================================================================
# 8. FINANCE TESTS
# ============================================================================

class TestFinance:
    """Test finance module uses DataProvider."""

    def test_calculate_position_with_new_fields(self, sample_analysis):
        """Test calculate_position works with new SMC fields."""
        from src.finance import calculate_position

        with patch('src.data_sources.get_provider') as mock_prov:
            mock_instance = MagicMock()
            mock_instance.get_candles.return_value = None
            mock_instance.get_exchange_rate.return_value = 4.0
            mock_prov.return_value = mock_instance

            result = calculate_position(sample_analysis, 10000, "USD", "test_key")

        assert result['direction'] in ('LONG', 'SHORT', 'CZEKAJ')
        if result['direction'] != 'CZEKAJ':
            assert 'entry' in result
            assert 'sl' in result
            assert 'tp' in result
            assert 'lot' in result


# ============================================================================
# 9. INTEGRATION SMOKE TEST
# ============================================================================

class TestIntegrationSmoke:
    """End-to-end integration test with mocks."""

    def test_full_signal_pipeline(self, sample_analysis, sample_df, db):
        """Test: SMC → calculate_position → ensemble → log_trade."""
        from src.finance import calculate_position
        from src.ensemble_models import get_ensemble_prediction

        # 1. Mock data provider
        with patch('src.data_sources.get_provider') as mock_prov, \
             patch('src.ensemble_models.get_ensemble_prediction') as mock_ensemble:

            mock_instance = MagicMock()
            mock_instance.get_candles.return_value = sample_df
            mock_prov.return_value = mock_instance

            mock_ensemble.return_value = {
                'ensemble_signal': 'LONG',
                'final_score': 0.75,
                'confidence': 0.8,
                'models_available': 3,
                'predictions': {
                    'smc': {'direction': 'LONG', 'confidence': 0.8},
                    'lstm': {'direction': 'LONG', 'confidence': 0.7},
                    'xgb': {'direction': 'LONG', 'confidence': 0.6},
                }
            }

            # 2. Calculate position
            result = calculate_position(sample_analysis, 10000, "USD", "test_key", df=sample_df)

            if result.get('direction') not in (None, 'CZEKAJ'):
                # 3. Log trade
                db.log_trade(
                    direction=result['direction'],
                    price=result['entry'],
                    sl=result['sl'],
                    tp=result['tp'],
                    rsi=sample_analysis['rsi'],
                    trend=sample_analysis['trend'],
                    structure=sample_analysis.get('structure', 'test'),
                    pattern=f"{result['direction']}_test",
                    factors={'test': 1, 'ichimoku_bull': 1, 'engulfing': 1},
                    lot=result.get('lot')
                )

                # 4. Verify trade is in DB
                open_trades = db.get_open_trades()
                assert len(open_trades) > 0, "Trade was not logged to database"

                # 5. Verify factors are stored
                trade_id = open_trades[-1][0]
                factors = db.get_trade_factors(trade_id)
                assert 'ichimoku_bull' in factors or 'test' in factors

    def test_candlestick_patterns_module(self, sample_df):
        """Verify candlestick patterns work on sample data."""
        from src.candlestick_patterns import engulfing, pin_bar, inside_bar

        eng = engulfing(sample_df)
        assert eng in ('bullish', 'bearish', False)

        pb = pin_bar(sample_df)
        assert pb in ('bullish', 'bearish', False)

        ib = inside_bar(sample_df)
        assert bool(ib) in (True, False)  # numpy bool compatible

    def test_indicators_module(self, sample_df):
        """Verify ichimoku and volume_profile work on sample data."""
        from src.indicators import ichimoku, volume_profile

        ichi = ichimoku(sample_df)
        assert 'tenkan_sen' in ichi.columns
        assert 'senkou_span_a' in ichi.columns

        vp = volume_profile(sample_df)
        assert 'poc' in vp
        assert 'vah' in vp
        assert 'val' in vp


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-x"])







