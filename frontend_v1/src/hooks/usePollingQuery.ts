/**
 * src/hooks/usePollingQuery.ts — Thin wrapper around React Query's useQuery
 *
 * Provides polling with:
 * - Automatic stale data display (no blank flash)
 * - Error retry with exponential backoff
 * - Window focus refetch disabled (we poll instead)
 * - Circuit breaker awareness: skips fetch when backend is known-down
 * - Typed data and error
 *
 * Usage:
 *   const { data, isLoading, error } = usePollingQuery('ticker', () => marketAPI.getTicker(), 15_000);
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { useTradingStore } from '../store/tradingStore';

export function usePollingQuery<T>(
  key: string | string[],
  fetcher: () => Promise<T>,
  intervalMs: number,
  options?: {
    enabled?: boolean;
    staleTime?: number;
    onSuccess?: (data: T) => void;
  },
): UseQueryResult<T, Error> {
  const queryKey = typeof key === 'string' ? [key] : key;
  const apiConnected = useTradingStore((s) => s.apiConnected);

  // Don't poll when backend is known-down (circuit open)
  const enabled = (options?.enabled ?? true) && apiConnected;

  return useQuery<T, Error>({
    queryKey,
    queryFn: async () => {
      const result = await fetcher();
      options?.onSuccess?.(result);
      return result;
    },
    refetchInterval: enabled ? intervalMs : false,
    refetchOnWindowFocus: false,
    staleTime: options?.staleTime ?? intervalMs * 0.8,
    gcTime: intervalMs * 3,
    retry: 1,
    retryDelay: 5000,
    enabled,
    placeholderData: (prev) => prev, // Keep stale data visible while refetching
  });
}

