import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'

/**
 * RouteTransitionOverlay — fires a slim gradient sweep across the viewport
 * on every route change. Sits above content (z-50), fully non-interactive.
 *
 * Visual: 100vw-wide diagonal gold/info gradient slab that flies in from
 * left, hits center peak (~70% opacity), exits right. ~480ms total.
 *
 * Pairs with the View Transitions API fade in globals.css — gives the
 * SPA a "production-grade" feel without blocking the user.
 */
export function RouteTransitionOverlay() {
  const loc = useLocation()
  const [bursting, setBursting] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    setBursting(true)
    setTick((n) => n + 1)
    const t = setTimeout(() => setBursting(false), 520)
    return () => clearTimeout(t)
  }, [loc.pathname])

  return (
    <AnimatePresence>
      {bursting && (
        <motion.div
          key={tick}
          aria-hidden
          initial={{ x: '-110vw', skewX: -18, opacity: 0 }}
          animate={{ x: '110vw', skewX: -18, opacity: [0, 0.55, 0] }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.52, ease: [0.65, 0, 0.35, 1], times: [0, 0.4, 1] }}
          className="pointer-events-none fixed inset-0 z-50 mix-blend-screen"
          style={{
            background:
              'linear-gradient(90deg, transparent 0%, rgba(212,175,55,0.18) 30%, rgba(244,214,118,0.28) 50%, rgba(59,130,246,0.18) 70%, transparent 100%)',
            filter: 'blur(2px)',
            width: '40vw',
          }}
        />
      )}
    </AnimatePresence>
  )
}
