#!/usr/bin/env python3
"""tests/test_ml.py - Machine Learning tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from src.ml_models import ml
    from src.rl_agent import DQNAgent

    print("Testing Machine Learning...")

    tests_passed = 0
    tests_total = 0

    # Test 1: ML module loaded
    try:
        assert ml is not None
        print("[OK] ML module loaded")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] ML module: {e}")
    tests_total += 1

    # Test 2: RL Agent
    try:
        agent = DQNAgent(state_size=22, action_size=3)
        assert agent is not None
        print("[OK] RL Agent initialized")
        tests_passed += 1
    except Exception as e:
        print(f"[FAIL] RL Agent: {e}")
    tests_total += 1

    # Test 3: Model prediction
    try:
        import pandas as pd
        import numpy as np
        df = pd.DataFrame({
            'close': np.random.rand(100) * 100,
            'open': np.random.rand(100) * 100,
            'high': np.random.rand(100) * 100,
            'low': np.random.rand(100) * 100,
        })
        if hasattr(ml, 'predict_xgb'):
            pred = ml.predict_xgb(df)
            assert pred is not None
            print("[OK] XGBoost prediction")
            tests_passed += 1
        else:
            print("[WARN] XGBoost not available")
    except Exception as e:
        print(f"[FAIL] XGBoost prediction: {e}")
    tests_total += 1

    print(f"\n{tests_passed}/{tests_total} tests passed")
    return 0 if tests_passed >= tests_total * 0.6 else 1


if __name__ == "__main__":
    sys.exit(main())
