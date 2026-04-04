"""
src/persistent_cache.py - Aggressive caching for daily data
Caches data that doesn't change frequently to drastically reduce API calls
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

CACHE_DIR = os.getenv('CACHE_DIR', './cache')
os.makedirs(CACHE_DIR, exist_ok=True)


class PersistentCache:
    """
    Disk-based persistent cache for expensive data
    - Daily OHLC data: 24h TTL
    - Company stats: 7d TTL
    - Income statements: 30d TTL (not fetched anyway due to cost)
    """

    def __init__(self):
        self.memory_cache = {}
        logger.info("📦 PersistentCache initialized")

    def _get_cache_path(self, key: str) -> str:
        """Get file path for cache key"""
        safe_key = key.replace('/', '_').replace(':', '_')
        return os.path.join(CACHE_DIR, f"{safe_key}.json")

    def _is_fresh(self, timestamp: float, ttl_seconds: int) -> bool:
        """Check if cache entry is fresh"""
        return (time.time() - timestamp) < ttl_seconds

    def get_daily_ohlc(self, symbol: str) -> Optional[Dict]:
        """
        Get cached daily OHLC data (24h TTL)

        Args:
            symbol: Stock symbol

        Returns:
            Cached OHLC data or None
        """
        key = f"daily_ohlc:{symbol}"

        # Check memory cache first
        if key in self.memory_cache:
            cached = self.memory_cache[key]
            if self._is_fresh(cached['timestamp'], 86400):  # 24h
                logger.debug(f"📦 Memory cache hit: {symbol} daily OHLC")
                return cached['data']
            else:
                del self.memory_cache[key]

        # Check disk cache
        cache_path = self._get_cache_path(key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)

                if self._is_fresh(cached['timestamp'], 86400):  # 24h
                    self.memory_cache[key] = cached
                    logger.debug(f"💾 Disk cache hit: {symbol} daily OHLC")
                    return cached['data']
                else:
                    os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Cache read error for {key}: {e}")

        return None

    def set_daily_ohlc(self, symbol: str, data: Dict):
        """
        Cache daily OHLC data

        Args:
            symbol: Stock symbol
            data: OHLC data
        """
        key = f"daily_ohlc:{symbol}"

        cache_entry = {
            'timestamp': time.time(),
            'data': data,
        }

        # Memory cache
        self.memory_cache[key] = cache_entry

        # Disk cache
        try:
            cache_path = self._get_cache_path(key)
            with open(cache_path, 'w') as f:
                json.dump(cache_entry, f)
            logger.debug(f"💾 Cached daily OHLC: {symbol}")
        except Exception as e:
            logger.warning(f"Cache write error for {key}: {e}")

    def get_company_stats(self, symbol: str) -> Optional[Dict]:
        """
        Get cached company stats (7d TTL)

        Args:
            symbol: Stock symbol

        Returns:
            Cached stats or None
        """
        key = f"company_stats:{symbol}"

        # Memory cache
        if key in self.memory_cache:
            cached = self.memory_cache[key]
            if self._is_fresh(cached['timestamp'], 604800):  # 7d
                logger.debug(f"📦 Memory cache hit: {symbol} company stats")
                return cached['data']
            else:
                del self.memory_cache[key]

        # Disk cache
        cache_path = self._get_cache_path(key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    cached = json.load(f)

                if self._is_fresh(cached['timestamp'], 604800):  # 7d
                    self.memory_cache[key] = cached
                    logger.debug(f"💾 Disk cache hit: {symbol} company stats")
                    return cached['data']
                else:
                    os.remove(cache_path)
            except Exception as e:
                logger.warning(f"Cache read error for {key}: {e}")

        return None

    def set_company_stats(self, symbol: str, data: Dict):
        """
        Cache company stats

        Args:
            symbol: Stock symbol
            data: Company statistics
        """
        key = f"company_stats:{symbol}"

        cache_entry = {
            'timestamp': time.time(),
            'data': data,
        }

        # Memory cache
        self.memory_cache[key] = cache_entry

        # Disk cache
        try:
            cache_path = self._get_cache_path(key)
            with open(cache_path, 'w') as f:
                json.dump(cache_entry, f)
            logger.debug(f"💾 Cached company stats: {symbol}")
        except Exception as e:
            logger.warning(f"Cache write error for {key}: {e}")

    def get_intraday_data(self, symbol: str, interval: str) -> Optional[Dict]:
        """
        Get cached intraday data (1h TTL for high frequency, 4h for low)

        Args:
            symbol: Stock symbol
            interval: Interval (5m, 15m, 1h, 4h)

        Returns:
            Cached data or None
        """
        key = f"intraday:{symbol}:{interval}"

        # TTL depends on interval
        ttl_map = {
            '5m': 300,      # 5 minutes
            '15m': 900,     # 15 minutes
            '1h': 3600,     # 1 hour
            '4h': 14400,    # 4 hours
        }
        ttl = ttl_map.get(interval, 300)

        # Memory cache
        if key in self.memory_cache:
            cached = self.memory_cache[key]
            if self._is_fresh(cached['timestamp'], ttl):
                logger.debug(f"📦 Memory cache hit: {symbol} {interval}")
                return cached['data']
            else:
                del self.memory_cache[key]

        # For frequently changing data, don't use disk cache
        # (only memory cache to reduce I/O)

        return None

    def set_intraday_data(self, symbol: str, interval: str, data: Dict):
        """
        Cache intraday data

        Args:
            symbol: Stock symbol
            interval: Interval
            data: OHLCV data
        """
        key = f"intraday:{symbol}:{interval}"

        cache_entry = {
            'timestamp': time.time(),
            'data': data,
        }

        self.memory_cache[key] = cache_entry
        logger.debug(f"📦 Cached intraday: {symbol} {interval}")

    def clear_expired(self):
        """Clean up expired entries"""
        now = time.time()
        to_delete = []

        for key, entry in self.memory_cache.items():
            # Different TTLs based on key type
            if 'daily_ohlc' in key:
                ttl = 86400
            elif 'company_stats' in key:
                ttl = 604800
            elif 'intraday' in key:
                ttl = 14400
            else:
                ttl = 3600

            if now - entry['timestamp'] > ttl:
                to_delete.append(key)

        for key in to_delete:
            del self.memory_cache[key]

        if to_delete:
            logger.debug(f"🗑️ Cleared {len(to_delete)} expired cache entries")

    def get_stats(self) -> Dict:
        """Get cache statistics"""
        self.clear_expired()

        return {
            'memory_cache_size': len(self.memory_cache),
            'cache_dir': CACHE_DIR,
            'disk_cache_files': len([f for f in os.listdir(CACHE_DIR) if f.endswith('.json')]),
        }


# Global persistent cache instance
_persistent_cache = None


def get_persistent_cache() -> PersistentCache:
    """Get global persistent cache"""
    global _persistent_cache
    if _persistent_cache is None:
        _persistent_cache = PersistentCache()
    return _persistent_cache

