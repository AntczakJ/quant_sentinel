"""
src/cache.py - In-memory caching utilities with TTL support.

Provides decorators for caching function results with configurable TTL.
"""

import datetime
import functools
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar('T')

# Global cache storage
_cache: Dict[str, Dict[str, Any]] = {}
_MAX_CACHE_SIZE = 500  # evict expired entries when cache exceeds this size
_last_eviction_ts: float = 0.0


def _evict_expired():
    """Remove expired entries from cache. Called periodically to prevent memory bloat."""
    global _last_eviction_ts
    now = datetime.datetime.now().timestamp()
    # Run at most once per 60 seconds
    if now - _last_eviction_ts < 60:
        return
    _last_eviction_ts = now
    expired = [k for k, v in _cache.items() if now - v['ts'] > 600]  # 10 min max
    for k in expired:
        del _cache[k]


def cached(key: str, ttl: int = 180) -> Callable:
    """
    Decorator to cache function results with static key.

    Args:
        key: Cache key (static)
        ttl: Time-to-live in seconds (default 180)

    Returns:
        Decorated function with caching
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            now = datetime.datetime.now().timestamp()
            if key in _cache and now - _cache[key]['ts'] < ttl:
                return _cache[key]['val']
            result = func(*args, **kwargs)
            _cache[key] = {'val': result, 'ts': now}
            if len(_cache) > _MAX_CACHE_SIZE:
                _evict_expired()
            return result
        return wrapper
    return decorator


def cached_with_key(key_func: Callable[..., str], ttl: int = 180) -> Callable:
    """
    Decorator to cache function results with dynamically generated key.

    The key_func receives the same arguments as the decorated function
    and should return a string to be used as cache key.

    Args:
        key_func: Function to generate cache key from function arguments
        ttl: Time-to-live in seconds (default 180)

    Returns:
        Decorated function with caching

    Example:
        >>> def cache_key(symbol: str, interval: str) -> str:
        ...     return f"{symbol}:{interval}"
        >>>
        >>> @cached_with_key(cache_key, ttl=300)
        >>> def get_candles(symbol: str, interval: str) -> list:
        ...     return fetch_from_api(symbol, interval)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            key = key_func(*args, **kwargs)
            now = datetime.datetime.now().timestamp()
            if key in _cache and now - _cache[key]['ts'] < ttl:
                return _cache[key]['val']
            result = func(*args, **kwargs)
            _cache[key] = {'val': result, 'ts': now}
            if len(_cache) > _MAX_CACHE_SIZE:
                _evict_expired()
            return result
        return wrapper
    return decorator

