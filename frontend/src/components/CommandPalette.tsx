import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Command } from 'cmdk'
import { toast } from 'sonner'
import { api, type Trade } from '@/api/client'
import { playClick } from '@/lib/sound'

type Action = {
  id: string
  label: string
  hint?: string
  perform: () => void | Promise<void>
}

interface Props {
  /** Optional external open-state binding. When omitted, palette manages its own. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

export function CommandPalette({ open: controlled, onOpenChange }: Props = {}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const open = controlled ?? internalOpen
  const setOpen = (v: boolean) => {
    if (onOpenChange) onOpenChange(v)
    setInternalOpen(v)
  }

  const navigate = useNavigate()
  const qc = useQueryClient()

  // Mod+K to open, Esc to close (cmdk handles Esc internally too)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const go = (path: string) => {
    playClick()
    navigate(path, { viewTransition: true })
    setOpen(false)
  }

  const recent = (qc.getQueryData<Trade[]>(['trades-recent']) ?? []).slice(0, 5)

  const callScannerControl = async (mode: 'pause' | 'resume') => {
    try {
      const fn = mode === 'pause' ? api.scannerPause : api.scannerResume
      await fn()
      toast.success(`Scanner ${mode}d`, {
        description: mode === 'pause' ? 'No new setups will be opened.' : 'Background loop active.',
      })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        toast.warning('Scanner control endpoint missing', {
          description: `POST /api/scanner/${mode} is not implemented yet on the backend.`,
        })
      } else {
        toast.error(`Scanner ${mode} failed`, {
          description: (err as Error).message ?? 'Unknown error',
        })
      }
    }
    setOpen(false)
  }

  const refreshAll = () => {
    qc.invalidateQueries()
    toast.success('Refreshed', { description: 'All queries marked stale.' })
    setOpen(false)
  }

  const toggleReducedMotion = () => {
    const cur = localStorage.getItem('qs.reduced-motion-override')
    const next = cur === '1' ? '0' : '1'
    localStorage.setItem('qs.reduced-motion-override', next)
    toast.info(`Motion ${next === '1' ? 'reduced' : 'restored'}`, {
      description: 'Reload the page to apply globally.',
    })
    setOpen(false)
  }

  const previewGrid = async (grid = 'prod_v1') => {
    try {
      const p = await api.gridPreview(grid)
      const m = p.metrics
      const diffLines = p.diff
        .map((d) => `${d.param}: ${d.current ?? '—'} → ${d.winner ?? '—'}${d.change_pct != null ? ` (${d.change_pct >= 0 ? '+' : ''}${d.change_pct}%)` : ''}`)
        .join('\n')
      toast.info(`Grid winner: ${grid} · ${p.cell_hash?.slice(0, 8)}`, {
        description: `Sharpe ${m.sharpe_mean?.toFixed(2) ?? '—'} · PF ${m.profit_factor_mean?.toFixed(2) ?? '—'} · Ret ${m.return_pct_mean?.toFixed(2) ?? '—'}% · DD ${m.max_drawdown_pct_mean?.toFixed(2) ?? '—'}%\n\n${diffLines}`,
        duration: 12_000,
        action: {
          label: 'Apply',
          onClick: () => applyGrid(grid, p.cell_hash),
        },
      })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        toast.warning('No grid report found', {
          description: `Run scripts/run_production_backtest.py with grid name "${grid}" first.`,
        })
      } else {
        toast.error('Grid preview failed', { description: (err as Error).message ?? 'Unknown error' })
      }
    }
    setOpen(false)
  }

  const applyGrid = async (grid: string, cellHash?: string) => {
    try {
      const r = await api.gridApply(grid, cellHash, true)
      if (r.applied) {
        toast.success(`Applied grid winner ${r.cell_hash?.slice(0, 8)}`, {
          description: `Backup written to ${r.backup_path}. Restart scanner to pick up new params.`,
          duration: 12_000,
        })
        qc.invalidateQueries()
      } else {
        toast.warning('Apply not confirmed', { description: r.reason })
      }
    } catch (err) {
      toast.error('Grid apply failed', { description: (err as Error).message ?? 'Unknown error' })
    }
  }

  const actions: Action[] = [
    { id: 'scan-pause', label: 'Pause scanner', hint: 'Stop opening new positions', perform: () => callScannerControl('pause') },
    { id: 'scan-resume', label: 'Resume scanner', hint: 'Continue background loop', perform: () => callScannerControl('resume') },
    { id: 'grid-preview', label: 'Preview grid winner', hint: 'Show top cell diff (no write)', perform: () => previewGrid() },
    { id: 'refresh', label: 'Refresh all data', hint: 'Re-query every endpoint', perform: refreshAll },
    { id: 'motion', label: 'Toggle reduced motion', hint: 'Animation accessibility', perform: toggleReducedMotion },
  ]

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="palette-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[100] bg-black/50 backdrop-blur-md flex items-start justify-center pt-[12vh] px-4"
          onClick={() => setOpen(false)}
        >
          <motion.div
            key="palette-window"
            initial={{ opacity: 0, scale: 0.96, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-xl rounded-2xl border border-white/10 bg-ink-100/95 backdrop-blur-2xl shadow-lift overflow-hidden"
          >
            <Command label="Quant Sentinel command palette" className="flex flex-col">
              <div className="flex items-center gap-3 border-b border-white/[0.06] px-5 py-4">
                <kbd className="text-micro text-ink-600 font-mono uppercase tracking-wider">⌘K</kbd>
                <Command.Input
                  autoFocus
                  placeholder="Search pages, symbols, actions…"
                  className="flex-1 bg-transparent outline-none border-none text-body text-ink-900 placeholder:text-ink-500"
                />
                <button
                  onClick={() => setOpen(false)}
                  className="text-micro text-ink-600 hover:text-ink-800 uppercase tracking-wider"
                  aria-label="Close palette"
                >
                  Esc
                </button>
              </div>

              <Command.List className="max-h-[60vh] overflow-y-auto px-2 py-2">
                <Command.Empty className="py-10 text-center text-caption text-ink-600">
                  No matches.
                </Command.Empty>

                <Command.Group heading="Pages" className="px-2 pt-2 pb-1 text-micro uppercase tracking-wider text-ink-600">
                  {[
                    { p: '/', l: 'Dashboard', h: 'KPIs, recent signals, scanner' },
                    { p: '/chart', l: 'Chart', h: 'Live OHLCV candles' },
                    { p: '/trades', l: 'Trades', h: 'Full history, filterable' },
                    { p: '/models', l: 'Models', h: 'Voter ensemble + signal' },
                    { p: '/settings', l: 'Settings', h: 'API health, config, audio' },
                  ].map((x) => (
                    <PaletteItem key={x.p} value={`page ${x.l}`} label={x.l} hint={x.h} onSelect={() => go(x.p)} />
                  ))}
                </Command.Group>

                <Command.Group heading="Symbols" className="px-2 pt-3 pb-1 text-micro uppercase tracking-wider text-ink-600">
                  <PaletteItem value="symbol XAU/USD gold" label="XAU/USD" hint="Gold spot — primary" onSelect={() => go('/chart')} />
                  <PaletteItem value="symbol EUR/USD" label="EUR/USD" hint="Eurodollar reference" onSelect={() => go('/chart')} />
                  <PaletteItem value="symbol USD/JPY" label="USD/JPY" hint="Macro context proxy" onSelect={() => go('/chart')} />
                </Command.Group>

                {recent.length > 0 && (
                  <Command.Group heading="Recent trades" className="px-2 pt-3 pb-1 text-micro uppercase tracking-wider text-ink-600">
                    {recent.map((t) => {
                      const profit = t.profit != null ? (t.profit >= 0 ? `+${t.profit.toFixed(2)}` : t.profit.toFixed(2)) : '—'
                      return (
                        <PaletteItem
                          key={t.id}
                          value={`trade ${t.id} ${t.direction} ${t.pattern ?? ''}`}
                          label={`#${t.id} · ${t.direction} · ${profit}`}
                          hint={`${t.timeframe ?? '—'} · ${t.status}`}
                          onSelect={() => go('/trades')}
                        />
                      )
                    })}
                  </Command.Group>
                )}

                <Command.Group heading="Actions" className="px-2 pt-3 pb-1 text-micro uppercase tracking-wider text-ink-600">
                  {actions.map((a) => (
                    <PaletteItem key={a.id} value={`action ${a.label}`} label={a.label} hint={a.hint} onSelect={() => a.perform()} />
                  ))}
                </Command.Group>
              </Command.List>

              <div className="border-t border-white/[0.06] px-5 py-3 flex items-center justify-between text-micro text-ink-600 uppercase tracking-wider">
                <span className="flex items-center gap-2">
                  <kbd className="font-mono">↑↓</kbd> navigate
                  <kbd className="font-mono ml-3">↵</kbd> select
                </span>
                <span className="font-mono">v4.0</span>
              </div>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function PaletteItem({
  value,
  label,
  hint,
  onSelect,
}: {
  value: string
  label: string
  hint?: string
  onSelect: () => void
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex items-center justify-between px-3 py-2.5 mx-1 rounded-lg cursor-pointer text-body
                 text-ink-700 hover:text-ink-900
                 data-[selected=true]:bg-white/[0.06] data-[selected=true]:text-ink-900
                 transition-colors"
    >
      <span>{label}</span>
      {hint && <span className="text-caption text-ink-500">{hint}</span>}
    </Command.Item>
  )
}
