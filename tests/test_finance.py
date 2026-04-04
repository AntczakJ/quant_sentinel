#!/usr/bin/env python3
"""tests/test_finance.py - Finance calculations tests"""

from src.finance import calculate_position

print("Testing finance calculations...")

tests_passed = 0
tests_total = 0

# Test 1: calculate_position
try:
    analysis = {
        'price': 2545.50,
        'trend': 'bull',
        'fvg_type': 'bullish',
        'ob_price': 2540.00,
        'swing_high': 2550.00,
        'swing_low': 2530.00,
        'atr': 15.0,
        'macro_regime': 'zielony',
    }
    result = calculate_position(analysis, 10000, "USD", "key")
    assert result is not None
    assert 'direction' in result
    print("✅ calculate_position")
    tests_passed += 1
except Exception as e:
    print(f"❌ calculate_position: {e}")
tests_total += 1

# Test 2: SL/TP presence
try:
    analysis = {
        'price': 2545.50,
        'trend': 'bull',
        'fvg_type': 'bullish',
        'ob_price': 2540.00,
        'swing_high': 2550.00,
        'swing_low': 2530.00,
        'atr': 15.0,
        'macro_regime': 'zielony',
    }
    result = calculate_position(analysis, 10000, "USD", "key")
    # When direction is CZEKAJ, other fields may not be present
    if result.get('direction') in ['LONG', 'SHORT']:
        assert 'sl' in result
        assert 'tp' in result
    print("✅ SL/TP validation")
    tests_passed += 1
except Exception as e:
    print(f"❌ SL/TP validation: {e}")
tests_total += 1

print(f"\n{tests_passed}/{tests_total} tests passed")
exit(0 if tests_passed == tests_total else 1)

