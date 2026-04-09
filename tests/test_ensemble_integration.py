"""
test_ensemble_integration.py — Integration tests for ensemble voting system

Tests to verify:
1. Ensemble voter combines predictions correctly
2. Weights are applied properly
3. Confidence scores are accurate
4. Feature engineering integration works
"""

import sys
import os
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ensemble_voting import EnsembleVoter, ensemble_stacking
from src.feature_engineering import add_advanced_features
from src.logger import logger

def test_ensemble_voter_basic():
    """Test basic ensemble voting"""
    voter = EnsembleVoter()

    # Test case 1: All models agree on BUY
    decision, confidence, details = voter.vote(0.75, 0.72, 1)
    assert decision == "LONG", f"Expected LONG, got {decision}"
    assert confidence > 0.6, f"Expected high confidence, got {confidence}"
    print(f"✅ Test 1 PASSED: Ensemble correctly votes LONG with {confidence:.2%} confidence")

    # Test case 2: All models agree on SELL
    decision, confidence, details = voter.vote(0.25, 0.28, 2)
    assert decision == "SHORT", f"Expected SHORT, got {decision}"
    assert confidence > 0.6, f"Expected high confidence, got {confidence}"
    print(f"✅ Test 2 PASSED: Ensemble correctly votes SHORT with {confidence:.2%} confidence")

    # Test case 3: Models disagree - HOLD
    decision, confidence, details = voter.vote(0.55, 0.45, 0)
    assert decision == "HOLD", f"Expected HOLD, got {decision}"
    print(f"✅ Test 3 PASSED: Ensemble correctly votes HOLD when models disagree")


def test_ensemble_agreement_level():
    """Test agreement level calculation"""
    voter = EnsembleVoter()

    # Test case: 3/3 models agree
    _, _, details = voter.vote(0.8, 0.75, 1)  # All say UP
    assert details['agreement_level'] == 1.0, "Expected 100% agreement"
    assert details['up_votes'] == 3, "Expected 3 UP votes"
    print(f"✅ Agreement test PASSED: 3/3 models agreement detected")


@pytest.mark.skip(reason="Legacy feature_engineering.py deprecated — use compute.py")
def test_feature_engineering():
    """Test feature engineering pipeline"""
    # Create sample market data
    dates = pd.date_range('2024-01-01', periods=100, freq='5min')
    sample_data = pd.DataFrame({
        'open': np.random.uniform(2300, 2400, 100),
        'high': np.random.uniform(2300, 2400, 100),
        'low': np.random.uniform(2300, 2400, 100),
        'close': np.random.uniform(2300, 2400, 100),
        'volume': np.random.uniform(1e6, 5e6, 100),
    }, index=dates)

    # Add features
    df_with_features = add_advanced_features(sample_data)

    # Verify features were added
    new_features = ['williams_r', 'cci', 'vwma_20', 'mfi', 'higher_high', 'lower_low']
    for feature in new_features:
        assert feature in df_with_features.columns, f"Feature {feature} not found"

    print(f"✅ Feature engineering PASSED: {len(df_with_features.columns)} features generated")


def test_voting_history():
    """Test voting history tracking"""
    voter = EnsembleVoter()

    # Make multiple votes
    for i in range(10):
        voter.vote(0.6 + i*0.01, 0.65 + i*0.01, 1)

    stats = voter.get_statistics()
    assert stats['total_votes'] == 10, "Expected 10 votes recorded"
    assert stats['recent_long'] == 10, "Expected 10 LONG votes"
    print(f"✅ Voting history PASSED: {stats['total_votes']} votes tracked, avg confidence {stats['avg_confidence']:.2%}")


def test_ensemble_metrics():
    """Test ensemble metrics and performance"""
    voter = EnsembleVoter()

    # Simulate mixed votes
    test_cases = [
        (0.75, 0.72, 1, "LONG"),  # Bullish
        (0.25, 0.28, 2, "SHORT"),  # Bearish
        (0.55, 0.45, 0, "HOLD"),  # Neutral
        (0.70, 0.65, 1, "LONG"),  # Bullish
        (0.30, 0.32, 2, "SHORT"),  # Bearish
    ]

    for xgb, lstm, dqn, expected in test_cases:
        decision, conf, _ = voter.vote(xgb, lstm, dqn)
        assert decision == expected, f"Expected {expected}, got {decision}"

    stats = voter.get_statistics()
    print(f"✅ Ensemble metrics PASSED:")
    print(f"   - Total votes: {stats['total_votes']}")
    print(f"   - LONG: {stats['recent_long']}, SHORT: {stats['recent_short']}, HOLD: {stats['recent_hold']}")
    print(f"   - Avg confidence: {stats['avg_confidence']:.2%}")
    print(f"   - Agreement level: {stats['avg_agreement_level']:.2%}")


def test_weight_updates():
    """Test dynamic weight updates"""
    voter = EnsembleVoter()

    # Initial weights
    initial_xgb = voter.xgb_weight

    # Update weights
    voter.update_weights(xgb_weight=0.5, lstm_weight=0.3, dqn_weight=0.2)

    # Verify update
    assert voter.xgb_weight == 0.5, "XGBoost weight not updated"
    assert voter.lstm_weight == 0.3, "LSTM weight not updated"
    assert voter.dqn_weight == 0.2, "DQN weight not updated"

    print(f"✅ Weight updates PASSED: Weights updated successfully")


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("ENSEMBLE VOTING - INTEGRATION TESTS")
    print("="*60 + "\n")

    try:
        test_ensemble_voter_basic()
        print()
        test_ensemble_agreement_level()
        print()
        test_feature_engineering()
        print()
        test_voting_history()
        print()
        test_ensemble_metrics()
        print()
        test_weight_updates()

        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED")
        print("="*60 + "\n")
        return True

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

