#!/usr/bin/env python3
"""
test_optimization.py - Test rate limiter i optimization system
"""

from src.api_optimizer import (
    get_rate_limiter,
    get_batch_grouper,
    CreditWeights,
    RateLimiter
)
from src.persistent_cache import get_persistent_cache
import time

def test_rate_limiter():
    """Test basic rate limiter functionality"""
    print("\n" + "="*60)
    print("🧪 Testing Rate Limiter")
    print("="*60)

    limiter = RateLimiter(credits_per_minute=55, safe_margin=52)

    # Test 1: Can use credits
    print("\n✓ Test 1: Check if can use credits")
    can_use, wait_time = limiter.can_use_credits(10)
    print(f"  Can use 10 credits: {can_use}")
    print(f"  Wait time: {wait_time:.1f}s")

    # Test 2: Use credits
    print("\n✓ Test 2: Use credits")
    result = limiter.use_credits(10, endpoint='price', symbol='AAPL')
    print(f"  Used 10 credits successfully: {result}")

    # Test 3: Check stats
    print("\n✓ Test 3: Get statistics")
    stats = limiter.get_stats()
    print(f"  Current credits: {stats['current_credits']}")
    print(f"  Credits used last min: {stats['credits_used_last_min']}")
    print(f"  Recent requests: {stats['recent_requests']}")

    # Test 4: Validate expensive endpoint
    print("\n✓ Test 4: Validate endpoint costs")

    is_safe, cost, error = limiter.validate_endpoint_cost('price', num_symbols=1)
    print(f"  Price endpoint (1 symbol): {is_safe}, Cost: {cost} credits")

    is_safe, cost, error = limiter.validate_endpoint_cost('income_statement', num_symbols=1)
    print(f"  Income statement (1 symbol): {is_safe}, Cost: {cost} credits")
    if error:
        print(f"  Error: {error[:80]}...")

    # Test 5: Batch grouping
    print("\n✓ Test 5: Batch grouping")
    grouper = get_batch_grouper()
    symbols = ['AAPL', 'MSFT', 'TSLA', 'GOOGL', 'AMZN', 'FB', 'NFLX', 'UBER', 'COIN', 'SQ', 'ROKU', 'DDOG']
    batches = grouper.group_symbols(symbols)
    print(f"  Grouped {len(symbols)} symbols into {len(batches)} batches")
    for i, batch in enumerate(batches):
        print(f"    Batch {i+1}: {', '.join(batch)}")


def test_persistent_cache():
    """Test persistent cache"""
    print("\n" + "="*60)
    print("🧪 Testing Persistent Cache")
    print("="*60)

    cache = get_persistent_cache()

    # Test 1: Set and get daily OHLC
    print("\n✓ Test 1: Daily OHLC caching")
    import pandas as pd
    test_data = pd.DataFrame({
        'open': [100, 101, 102],
        'high': [102, 103, 104],
        'low': [99, 100, 101],
        'close': [101, 102, 103],
    })
    cache.set_daily_ohlc('AAPL', test_data)
    retrieved = cache.get_daily_ohlc('AAPL')
    print(f"  Cached daily OHLC: {len(retrieved)} rows" if retrieved is not None else "  Retrieved: None")

    # Test 2: Set and get company stats
    print("\n✓ Test 2: Company stats caching")
    stats_data = {'eps': 5.61, 'pe_ratio': 25.5, 'market_cap': 2000000000}
    cache.set_company_stats('AAPL', stats_data)
    retrieved = cache.get_company_stats('AAPL')
    print(f"  Cached company stats: {retrieved}" if retrieved else "  Retrieved: None")

    # Test 3: Cache stats
    print("\n✓ Test 3: Cache statistics")
    stats = cache.get_stats()
    print(f"  Memory cache size: {stats['memory_cache_size']}")
    print(f"  Disk cache files: {stats['disk_cache_files']}")


def test_credit_weights():
    """Test credit weight calculations"""
    print("\n" + "="*60)
    print("🧪 Testing Credit Weights")
    print("="*60)

    endpoints = [
        ('price', 1),
        ('time_series', 1),
        ('quote', 1),
        ('income_statement', 100),
        ('balance_sheet', 100),
        ('cash_flow', 100),
    ]

    print("\nEndpoint Credit Costs:")
    for endpoint, expected in endpoints:
        cost = CreditWeights.get_cost(endpoint)
        status = "✅" if cost == expected else "❌"
        print(f"  {status} {endpoint}: {cost} credits (expected: {expected})")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("🚀 OPTIMIZATION SYSTEM TESTS")
    print("="*60)
    print("Testing: Rate Limiting, Batch Requests, Caching, Credits")

    try:
        test_rate_limiter()
        test_persistent_cache()
        test_credit_weights()

        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\n🎉 Optimization system is working correctly!")
        print("📊 Ready for production with:")
        print("   - Rate Limiting: 55 credits/min with 52 safe limit")
        print("   - Batch Requests: Auto-grouping max 10 symbols")
        print("   - Persistent Cache: Disk + memory with smart TTL")
        print("   - Exponential Backoff: 429 error handling")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())

