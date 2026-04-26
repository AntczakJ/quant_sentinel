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
import type { Signal } from './types/trading';
import { useCachedFetch } from './hooks/useApiCache';
import { prefetchAllRoutes } from './hooks/usePrefetchRoutes';
import { useSSE } from './hooks/useSSE';
import { useBrowserNotifications } from './hooks/useBrowserNotifications';
import { useDocumentTitle } from './hooks/useDocumentTitle';
import { useFaviconBadge } from './hooks/useFaviconBadge';
import { pushNotification } from './components/dashboard/NotificationCenter';
// RefreshCw removed — PageLoader now uses branded QS logo
import './index.css';

/* ── Lazy-loaded pages (code-split chunks) ─────────────────────────────── */
const ChartPage    = lazy(() => import('./pages/ChartPage'));
const AnalysisPage = lazy(() => import('./pages/AnalysisPage'));
const TradesPage   = lazy(() => import('./pages/TradesPage'));
const ModelsPage   = lazy(() => import('./pages/ModelsPage'));
const NewsPage     = lazy(() => import('./pages/NewsPage'));
const AgentPage    = lazy(() => import('./pages/AgentPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

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
    <div className="flex flex-col items-center justify-center h-64 gap-3">
      <div className="flex items-center gap-1.5 animate-pulse">
        <span className="text-sm font-bold tracking-wider" style={{ color: 'var(--color-text-primary)' }}>QUANT</span>
        <span className="text-sm font-bold tracking-wider" style={{ color: 'var(--color-accent-green)' }}>SENTINEL</span>
      </div>
      <div className="flex gap-1">
        {[0, 1, 2].map(i => (
          <div
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-accent-green"
            style={{ animation: `pulse 1s ease-in-out ${i * 0.2}s infinite` }}
          />
        ))}
      </div>
    </div>
  );
}

function AppContent() {
  const { setTicker, setCurrentSignal, setPortfolio, setModelsStats, setApiConnected, setWsConnected, apiConnected } = useTradingStore();

  // Dynamic browser tab title with live price
  useDocumentTitle();

  // Favicon badge when there's an active signal
  const currentSignal = useTradingStore(s => s.currentSignal);
  const hasActiveSignal = Boolean(currentSignal && currentSignal.consensus && currentSignal.consensus !== 'HOLD');
  useFaviconBadge(hasActiveSignal);

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

  // ── SSE live price feed — native auto-reconnect, no manual backoff ──
  const { status: ssePriceStatus } = useSSE<{
    type: string; symbol: string; price: number;
    change: number; change_pct: number;
    high_24h?: number; low_24h?: number; timestamp: string;
  }>('/sse/prices', (data) => {
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

  // Browser notifications — request permission on first API connection.
  // Only call requestPermission() if permission is still 'default' (never
  // answered). Chrome blocks repeated requests after user ignores a prompt,
  // surfacing a console warning that can cascade into app load failures
  // when mixed with strict React error boundaries. Skipping a redundant
  // request is always safe.
  const { notifySignal, requestPermission } = useBrowserNotifications();
  useEffect(() => {
    if (!apiConnected) {return;}
    if (typeof Notification === 'undefined') {return;}
    if (Notification.permission !== 'default') {return;}
    try {
      void requestPermission();
    } catch {
      // Chrome may throw on blocked-by-policy / already-denied states.
    }
  }, [apiConnected, requestPermission]);

  // SSE signal feed — instant signal notifications + browser push
  useSSE<{ type: string; direction?: string; entry_price?: number; [k: string]: unknown }>(
    '/sse/signals',
    (data) => {
      if (data.type === 'signal') {
        setCurrentSignal(data as unknown as Signal);
        if (data.direction && data.direction !== 'WAIT') {
          notifySignal(data.direction, data.entry_price);
          pushNotification({
            type: 'signal',
            title: `Nowy sygnal: ${data.direction}`,
            message: data.entry_price ? `Entry: $${data.entry_price.toFixed(2)}` : 'Sprawdz dashboard',
          });
        }
      }
    },
    apiConnected,
  );

  // Track SSE connection in store for header indicator
  const wsConnected = ssePriceStatus === 'connected';
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
        <Route path="settings" element={
          <ErrorBoundary fallbackTitle="Błąd ładowania ustawień">
            <Suspense fallback={<PageLoader />}><SettingsPage /></Suspense>
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

