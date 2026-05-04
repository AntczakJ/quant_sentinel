import { lazy, Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import { Shell } from '@/components/Shell'
import { CommandPalette } from '@/components/CommandPalette'
import { ShortcutsOverlay } from '@/components/ShortcutsOverlay'
import { TradeWatcher } from '@/components/TradeWatcher'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import Dashboard from '@/pages/Dashboard'

// Code-split: only Dashboard ships in the initial bundle. Trades/Models/
// Chart/Settings load on-demand. lightweight-charts (~120 kB) lives in
// Chart's chunk so users who never open the chart never download it.
const Trades = lazy(() => import('@/pages/Trades'))
const Models = lazy(() => import('@/pages/Models'))
const ChartPage = lazy(() => import('@/pages/Chart'))
const Settings = lazy(() => import('@/pages/Settings'))

function PageFallback() {
  return (
    <div className="flex items-center justify-center py-32 text-ink-600 text-caption">
      Loading…
    </div>
  )
}

export default function App() {
  return (
    <>
      <Shell>
        <ErrorBoundary>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/trades" element={<Trades />} />
              <Route path="/models" element={<Models />} />
              <Route path="/chart" element={<ChartPage />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Dashboard />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </Shell>
      <CommandPalette />
      <ShortcutsOverlay />
      <TradeWatcher />
    </>
  )
}
