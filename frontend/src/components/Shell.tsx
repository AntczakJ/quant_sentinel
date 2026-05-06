import { type ReactNode, Suspense, lazy, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Logo } from './Logo'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { OfflineBanner } from './OfflineBanner'
import { ScrambleText } from './ScrambleText'
import { HealthDeepPopover } from './HealthDeepPopover'
import { ScrollProgress } from './ScrollProgress'
import { CursorFollower } from './CursorFollower'
import { CursorAura } from './CursorAura'
import { RouteTransitionOverlay } from './RouteTransitionOverlay'
import { LiveDot } from './LiveDot'
import { isSoundEnabled, setSoundEnabled, playClick } from '@/lib/sound'

// Lazy-load WebGL shader to avoid blocking initial paint on slower routes
const MeshBackground = lazy(() =>
  import('./MeshBackground').then((m) => ({ default: m.MeshBackground }))
)

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/chart', label: 'Chart' },
  { to: '/trades', label: 'Trades' },
  { to: '/models', label: 'Models' },
  { to: '/settings', label: 'Settings' },
]

export function Shell({ children }: { children: ReactNode }) {
  const loc = useLocation()
  const [navOpen, setNavOpen] = useState(false)
  const { data: health, isError } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })
  const apiOk = !isError && (health?.status === 'ok' || health?.status === 'healthy')

  // Disable shader on /chart route — frees GPU for lightweight-charts canvas
  const meshEnabled = !loc.pathname.startsWith('/chart')

  return (
    <div className="min-h-screen flex flex-col relative">
      {/* ─── Top scroll-progress bar ────────────────────────────────── */}
      <ScrollProgress />

      {/* ─── Page-wide gold ambient halo (cursor-following) ──────── */}
      <CursorAura />

      {/* ─── Magnetic cursor follower (gold dot + glow trail) ───────── */}
      <CursorFollower />

      {/* ─── Route transition gradient sweep ───────────────────────── */}
      <RouteTransitionOverlay />

      {/* ─── Cursor-reactive WebGL mesh background ──────────────────── */}
      <Suspense fallback={null}>
        <MeshBackground enabled={meshEnabled} />
      </Suspense>

      {/* ─── Top bar ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-white/[0.05] backdrop-blur-xl bg-ink-50/70">
        <div className="max-w-[1400px] mx-auto px-6 lg:px-10 h-16 flex items-center justify-between">
          {/* Brand */}
          <Link to="/" viewTransition className="flex items-center gap-3 group">
            <Logo />
            <div>
              <div className="text-title font-display tracking-tight">
                <ScrambleText text="Quant Sentinel" duration={650} />
              </div>
              <div className="text-micro text-ink-600 group-hover:text-ink-700 transition-colors">
                <ScrambleText text="XAU/USD" duration={500} />
              </div>
            </div>
          </Link>

          {/* Nav (desktop) */}
          <nav className="hidden md:flex items-center gap-1">
            {NAV.map((n) => {
              const active = loc.pathname === n.to || (n.to !== '/' && loc.pathname.startsWith(n.to))
              return (
                <Link
                  key={n.to}
                  to={n.to}
                  viewTransition
                  className={`relative px-4 py-2 text-body transition-colors ${
                    active ? 'text-ink-900' : 'text-ink-600 hover:text-ink-800'
                  }`}
                >
                  {n.label}
                  {active && (
                    <motion.div
                      layoutId="nav-active"
                      className="absolute inset-0 bg-white/[0.06] rounded-full -z-10"
                      transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                    />
                  )}
                </Link>
              )
            })}
          </nav>

          {/* Health pill + Cmd+K hint + sound toggle */}
          <div className="flex items-center gap-3">
            {apiOk && (
              <span
                className="hidden md:inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-bull/30 bg-bull/[0.06]"
                title="Scanner active — backend reachable"
              >
                <LiveDot color="bull" />
                <span className="text-micro uppercase tracking-wider text-bull">Scanner</span>
              </span>
            )}
            <button
              type="button"
              onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))}
              className="hidden md:inline-flex items-center gap-2 px-2.5 py-1 rounded-full border border-white/[0.08] bg-white/[0.02] text-micro text-ink-600 uppercase tracking-wider hover:border-white/20 hover:text-ink-800 transition-all"
              title="Open command palette (⌘K)"
            >
              <kbd className="font-mono text-ink-700">⌘K</kbd>
              <span>quick</span>
            </button>
            <SoundToggle />
            <HealthDeepPopover />
            <button
              type="button"
              onClick={() => setNavOpen((v) => !v)}
              className="md:hidden w-10 h-10 rounded-full border border-white/10 flex items-center justify-center hover:bg-white/5"
              aria-label="Toggle nav"
            >
              <span className="block w-4 h-px bg-white relative before:absolute before:content-[''] before:w-4 before:h-px before:bg-white before:-top-1.5 after:absolute after:content-[''] after:w-4 after:h-px after:bg-white after:top-1.5" />
            </button>
          </div>
        </div>

        {/* Mobile nav drawer */}
        <AnimatePresence>
          {navOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="md:hidden border-t border-white/[0.05] overflow-hidden"
            >
              <div className="px-6 py-3 flex flex-col gap-1">
                {NAV.map((n) => (
                  <Link
                    key={n.to}
                    to={n.to}
                    viewTransition
                    onClick={() => setNavOpen(false)}
                    className={`px-3 py-3 rounded-xl text-body ${
                      loc.pathname === n.to ? 'bg-white/[0.06] text-ink-900' : 'text-ink-600'
                    }`}
                  >
                    {n.label}
                  </Link>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      {/* ─── Offline banner ──────────────────────────────────────────── */}
      <OfflineBanner show={!apiOk} />

      {/* ─── Main content ────────────────────────────────────────────── */}
      <main className="flex-1">
        <div className="max-w-[1400px] mx-auto px-6 lg:px-10 py-10 lg:py-14">{children}</div>
      </main>

      {/* ─── Footer ──────────────────────────────────────────────────── */}
      <footer className="border-t border-white/[0.04] mt-16 py-8">
        <div className="max-w-[1400px] mx-auto px-6 lg:px-10 flex flex-col md:flex-row gap-2 justify-between text-caption text-ink-600">
          <div>© 2026 Quant Sentinel — autonomous gold trading.</div>
          <div className="font-mono text-micro tracking-wider">
            v3.0 · {health?.data_provider ?? 'idle'}
          </div>
        </div>
      </footer>
    </div>
  )
}

// ─── Sound toggle (inline, only used here) ───────────────────────────
function SoundToggle() {
  const [on, setOn] = useState(false)
  useEffect(() => setOn(isSoundEnabled()), [])
  return (
    <button
      type="button"
      onClick={() => {
        const next = !on
        setSoundEnabled(next)
        setOn(next)
        // Play a confirmation tick *after* enabling so the user hears it
        if (next) setTimeout(() => playClick(), 30)
      }}
      title={on ? 'Sound feedback: ON' : 'Sound feedback: OFF'}
      aria-label="Toggle sound"
      className={`hidden md:inline-flex items-center justify-center w-9 h-9 rounded-full border transition-all ${
        on
          ? 'bg-gold-500/[0.08] border-gold-500/30 text-gold-400 shadow-glow-gold'
          : 'bg-white/[0.02] border-white/[0.08] text-ink-600 hover:text-ink-800 hover:border-white/20'
      }`}
    >
      {on ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
          <path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
          <line x1="22" y1="9" x2="16" y2="15" />
          <line x1="16" y1="9" x2="22" y2="15" />
        </svg>
      )}
    </button>
  )
}
