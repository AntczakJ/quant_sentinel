/**
 * src/App.tsx - Main application with react-router and lazy-loaded pages
 * Each page is a separate chunk — only the active page JS is loaded.
 */

import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { Dashboard } from './components/dashboard';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { useTradingStore } from './store/tradingStore';
import { marketAPI, portfolioAPI, modelsAPI, healthAPI } from './api/client';
import { useCachedFetch } from './hooks/useApiCache';
import { prefetchAllRoutes } from './hooks/usePrefetchRoutes';
import { RefreshCw } from 'lucide-react';
import './index.css';

/* ── Lazy-loaded pages (code-split chunks) ─────────────────────────────── */
const ChartPage    = lazy(() => import('./pages/ChartPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const TradesPage   = lazy(() => import('./pages/TradesPage'));
const ModelsPage   = lazy(() => import('./pages/ModelsPage'));
const AgentPage    = lazy(() => import('./pages/AgentPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60000,
      gcTime: 120000,
      refetchInterval: 120000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64 text-gray-500 text-sm gap-2">
      <RefreshCw size={14} className="animate-spin" />
      Loading…
    </div>
  );
}

function AppContent() {
  const { setTicker, setPortfolio, setModelsStats, setApiConnected } = useTradingStore();

  // Ukryj splash screen gdy React się zamontuje + prefetch routes
  useEffect(() => {
    const splash = document.getElementById('splash');
    if (splash) {
      const timer = setTimeout(() => {
        splash.classList.add('qs-hidden');
        setTimeout(() => { splash.remove(); prefetchAllRoutes(); }, 700);
      }, 400);
      return () => clearTimeout(timer);
    } else {
      prefetchAllRoutes();
    }
  }, []);

  // Health check
  useEffect(() => {
    const checkHealth = async () => {
      try {
        await healthAPI.check();
        setApiConnected(true);
      } catch {
        setApiConnected(false);
      }
    };
    void checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [setApiConnected]);

  // Ticker polling — always active (header needs it)
  useCachedFetch('ticker', () => marketAPI.getTicker(), {
    ttl: 15000,
    onSuccess: setTicker,
  });

  // Portfolio
  useCachedFetch('portfolio', () => portfolioAPI.getStatus(), {
    ttl: 60000,
    onSuccess: setPortfolio,
  });

  // Model stats
  useCachedFetch('models-stats', () => modelsAPI.getStats(), {
    ttl: 90000,
    onSuccess: setModelsStats,
  });

  return (
    <Routes>
      <Route element={<Dashboard />}>
        <Route index element={
          <ErrorBoundary fallbackTitle="Błąd ładowania wykresu">
            <Suspense fallback={<PageLoader />}><ChartPage /></Suspense>
          </ErrorBoundary>
        } />
        <Route path="analysis" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania analizy">
            <Suspense fallback={<PageLoader />}><AnalysisPage /></Suspense>
          </ErrorBoundary>
        } />
        <Route path="trades" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania transakcji">
            <Suspense fallback={<PageLoader />}><TradesPage /></Suspense>
          </ErrorBoundary>
        } />
        <Route path="models" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania modeli">
            <Suspense fallback={<PageLoader />}><ModelsPage /></Suspense>
          </ErrorBoundary>
        } />
        <Route path="agent" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania agenta">
            <Suspense fallback={<PageLoader />}><AgentPage /></Suspense>
          </ErrorBoundary>
        } />
        {/* Fallback: redirect unknown routes to chart */}
        <Route path="*" element={
          <ErrorBoundary>
            <Suspense fallback={<PageLoader />}><ChartPage /></Suspense>
          </ErrorBoundary>
        } />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-dark-bg text-gray-200 font-sans">
          <AppContent />
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

