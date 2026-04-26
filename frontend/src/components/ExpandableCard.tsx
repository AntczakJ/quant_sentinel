import { type ReactNode, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

interface Props {
  /** Unique id used for Motion `layoutId` morph. Must be stable. */
  id: string
  /** Collapsed content rendered in the bento grid. */
  children: ReactNode
  /** Expanded detail rendered in the modal overlay. Optional — when omitted,
   *  the card renders without click-to-expand behavior. */
  detail?: ReactNode
  /** Optional title shown on the expanded view. */
  detailTitle?: string
  /** Tailwind class for the collapsed shell. */
  className?: string
  /** Subtle directional glow on hover. */
  accent?: 'gold' | 'bull' | 'bear' | 'info' | 'none'
}

const accentShadow: Record<NonNullable<Props['accent']>, string> = {
  gold: 'hover:shadow-glow-gold',
  bull: 'hover:shadow-glow-bull',
  bear: 'hover:shadow-glow-bear',
  info: 'hover:shadow-glow-info',
  none: 'hover:shadow-lift',
}

/**
 * Bento-style card. Click → expands to a fullscreen modal with shared
 * `layoutId` morph. Esc + click-outside closes. If `detail` is omitted,
 * the card is non-interactive (just a styled tile).
 */
export function ExpandableCard({
  id,
  children,
  detail,
  detailTitle,
  className = '',
  accent = 'none',
}: Props) {
  const [open, setOpen] = useState(false)
  const interactive = Boolean(detail)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open])

  return (
    <>
      <motion.div
        layoutId={`bento-${id}`}
        onClick={interactive ? () => setOpen(true) : undefined}
        whileHover={interactive ? { y: -2 } : undefined}
        transition={{ type: 'spring', stiffness: 380, damping: 32 }}
        className={`
          relative overflow-hidden rounded-xl2
          bg-ink-100 border border-white/[0.06] shadow-soft
          transition-all duration-300
          ${interactive ? `cursor-pointer ${accentShadow[accent]} hover:border-white/15` : ''}
          ${className}
        `}
      >
        {children}
      </motion.div>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              key="bento-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-[90] bg-black/60 backdrop-blur-md"
            />
            <div className="fixed inset-0 z-[91] flex items-center justify-center p-6 pointer-events-none">
              <motion.div
                layoutId={`bento-${id}`}
                transition={{ type: 'spring', stiffness: 320, damping: 32 }}
                className="relative w-full max-w-4xl max-h-[88vh] overflow-y-auto rounded-xl3
                           bg-ink-100/95 backdrop-blur-2xl border border-white/10 shadow-lift
                           pointer-events-auto"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="sticky top-0 z-10 flex items-center justify-between
                                px-7 py-4 border-b border-white/[0.06]
                                bg-ink-100/80 backdrop-blur-xl">
                  <div className="text-title font-display text-ink-900">
                    {detailTitle ?? 'Detail'}
                  </div>
                  <button
                    onClick={() => setOpen(false)}
                    aria-label="Close"
                    className="w-9 h-9 rounded-full border border-white/10 flex items-center justify-center
                               text-ink-700 hover:text-ink-900 hover:bg-white/5 transition-all"
                  >
                    <span className="text-body">✕</span>
                  </button>
                </div>
                <div className="p-7">{detail}</div>
              </motion.div>
            </div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
