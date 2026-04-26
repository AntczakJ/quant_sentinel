import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { api } from '@/api/client'

/**
 * Click-to-open popover anchored beside the live/down pill in Shell.
 * Renders /api/system/health/deep so the operator can see at a glance
 * which subsystem is failing without opening the Settings page.
 *
 * Closes on outside click, Esc, or selecting another action.
 */
export function HealthDeepPopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)

  const { data } = useQuery({
    queryKey: ['health-deep'],
    queryFn: api.healthDeep,
    refetchInterval: open ? 5_000 : 30_000,
    staleTime: 4_000,
  })

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const allOk = data?.all_ok ?? null
  const failed = data ? Object.entries(data.checks).filter(([, v]) => !v.ok) : []

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Subsystem health (click for detail)"
        className={`pill transition-colors ${
          allOk === null ? '' : allOk ? 'border-bull/30 bg-bull/[0.08] text-bull' : 'border-bear/30 bg-bear/[0.08] text-bear'
        }`}
      >
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full ${
            allOk === null ? 'bg-ink-600' : allOk ? 'bg-bull animate-pulse-glow' : 'bg-bear'
          }`}
          style={{ boxShadow: allOk ? '0 0 8px currentColor' : 'none' }}
        />
        {allOk === null ? '…' : allOk ? 'all systems' : `${failed.length} fail`}
      </button>

      <AnimatePresence>
        {open && data && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="absolute right-0 mt-2 w-80 rounded-xl2 border border-white/10 bg-ink-100/95 backdrop-blur-2xl shadow-lift overflow-hidden z-50"
          >
            <div className="px-4 py-3 border-b border-white/[0.06]">
              <div className="text-micro uppercase tracking-wider text-ink-600">Health · deep</div>
              <div className={`text-body font-medium mt-0.5 ${data.all_ok ? 'text-bull' : 'text-bear'}`}>
                {data.all_ok ? 'All subsystems OK' : `${failed.length} subsystem${failed.length === 1 ? '' : 's'} failing`}
              </div>
            </div>
            <div className="py-2">
              {Object.entries(data.checks).map(([name, c]) => (
                <div
                  key={name}
                  className="px-4 py-2 flex items-center justify-between gap-3 hover:bg-white/[0.02]"
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        c.ok ? 'bg-bull' : 'bg-bear'
                      }`}
                    />
                    <span className="text-caption uppercase tracking-wider text-ink-700 shrink-0">{name}</span>
                  </div>
                  <span className="text-caption text-ink-600 truncate ml-3">
                    {c.message ?? '—'}
                  </span>
                </div>
              ))}
            </div>
            <div className="px-4 py-2 border-t border-white/[0.06] text-micro text-ink-600">
              Auto-refresh 5 s while open
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
