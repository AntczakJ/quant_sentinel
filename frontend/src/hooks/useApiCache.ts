/**
 * src/hooks/useApiCache.ts - Professional API caching with smart invalidation
 */

import { useCallback, useRef, useEffect, useState } from 'react';

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

interface CacheStore {
  [key: string]: CacheEntry<any>;
}

const globalCache: CacheStore = {};

/**
 * Professional API cache hook with intelligent TTL management
 * Reduces API calls significantly by caching responses
 */
export function useApiCache() {
  const cacheRef = useRef(globalCache);

  const get = useCallback(<T,>(key: string, ttl: number = 30000): T | null => {
    const entry = cacheRef.current[key];

    if (!entry) {
      return null;
    }

    const now = Date.now();
    const age = now - entry.timestamp;

    // Check if cache is expired
    if (age > ttl) {
      delete cacheRef.current[key];
      return null;
    }

    return entry.data as T;
  }, []);

  const set = useCallback(<T,>(key: string, data: T, ttl: number = 30000): void => {
    cacheRef.current[key] = {
      data,
      timestamp: Date.now(),
      ttl,
    };
  }, []);

  const invalidate = useCallback((key: string): void => {
    delete cacheRef.current[key];
  }, []);

  const invalidatePattern = useCallback((pattern: string): void => {
    const regex = new RegExp(pattern);
    Object.keys(cacheRef.current).forEach(key => {
      if (regex.test(key)) {
        delete cacheRef.current[key];
      }
    });
  }, []);

  const clear = useCallback((): void => {
    Object.keys(cacheRef.current).forEach(key => {
      delete cacheRef.current[key];
    });
  }, []);

  const getStats = useCallback((): { size: number; entries: string[] } => {
    return {
      size: Object.keys(cacheRef.current).length,
      entries: Object.keys(cacheRef.current),
    };
  }, []);

  return {
    get,
    set,
    invalidate,
    invalidatePattern,
    clear,
    getStats,
  };
}

/**
 * Professional hook for fetching data with caching
 */
export function useCachedFetch<T,>(
  key: string,
  fetchFn: () => Promise<T>,
  options: {
    ttl?: number;
    enabled?: boolean;
    onSuccess?: (data: T) => void;
    onError?: (error: Error) => void;
  } = {}
) {
  const cache = useApiCache();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const ttl = options.ttl ?? 30000; // Default 30s
  const enabled = options.enabled ?? true;

  const fetch = useCallback(async () => {
    // Check cache first
    const cached = cache.get<T>(key, ttl);
    if (cached) {
      setData(cached);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const result = await fetchFn();
      cache.set(key, result, ttl);
      setData(result);
      options.onSuccess?.(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      options.onError?.(error);
    } finally {
      setLoading(false);
    }
  }, [key, fetchFn, ttl, cache, options]);

  useEffect(() => {
    if (enabled) {
      fetch();
    }
  }, [key, enabled, fetch]);

  return {
    data,
    loading,
    error,
    refetch: fetch,
  };
}

