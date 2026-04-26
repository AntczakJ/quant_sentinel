import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '@/lib/useReducedMotion'

interface Props {
  /** Numeric value to compare. Direction of flash is derived from change sign. */
  value: number | string | null | undefined
  children: ReactNode
  className?: string
  /** Override auto-detection — force bull/bear flash regardless of direction. */
  forceDirection?: 'bull' | 'bear'
  /** Don't flash on the very first paint (avoids highlighting initial render). */
  skipFirst?: boolean
}

/**
 * Wraps any child and pulses a brief bull/bear background flash whenever
 * the `value` prop changes. Intended for live trading numerics
 * (price ticks, P&L, equity).
 */
export function FlashOnChange({
  value,
  children,
  className = '',
  forceDirection,
  skipFirst = true,
}: Props) {
  const prevRef = useRef<typeof value>(value)
  const [flash, setFlash] = useState<'bull' | 'bear' | null>(null)
  const reduced = useReducedMotion()
  const seenRef = useRef(false)

  useEffect(() => {
    if (reduced) return
    if (skipFirst && !seenRef.current) {
      seenRef.current = true
      prevRef.current = value
      return
    }
    if (value === prevRef.current) return
    if (value == null || prevRef.current == null) {
      prevRef.current = value
      return
    }
    let dir: 'bull' | 'bear' | null = forceDirection ?? null
    if (!dir && typeof value === 'number' && typeof prevRef.current === 'number') {
      dir = value > prevRef.current ? 'bull' : value < prevRef.current ? 'bear' : null
    } else if (!dir) {
      dir = 'bull'
    }
    if (dir) {
      setFlash(dir)
      const t = setTimeout(() => setFlash(null), 700)
      prevRef.current = value
      return () => clearTimeout(t)
    }
    prevRef.current = value
  }, [value, forceDirection, reduced, skipFirst])

  return (
    <span
      className={`relative inline-block rounded-lg px-1 -mx-1 ${
        flash === 'bull' ? 'flash-bull' : flash === 'bear' ? 'flash-bear' : ''
      } ${className}`}
    >
      {children}
    </span>
  )
}
