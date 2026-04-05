#!/usr/bin/env python3
"""tests/test_config.py - Configuration tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import USER_PREFS, LAST_STATUS, LAST_STATUS_LOCK, TOKEN, CHAT_ID
import threading

print("Testing configuration...")

tests_passed = 0
tests_total = 0

# Test 1: USER_PREFS structure
try:
    required_keys = {'currency', 'capital', 'risk_pc', 'tf', 'contract_size', 'target_rr'}
    assert required_keys.issubset(set(USER_PREFS.keys()))
    print("✅ USER_PREFS has required keys")
    tests_passed += 1
except Exception as e:
    print(f"❌ USER_PREFS: {e}")
tests_total += 1

# Test 2: LAST_STATUS structure
try:
    assert 'trend' in LAST_STATUS
    assert 'fvg' in LAST_STATUS
    print("✅ LAST_STATUS has required keys")
    tests_passed += 1
except Exception as e:
    print(f"❌ LAST_STATUS: {e}")
tests_total += 1

# Test 3: Thread safety
try:
    assert isinstance(LAST_STATUS_LOCK, threading.Lock)
    print("✅ LAST_STATUS_LOCK is thread-safe")
    tests_passed += 1
except Exception as e:
    print(f"❌ Thread safety: {e}")
tests_total += 1

# Test 4: API keys available
try:
    assert TOKEN is not None and len(TOKEN) > 0
    assert CHAT_ID is not None
    print("✅ API credentials loaded")
    tests_passed += 1
except Exception as e:
    print(f"❌ API credentials: {e}")
tests_total += 1

print(f"\n{tests_passed}/{tests_total} tests passed")
exit(0 if tests_passed == tests_total else 1)

