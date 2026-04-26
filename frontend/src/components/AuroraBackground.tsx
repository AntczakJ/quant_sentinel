import { useReducedMotion } from '@/lib/useReducedMotion'

interface Props {
  /** Container needs `position: relative` and `overflow: hidden`. */
  className?: string
  intensity?: number
}

/**
 * Pure-CSS animated aurora gradient. Drop into any container that owns
 * `position: relative` + `overflow: hidden`. Mostly used on Settings and
 * empty states. The reduced-motion variant keeps the gradient but freezes it.
 */
export function AuroraBackground({ className = '', intensity = 1 }: Props) {
  const reduced = useReducedMotion()
  return (
    <div
      aria-hidden
      className={`aurora-bg ${className}`}
      style={{
        opacity: 0.42 * intensity,
        animationPlayState: reduced ? 'paused' : 'running',
      }}
    />
  )
}
