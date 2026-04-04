/**
 * src/App.tsx - Main application component
 * Optimized with centralized API caching to reduce requests
 */

import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { Dashboard } from './components/dashboard/Dashboard';
import { useTradingStore } from './store/tradingStore';
import { marketAPI, portfolioAPI, modelsAPI, healthAPI } from './api/client';
import { useCachedFetch } from './hooks/useApiCache';
import { useEffect } from 'react';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60000, // 60 seconds (up from 30)
      gcTime: 120000, // 120 seconds (up from 60)
      refetchInterval: 120000, // 2 minutes (up from 1)
      refetchOnWindowFocus: false, // Don't refetch when window refocuses
      retry: 1, // Only 1 retry
    },
  },
});

export function App() {
  const { setTicker, setPortfolio, setModelsStats, setApiConnected } = useTradingStore();

  // Health check - every 10 seconds
  useEffect(() => {
    const checkHealth = async () => {
      try {
        await healthAPI.check();
        setApiConnected(true);
      } catch (error) {
        setApiConnected(false);
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, [setApiConnected]);

  // Ticker - Update every 60 seconds (not 3 seconds!)
  useCachedFetch(
    'ticker',
    () => marketAPI.getTicker(),
    {
      ttl: 60000,
      onSuccess: setTicker,
    }
  );

  // Portfolio - Update every 60 seconds
  useCachedFetch(
    'portfolio',
    () => portfolioAPI.getStatus(),
    {
      ttl: 60000,
      onSuccess: setPortfolio,
    }
  );

  // Model stats - Update every 90 seconds
  useCachedFetch(
    'models-stats',
    () => modelsAPI.getStats(),
    {
      ttl: 90000,
      onSuccess: setModelsStats,
    }
  );

  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen bg-dark-bg text-white font-mono">
        <Dashboard />
      </div>
    </QueryClientProvider>
  );
}


