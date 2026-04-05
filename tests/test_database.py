#!/usr/bin/env python3
"""tests/test_database.py - Database tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import NewsDB

print("Testing database...")

db = NewsDB()
tests_passed = 0
tests_total = 0

# Test 1: get_balance
try:
    balance = db.get_balance(12345)
    assert isinstance(balance, (int, float))
    print("✅ get_balance")
    tests_passed += 1
except Exception as e:
    print(f"❌ get_balance: {e}")
tests_total += 1

# Test 2: update_balance
try:
    db.update_balance(12345, 5000)
    balance = db.get_balance(12345)
    assert balance == 5000
    print("✅ update_balance")
    tests_passed += 1
except Exception as e:
    print(f"❌ update_balance: {e}")
tests_total += 1

# Test 3: get_param
try:
    db.set_param("test", 42.5)
    val = db.get_param("test", 0)
    assert val == 42.5
    print("✅ get/set_param")
    tests_passed += 1
except Exception as e:
    print(f"❌ get/set_param: {e}")
tests_total += 1

# Test 4: Performance stats
try:
    stats, history = db.get_performance_stats()
    assert stats is not None
    print("✅ get_performance_stats")
    tests_passed += 1
except Exception as e:
    print(f"❌ get_performance_stats: {e}")
tests_total += 1

# Test 5: Log trade
try:
    db.log_trade(direction="LONG", price=2545.50, sl=2540.00, tp=2555.00,
                 rsi=45.0, trend="bull", structure="FVG", factors={})
    print("✅ log_trade")
    tests_passed += 1
except Exception as e:
    print(f"❌ log_trade: {e}")
tests_total += 1

print(f"\n{tests_passed}/{tests_total} tests passed")
exit(0 if tests_passed == tests_total else 1)

