/**
 * src/hooks/useApiCache.ts - API caching with smart invalidation
 *
 * IMPORTANT: Both hooks must return referentially-stable values to avoid
 * infinite React re-render loops.  useApiCache() returns a memoised object
 * whose methods never change, and useCachedFetch() keeps the cache handle
 * in a ref so it is invisible to useCallback / useEffect dependency arrays.
 */

import { useCallback, useRef, useEffect, useState, useMemo } from 'react';

interface CacheEntry<T> {
  data: T;
  timestamp: number;
  ttl: number;
}

interface CacheStore {
  [key: string]: CacheEntry<unknown>;
}

const globalCache: CacheStore = {};

/**
 * Low-level cache access.  All returned functions are referentially stable.
 */
export function useApiCache() {
  const store = useRef(globalCache);

  const get = useCallback(<T,>(key: string, ttl: number = 30000): T | null => {
    const entry = store.current[key];
    if (!entry) {return null;}
    if (Date.now() - entry.timestamp >= ttl) {
      delete store.current[key];
      return null;
    }
    return entry.data as T;
  }, []);

  const set = useCallback(<T,>(key: string, data: T, ttl: number = 30000): void => {
    store.current[key] = { data, timestamp: Date.now(), ttl };
  }, []);

  const invalidate = useCallback((key: string): void => {
    delete store.current[key];
  }, []);

  const invalidatePattern = useCallback((pattern: string): void => {
    const regex = new RegExp(pattern);
    Object.keys(store.current).forEach(k => {
      if (regex.test(k)) {delete store.current[k];}
    });
  }, []);

  const clear = useCallback((): void => {
    Object.keys(store.current).forEach(k => delete store.current[k]);
  }, []);

  const getStats = useCallback((): { size: number; entries: string[] } => ({
    size: Object.keys(store.current).length,
    entries: Object.keys(store.current),
  }), []);

  // Return a STABLE object — all deps are themselves stable (empty-dep useCallbacks).
  return useMemo(
    () => ({ get, set, invalidate, invalidatePattern, clear, getStats }),
    [get, set, invalidate, invalidatePattern, clear, getStats],
  );
}

/**
 * Fetch with TTL-based caching.  Avoids infinite loops by keeping all
 * mutable/unstable values in refs so that useCallback & useEffect deps
 * only contain primitives (key, ttl, enabled).
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
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const ttl = options.ttl ?? 30000;
  const enabled = options.enabled ?? true;

  // ── Stable refs for values that must NOT appear in hook deps ──
  const cacheRef = useRef(useApiCache());
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;
  const onSuccessRef = useRef(options.onSuccess);
  onSuccessRef.current = options.onSuccess;
  const onErrorRef = useRef(options.onError);
  onErrorRef.current = options.onError;

  const doFetch = useCallback(async () => {
    const cache = cacheRef.current;

    // Check cache first
    const cached = cache.get<T>(key, ttl);
    if (cached) {
      setData(cached);
      onSuccessRef.current?.(cached);
      return;
    }

    try {
      setLoading(true);
      setError(null);
      const result = await fetchFnRef.current();
      cache.set(key, result, ttl);
      setData(result);
      onSuccessRef.current?.(result);
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      setError(e);
      onErrorRef.current?.(e);
    } finally {
      setLoading(false);
    }
  }, [key, ttl]);   // ← only primitives, no object refs

  useEffect(() => {
    if (!enabled) {return;}
    void doFetch();
    const interval = setInterval(() => void doFetch(), ttl);
    return () => clearInterval(interval);
  }, [enabled, doFetch, ttl]);   // ← stable deps, no infinite loop

  return { data, loading, error, refetch: doFetch };
}
