/**
 * src/hooks/usePersistedCache.ts — IndexedDB-backed cache for chart data
 *
 * Candle data for each (symbol, interval) pair is ~30KB and stable between
 * polling intervals.  This persists responses so navigating between
 * pages/intervals shows cached data instantly and survives page reloads.
 *
 * Uses `idb-keyval` (~1KB) — the simplest IndexedDB wrapper.
 */

import { get, set, del, clear as idbClear, createStore } from 'idb-keyval';

// Dedicated IndexedDB store for cache (avoids collision with other IDB usage)
const cacheStore = createStore('qs-cache-db', 'qs-cache-store');

interface CachedItem<T = unknown> {
  data: T;
  timestamp: number;
  ttl: number;
}

/**
 * Store a value in IndexedDB with TTL metadata.
 */
export async function setCached<T>(key: string, data: T, ttlMs: number): Promise<void> {
  try {
    const item: CachedItem<T> = { data, timestamp: Date.now(), ttl: ttlMs };
    await set(key, item, cacheStore);
  } catch {
    // IndexedDB unavailable in some contexts — silently skip
  }
}

/**
 * Get a value from IndexedDB if it hasn't expired.
 * Returns null if expired or missing.
 */
export async function getCached<T>(key: string, ttlMs?: number): Promise<T | null> {
  try {
    const item = await get<CachedItem<T>>(key, cacheStore);
    if (!item) return null;
    const maxAge = ttlMs ?? item.ttl;
    if (Date.now() - item.timestamp > maxAge) {
      // Expired — clean up in background
      void del(key, cacheStore);
      return null;
    }
    return item.data;
  } catch {
    return null;
  }
}

/**
 * Get a value even if expired — for stale-while-revalidate pattern.
 * Returns { data, isStale } or null.
 */
export async function getCachedStale<T>(key: string): Promise<{ data: T; isStale: boolean } | null> {
  try {
    const item = await get<CachedItem<T>>(key, cacheStore);
    if (!item) return null;
    const isStale = Date.now() - item.timestamp > item.ttl;
    return { data: item.data, isStale };
  } catch {
    return null;
  }
}

/**
 * Remove a specific key from cache.
 */
export async function removeCached(key: string): Promise<void> {
  try {
    await del(key, cacheStore);
  } catch {
    // ignore
  }
}

/**
 * Clear all cached items.
 */
export async function clearAllCached(): Promise<void> {
  try {
    await idbClear(cacheStore);
  } catch {
    // ignore
  }
}

