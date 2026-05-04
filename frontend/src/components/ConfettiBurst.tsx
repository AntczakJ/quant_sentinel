import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useReducedMotion } from '@/lib/useReducedMotion'

type Particle = {
  id: number
  x: number
  y: number
  rot: number
  hue: number
}

type Props = {
  trigger: number  // increment to fire a new burst
  count?: number
  origin?: { x: string; y: string }
}

const COLORS = ['#d4af37', '#22c55e', '#3b82f6', '#f4d676', '#a8861f']

export function ConfettiBurst({ trigger, count = 24, origin = { x: '50%', y: '50%' } }: Props) {
  const reduced = useReducedMotion()
  const [parts, setParts] = useState<Particle[]>([])

  useEffect(() => {
    if (trigger <= 0 || reduced) return
    const next: Particle[] = Array.from({ length: count }).map((_, i) => ({
      id: trigger * 1000 + i,
      x: (Math.random() - 0.5) * 360,
      y: (Math.random() - 0.5) * 240 - 80,
      rot: Math.random() * 720 - 360,
      hue: i % COLORS.length,
    }))
    setParts(next)
    const t = setTimeout(() => setParts([]), 1600)
    return () => clearTimeout(t)
  }, [trigger, count, reduced])

  if (reduced) return null

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 overflow-visible"
      style={{ left: origin.x, top: origin.y }}
    >
      <AnimatePresence>
        {parts.map((p) => (
          <motion.span
            key={p.id}
            initial={{ x: 0, y: 0, opacity: 1, rotate: 0, scale: 0.4 }}
            animate={{ x: p.x, y: p.y, opacity: 0, rotate: p.rot, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.4, ease: [0.22, 1, 0.36, 1] }}
            className="absolute block h-2 w-2 rounded-[2px]"
            style={{
              background: COLORS[p.hue],
              boxShadow: `0 0 8px ${COLORS[p.hue]}80`,
            }}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}
