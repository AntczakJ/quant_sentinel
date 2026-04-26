import { type ReactNode, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Logo } from './Logo'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

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
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })
  const apiOk = health?.status === 'ok' || health?.status === 'healthy'

  return (
    <div className="min-h-screen flex flex-col">
      {/* ─── Top bar ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-white/[0.05] backdrop-blur-xl bg-ink-50/70">
        <div className="max-w-[1400px] mx-auto px-6 lg:px-10 h-16 flex items-center justify-between">
          {/* Brand */}
          <Link to="/" className="flex items-center gap-3 group">
            <Logo />
            <div>
              <div className="text-title font-display tracking-tight">Quant Sentinel</div>
              <div className="text-micro text-ink-600 group-hover:text-ink-700 transition-colors">XAU/USD</div>
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

          {/* Health pill */}
          <div className="flex items-center gap-3">
            <div
              className={`pill ${apiOk ? 'border-bull/30 bg-bull/[0.08] text-bull' : 'border-bear/30 bg-bear/[0.08] text-bear'}`}
              title={health ? `API: ${health.status}` : 'API: unknown'}
            >
              <span
                className={`inline-block w-1.5 h-1.5 rounded-full ${apiOk ? 'bg-bull' : 'bg-bear'}`}
                style={{ boxShadow: apiOk ? '0 0 8px currentColor' : 'none' }}
              />
              {apiOk ? 'live' : 'down'}
            </div>
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
