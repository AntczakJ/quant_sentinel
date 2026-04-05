#!/usr/bin/env python3
"""tests/test_smc_engine.py - SMC Engine tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.smc_engine import get_smc_analysis, detect_fvg, detect_dbr_rbd
import pandas as pd

print("Testing SMC Engine...")

tests_passed = 0
tests_total = 0

# Test 1: get_smc_analysis
try:
    result = get_smc_analysis("15m")
    assert result is not None
    assert isinstance(result, dict)
    print("✅ get_smc_analysis")
    tests_passed += 1
except Exception as e:
    print(f"❌ get_smc_analysis: {e}")
tests_total += 1

# Test 2: detect_fvg
try:
    df = pd.DataFrame({
        'high': [100, 105, 95, 105],
        'low': [95, 100, 90, 100],
    })
    fvg = detect_fvg(df)
    assert isinstance(fvg, dict)
    assert 'type' in fvg
    print("✅ detect_fvg")
    tests_passed += 1
except Exception as e:
    print(f"❌ detect_fvg: {e}")
tests_total += 1

# Test 3: detect_dbr_rbd
try:
    df = pd.DataFrame({
        'high': [100, 110, 105, 115, 120, 110],
        'low': [95, 100, 100, 105, 110, 100],
    })
    dbr = detect_dbr_rbd(df)
    assert isinstance(dbr, dict)
    print("✅ detect_dbr_rbd")
    tests_passed += 1
except Exception as e:
    print(f"❌ detect_dbr_rbd: {e}")
tests_total += 1

print(f"\n{tests_passed}/{tests_total} tests passed")
exit(0 if tests_passed == tests_total else 1)

