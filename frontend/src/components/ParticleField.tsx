import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { useReducedMotion } from '@/lib/useReducedMotion'

type Props = {
  count?: number
  className?: string
  variant?: 'gold' | 'cool' | 'mixed'
}

const PALETTES = {
  gold: ['#d4af37', '#f4d676', '#a8861f'],
  cool: ['#3b82f6', '#8b5cf6', '#22c55e'],
  mixed: ['#d4af37', '#3b82f6', '#22c55e', '#f4d676'],
}

/**
 * ParticleField — sparse floating dots with vertical drift + opacity pulse.
 * Lightweight (no canvas, no WebGL) — pure DOM with Motion `animate`. Each
 * particle gets randomized seed + duration so the field never looks looped.
 */
export function ParticleField({ count = 18, className = '', variant = 'mixed' }: Props) {
  const reduced = useReducedMotion()
  const colors = PALETTES[variant]
  const particles = useMemo(
    () =>
      Array.from({ length: count }).map((_, i) => ({
        id: i,
        x: Math.random() * 100,
        y: Math.random() * 100,
        size: 1 + Math.random() * 2.5,
        color: colors[i % colors.length],
        duration: 6 + Math.random() * 8,
        delay: Math.random() * 4,
        drift: 8 + Math.random() * 16,
      })),
    [count, colors],
  )

  // Reduced-motion: render static dots at half opacity, no animation loops
  if (reduced) {
    return (
      <div
        aria-hidden
        className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
      >
        {particles.slice(0, Math.min(8, particles.length)).map((p) => (
          <span
            key={p.id}
            className="absolute rounded-full"
            style={{
              left: `${p.x}%`,
              top: `${p.y}%`,
              width: p.size,
              height: p.size,
              background: p.color,
              opacity: 0.35,
            }}
          />
        ))}
      </div>
    )
  }

  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      {particles.map((p) => (
        <motion.span
          key={p.id}
          className="absolute rounded-full"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            background: p.color,
            boxShadow: `0 0 ${p.size * 3}px ${p.color}80`,
          }}
          animate={{
            y: [0, -p.drift, 0],
            opacity: [0.15, 0.7, 0.15],
          }}
          transition={{
            duration: p.duration,
            delay: p.delay,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  )
}
