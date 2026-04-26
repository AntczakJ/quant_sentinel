import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '@/lib/useReducedMotion'

const SCRAMBLE_POOL = '!<>-_\\/[]{}—=+*^?#§$%&'

interface Props {
  text: string
  /** Total reveal duration in ms (each character settles at i/length·duration). */
  duration?: number
  /** Optional trigger — when false, displays final text. */
  trigger?: boolean
  className?: string
  /** Custom inline style. */
  style?: React.CSSProperties
}

/**
 * Letter-scrambled reveal. Each character cycles through random
 * `SCRAMBLE_POOL` glyphs until its "settle time" (proportional to its index)
 * elapses, then snaps to the final character. Pure rAF, no deps. Respects
 * reduced motion.
 */
export function ScrambleText({
  text,
  duration = 700,
  trigger = true,
  className,
  style,
}: Props) {
  const [display, setDisplay] = useState(text)
  const reduced = useReducedMotion()
  const startedRef = useRef(false)

  useEffect(() => {
    if (!trigger) return
    if (reduced) {
      setDisplay(text)
      return
    }
    if (startedRef.current) return
    startedRef.current = true

    const start = performance.now()
    let raf = 0
    const len = Math.max(1, text.length - 1)

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const out = text
        .split('')
        .map((ch, i) => {
          if (ch === ' ') return ' '
          const settle = i / len
          if (t >= settle) return ch
          return SCRAMBLE_POOL[Math.floor(Math.random() * SCRAMBLE_POOL.length)]
        })
        .join('')
      setDisplay(out)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [text, trigger, duration, reduced])

  return (
    <span className={className} style={style}>
      {display}
    </span>
  )
}
