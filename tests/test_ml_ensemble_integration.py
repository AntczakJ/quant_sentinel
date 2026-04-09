"""
test_ml_ensemble_integration.py — Test integracji ensemble ML z systemem.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from src.logger import logger
from src.ensemble_models import (
    get_ensemble_prediction,
    predict_lstm_direction,
    predict_xgb_direction,
    predict_dqn_action
)

def test_individual_models():
    """Test indywidualnych modeli ML."""
    logger.info("="*60)
    logger.info("TEST 1: Indywidualne modele ML")
    logger.info("="*60)

    # Utwórz dummy data
    n = 100
    prices = 2000 + np.cumsum(np.random.randn(n) * 2)
    df = pd.DataFrame({
        'open': prices + np.random.randn(n) * 0.5,
        'high': prices + abs(np.random.randn(n) * 1.0),
        'low': prices - abs(np.random.randn(n) * 1.0),
        'close': prices,
        'volume': np.random.randint(1000, 5000, n)
    })

    # Test LSTM
    logger.info("\n🧠 Testing LSTM...")
    lstm_pred = predict_lstm_direction(df)
    if lstm_pred is not None:
        logger.info(f"✅ LSTM Prediction: {lstm_pred:.4f} ({('LONG' if lstm_pred > 0.5 else 'SHORT')})")
    else:
        logger.warning("⚠️ LSTM not available (expected if model not trained)")

    # Test XGBoost
    logger.info("\n🌲 Testing XGBoost...")
    xgb_pred = predict_xgb_direction(df)
    if xgb_pred is not None:
        logger.info(f"✅ XGBoost Prediction: {xgb_pred:.4f} ({('LONG' if xgb_pred > 0.5 else 'SHORT')})")
    else:
        logger.warning("⚠️ XGBoost not available (expected if model not trained)")

    # Test DQN
    logger.info("\n🤖 Testing DQN...")
    close_prices = df['close'].values[-20:]
    dqn_result = predict_dqn_action(close_prices, balance=1.0, position=0)
    if dqn_result is not None:
        action = dqn_result.get('action', 0) if isinstance(dqn_result, dict) else dqn_result
        action_names = {0: "HOLD", 1: "BUY", 2: "SELL"}
        logger.info(f"DQN Action: {action_names.get(action, 'UNKNOWN')} ({dqn_result})")
    else:
        logger.warning("DQN not available (expected if model not trained)")


def test_ensemble():
    """Test ensemble voting z live data z Twelve Data."""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Ensemble Voting (with Twelve Data)")
    logger.info("="*60)

    logger.info("\n🤖 Running ensemble prediction with auto-fetch from Twelve Data...")
    try:
        # Nie podajemy df - powinien pobrać z Twelve Data
        ensemble = get_ensemble_prediction(
            df=None,  # ← Auto-fetch z Twelve Data!
            smc_trend="bull",
            current_price=2050.5,
            balance=10000,
            initial_balance=10000,
            position=0,
            symbol="XAU/USD",
            timeframe="15m",
            use_twelve_data=True
        )

        logger.info(f"✅ Ensemble Signal: {ensemble['ensemble_signal']}")
        logger.info(f"   Final Score: {ensemble['final_score']:.4f}")
        logger.info(f"   Confidence: {ensemble['confidence']:.1%}")
        logger.info(f"   Models Available: {ensemble['models_available']}")

        logger.info("\n📊 Individual Predictions:")
        for model, pred in ensemble['predictions'].items():
            status = pred.get('status', 'ok')
            if status != 'ok':
                logger.info(f"   {model.upper()}: {status}")
            else:
                logger.info(f"   {model.upper()}: {pred['direction']} (confidence: {pred['confidence']:.0%})")

        logger.info("\n⚖️  Weights:")
        for model, weight in ensemble['weights'].items():
            logger.info(f"   {model.upper()}: {weight:.0%}")

    except Exception as e:
        logger.error(f"❌ Ensemble test failed: {e}", exc_info=True)
        raise


def test_conflicting_signals():
    """Test scenariusza gdzie modele się nie zgadzają."""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Conflicting Signals (SMC Bull vs ML Bear)")
    logger.info("="*60)

    # Utwórz bear trend data (ceny spadają)
    n = 200
    prices = 2000 - np.cumsum(abs(np.random.randn(n) * 2))  # Downtrend
    df = pd.DataFrame({
        'open': prices + np.random.randn(n) * 0.5,
        'high': prices + abs(np.random.randn(n) * 1.0),
        'low': prices - abs(np.random.randn(n) * 1.0),
        'close': prices,
        'volume': np.random.randint(1000, 5000, n)
    })

    # Ensemble says bear, but SMC says bull
    logger.info("\n🤖 Running ensemble on bearish data (but SMC says BULL)...")
    ensemble = get_ensemble_prediction(
        df=df,
        smc_trend="bull",  # ← SMC Bull
        current_price=prices[-1],
        balance=10000,
        initial_balance=10000,
        position=0
    )

    logger.info(f"✅ SMC: BULL vs ML Ensemble: {ensemble['ensemble_signal']}")
    logger.info(f"   Final Score: {ensemble['final_score']:.4f}")
    logger.info(f"   Confidence: {ensemble['confidence']:.1%}")

    if abs(ensemble['final_score'] - 0.5) < 0.15:
        logger.warning("⚠️  Low confidence - conflicting signals detected")


def test_low_confidence():
    """Test scenariusza niskiej pewności."""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Low Confidence (Neutral Market)")
    logger.info("="*60)

    # Utwórz sideways data
    n = 200
    prices = 2000 + np.random.randn(n) * 5  # Sideways market
    df = pd.DataFrame({
        'open': prices + np.random.randn(n) * 0.5,
        'high': prices + abs(np.random.randn(n) * 1.0),
        'low': prices - abs(np.random.randn(n) * 1.0),
        'close': prices,
        'volume': np.random.randint(1000, 5000, n)
    })

    logger.info("\n🤖 Running ensemble on sideways market...")
    ensemble = get_ensemble_prediction(
        df=df,
        smc_trend="bull",
        current_price=prices[-1],
        balance=10000,
        initial_balance=10000,
        position=0
    )

    logger.info(f"✅ Ensemble Signal: {ensemble['ensemble_signal']}")
    logger.info(f"   Final Score: {ensemble['final_score']:.4f}")
    logger.info(f"   Confidence: {ensemble['confidence']:.1%}")

    if ensemble['confidence'] < 0.4:
        logger.warning("⚠️  Low confidence - CZEKAJ signal appropriate for neutral market")


def test_different_weights():
    """Test z różnymi wagami."""
    logger.info("\n" + "="*60)
    logger.info("TEST 5: Custom Weights")
    logger.info("="*60)

    # Utwórz dummy data
    n = 200
    prices = 2000 + np.cumsum(np.random.randn(n) * 2)
    df = pd.DataFrame({
        'open': prices + np.random.randn(n) * 0.5,
        'high': prices + abs(np.random.randn(n) * 1.0),
        'low': prices - abs(np.random.randn(n) * 1.0),
        'close': prices,
        'volume': np.random.randint(1000, 5000, n)
    })

    # Test z różnymi wagami
    weights_configs = [
        {"name": "SMC-Heavy", "weights": {"smc": 0.50, "lstm": 0.20, "xgb": 0.15, "dqn": 0.15}},
        {"name": "ML-Heavy", "weights": {"smc": 0.20, "lstm": 0.30, "xgb": 0.30, "dqn": 0.20}},
        {"name": "Balanced", "weights": {"smc": 0.35, "lstm": 0.25, "xgb": 0.20, "dqn": 0.20}},
    ]

    for config in weights_configs:
        logger.info(f"\n🎯 Testing with {config['name']} weights:")
        ensemble = get_ensemble_prediction(
            df=df,
            smc_trend="bull",
            current_price=prices[-1],
            balance=10000,
            initial_balance=10000,
            position=0,
            weights=config['weights']
        )
        logger.info(f"   Signal: {ensemble['ensemble_signal']} | Score: {ensemble['final_score']:.4f}")


if __name__ == "__main__":
    logger.info("\n\n" + "█"*60)
    logger.info("█ ML ENSEMBLE INTEGRATION TESTS")
    logger.info("█"*60 + "\n")

    try:
        test_individual_models()
        test_ensemble()
        test_conflicting_signals()
        test_low_confidence()
        test_different_weights()

        logger.info("\n\n" + "█"*60)
        logger.info("✅ ALL TESTS COMPLETED")
        logger.info("█"*60 + "\n")

    except Exception as e:
        logger.error(f"❌ TEST FAILED: {e}", exc_info=True)
        sys.exit(1)

