/**
 * src/App.tsx - Main application with react-router and lazy-loaded pages
 * Each page is a separate chunk — only the active page JS is loaded.
 */

import { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClientProvider, QueryClient } from '@tanstack/react-query';
import { Dashboard } from './components/dashboard';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { ToastProvider } from './components/ui/Toast';
import { useTradingStore } from './store/tradingStore';
import { marketAPI, portfolioAPI, modelsAPI, healthAPI } from './api/client';
import { useCachedFetch } from './hooks/useApiCache';
import { prefetchAllRoutes } from './hooks/usePrefetchRoutes';
import { useWebSocket } from './hooks/useWebSocket';
import { useBrowserNotifications } from './hooks/useBrowserNotifications';
import { RefreshCw } from 'lucide-react';
import './index.css';

/* ── Lazy-loaded pages (code-split chunks) ─────────────────────────────── */
const ChartPage    = lazy(() => import('./pages/ChartPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const TradesPage   = lazy(() => import('./pages/TradesPage'));
const ModelsPage   = lazy(() => import('./pages/ModelsPage'));
const NewsPage     = lazy(() => import('./pages/NewsPage'));
const AgentPage    = lazy(() => import('./pages/AgentPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30000,
      gcTime: 60000,
      refetchInterval: 60000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64 text-th-muted text-sm gap-2">
      <RefreshCw size={14} className="animate-spin" />
      Loading…
    </div>
  );
}

function AppContent() {
  const { setTicker, setCurrentSignal, setPortfolio, setModelsStats, setApiConnected, setWsConnected, apiConnected } = useTradingStore();

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

  // Health check — adaptive interval: 30s when online, 20s when offline
  // (circuit breaker inside client.ts prevents actual network calls when OPEN)
  // Initial check is staggered by 500ms to avoid request burst with chart data.
  useEffect(() => {
    const checkHealth = async () => {
      try {
        await healthAPI.check();
        setApiConnected(true);
      } catch {
        setApiConnected(false);
      }
    };
    const initTimer = setTimeout(() => void checkHealth(), 500);
    const interval = setInterval(checkHealth, apiConnected ? 30_000 : 20_000);
    return () => { clearTimeout(initTimer); clearInterval(interval); };
  }, [setApiConnected, apiConnected]);

  // ── WebSocket live price feed — replaces most HTTP ticker polling ──
  // When WS is connected, ticker updates arrive every ~30s via push.
  // HTTP polling below acts as fallback when WS is disconnected.
  const { status: wsPriceStatus } = useWebSocket<{
    type: string; symbol: string; price: number;
    change: number; change_pct: number;
    high_24h?: number; low_24h?: number; timestamp: string;
  }>('/ws/prices', (data) => {
    if (data.type === 'price') {
      setTicker({
        symbol: data.symbol ?? 'XAU/USD',
        price: data.price,
        change: data.change ?? 0,
        change_pct: data.change_pct ?? 0,
        high_24h: data.high_24h ?? data.price,
        low_24h: data.low_24h ?? data.price,
        timestamp: data.timestamp,
      });
    }
  }, apiConnected);

  // Browser notifications — request permission on first API connection
  const { notifySignal, requestPermission } = useBrowserNotifications();
  useEffect(() => {
    if (apiConnected) void requestPermission();
  }, [apiConnected, requestPermission]);

  // WS signal feed — instant signal notifications + browser push
  useWebSocket<{ type: string; direction?: string; entry_price?: number; [k: string]: unknown }>(
    '/ws/signals',
    (data) => {
      if (data.type === 'signal') {
        setCurrentSignal(data as any);
        if (data.direction && data.direction !== 'WAIT') {
          notifySignal(data.direction, data.entry_price);
        }
      }
    },
    apiConnected,
  );

  // Track WS connection in store for header indicator
  const wsConnected = wsPriceStatus === 'connected';
  useEffect(() => { setWsConnected(wsConnected); }, [wsConnected, setWsConnected]);

  // Ticker HTTP polling — fallback when WS is disconnected, longer interval
  useCachedFetch('ticker', () => marketAPI.getTicker(), {
    ttl: wsConnected ? 120_000 : 20_000, // Slow down when WS is active
    enabled: apiConnected,
    onSuccess: setTicker,
  });

  // Portfolio — stagger 2s after mount to avoid request burst
  useCachedFetch('portfolio', () => portfolioAPI.getStatus(), {
    ttl: 30000,
    enabled: apiConnected,
    onSuccess: setPortfolio,
  });

  // Model stats — stagger 4s after mount (least urgent)
  useCachedFetch('models-stats', () => modelsAPI.getStats(), {
    ttl: 60000,
    enabled: apiConnected,
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
        <Route path="news" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania newsów">
            <Suspense fallback={<PageLoader />}><NewsPage /></Suspense>
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
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ToastProvider>
          <div className="min-h-screen bg-dark-bg text-th font-sans">
            <AppContent />
          </div>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

