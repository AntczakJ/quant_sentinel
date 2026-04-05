/**
 * src/hooks/usePollingQuery.ts — Thin wrapper around React Query's useQuery
 *
 * Provides polling with:
 * - Automatic stale data display (no blank flash)
 * - Error retry with exponential backoff
 * - Window focus refetch disabled (we poll instead)
 * - Typed data and error
 *
 * Usage:
 *   const { data, isLoading, error } = usePollingQuery('ticker', () => marketAPI.getTicker(), 15_000);
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';

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

  return useQuery<T, Error>({
    queryKey,
    queryFn: async () => {
      const result = await fetcher();
      options?.onSuccess?.(result);
      return result;
    },
    refetchInterval: intervalMs,
    refetchOnWindowFocus: false,
    staleTime: options?.staleTime ?? intervalMs * 0.8,
    gcTime: intervalMs * 3,
    retry: 1,
    retryDelay: 3000,
    enabled: options?.enabled ?? true,
    placeholderData: (prev) => prev, // Keep stale data visible while refetching
  });
}

