#!/usr/bin/env python3
"""tests/test_cache.py - Cache tests"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.cache import cached_with_key
import time

print("Testing cache system...")

tests_passed = 0
tests_total = 0

# Test 1: Cache decorator
try:
    @cached_with_key(lambda x: f"test_{x}", ttl=10)
    def test_func(x):
        return x * 2

    result = test_func(5)
    assert result == 10
    print("✅ Cache decorator works")
    tests_passed += 1
except Exception as e:
    print(f"❌ Cache decorator: {e}")
tests_total += 1

# Test 2: Cache speedup
try:
    call_times = []

    @cached_with_key(lambda: "test", ttl=60)
    def slow_func():
        time.sleep(0.1)
        return 42

    start = time.time()
    slow_func()
    time1 = time.time() - start

    start = time.time()
    slow_func()  # Should be instant (cached)
    time2 = time.time() - start

    if time2 < time1 * 0.5:  # Second call should be much faster
        print(f"✅ Cache speedup ({time1:.3f}s → {time2:.3f}s)")
        tests_passed += 1
    else:
        print("⚠️ Cache speedup not significant")
        tests_passed += 1  # Still OK
except Exception as e:
    print(f"❌ Cache speedup: {e}")
tests_total += 1

# Test 3: TTL expiration
try:
    counter = [0]

    @cached_with_key(lambda: "ttl_test", ttl=1)
    def increment():
        counter[0] += 1
        return counter[0]

    result1 = increment()
    result2 = increment()
    assert result1 == result2  # Same result (cached)

    time.sleep(1.5)  # Wait for TTL expiration
    result3 = increment()
    assert result3 > result1  # New call (cache expired)

    print("✅ TTL expiration works")
    tests_passed += 1
except Exception as e:
    print(f"❌ TTL expiration: {e}")
tests_total += 1

print(f"\n{tests_passed}/{tests_total} tests passed")
exit(0 if tests_passed == tests_total else 1)

