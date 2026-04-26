import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

type Shortcut = { keys: string[]; label: string; hint?: string }

const GROUPS: Array<{ name: string; items: Shortcut[] }> = [
  {
    name: 'Command palette',
    items: [
      { keys: ['⌘', 'K'], label: 'Open palette', hint: 'Pages, symbols, scanner & grid actions' },
      { keys: ['Esc'],     label: 'Close palette / dialog' },
      { keys: ['↑', '↓'],  label: 'Navigate items' },
      { keys: ['⏎'],       label: 'Select item' },
    ],
  },
  {
    name: 'Pages (with palette open)',
    items: [
      { keys: ['type', 'dash'], label: 'Jump to Dashboard' },
      { keys: ['type', 'chart'], label: 'Jump to Chart' },
      { keys: ['type', 'trades'], label: 'Jump to Trades' },
      { keys: ['type', 'models'], label: 'Jump to Models' },
      { keys: ['type', 'set'], label: 'Jump to Settings' },
    ],
  },
  {
    name: 'Bento cards',
    items: [
      { keys: ['click'], label: 'Expand a KPI card', hint: 'Balance, Win Rate, P&L, Macro, Open positions' },
      { keys: ['Esc'],   label: 'Close expanded card' },
      { keys: ['click outside'], label: 'Close expanded card' },
    ],
  },
  {
    name: 'This overlay',
    items: [
      { keys: ['?'], label: 'Toggle shortcuts overlay' },
      { keys: ['Esc'], label: 'Close overlay' },
    ],
  },
]

export function ShortcutsOverlay() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't intercept while typing in form fields
      const t = e.target as HTMLElement | null
      const tag = t?.tagName?.toLowerCase()
      const isEditable =
        tag === 'input' || tag === 'textarea' || tag === 'select' ||
        (t?.isContentEditable ?? false)
      if (isEditable) return

      if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          key="shortcuts-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[95] bg-black/50 backdrop-blur-md flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          <motion.div
            key="shortcuts-window"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 4 }}
            transition={{ type: 'spring', stiffness: 380, damping: 32 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-2xl rounded-2xl border border-white/10 bg-ink-100/95 backdrop-blur-2xl shadow-lift overflow-hidden"
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <div>
                <div className="text-title font-display">Keyboard shortcuts</div>
                <div className="text-caption text-ink-600 mt-0.5">
                  Press <Key>?</Key> anywhere to toggle this overlay.
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="w-9 h-9 rounded-full border border-white/10 flex items-center justify-center text-ink-700 hover:text-ink-900 hover:bg-white/5 transition-all"
              >
                <span className="text-body">✕</span>
              </button>
            </div>

            <div className="max-h-[70vh] overflow-y-auto px-6 py-5 grid sm:grid-cols-2 gap-x-8 gap-y-6">
              {GROUPS.map((g) => (
                <div key={g.name}>
                  <div className="text-micro uppercase tracking-wider text-ink-600 mb-3">
                    {g.name}
                  </div>
                  <div className="flex flex-col gap-2.5">
                    {g.items.map((s, i) => (
                      <div key={i} className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="text-body text-ink-800 truncate">{s.label}</div>
                          {s.hint && (
                            <div className="text-caption text-ink-600 truncate">{s.hint}</div>
                          )}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {s.keys.map((k, j) => (
                            <Key key={j}>{k}</Key>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-white/[0.06] px-6 py-3 flex items-center justify-between text-micro text-ink-600 uppercase tracking-wider">
              <span>
                <Key>Esc</Key> close
              </span>
              <span className="font-mono">v4.x</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[24px] px-1.5 h-6 rounded-md border border-white/10 bg-white/[0.04] text-micro font-mono text-ink-800">
      {children}
    </kbd>
  )
}
