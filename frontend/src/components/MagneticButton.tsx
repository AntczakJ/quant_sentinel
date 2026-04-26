import { type ReactNode, forwardRef, useCallback, useRef } from 'react'
import {
  type HTMLMotionProps,
  motion,
  useMotionValue,
  useSpring,
  useTransform,
} from 'framer-motion'
import { useReducedMotion } from '@/lib/useReducedMotion'

interface Props extends Omit<HTMLMotionProps<'button'>, 'children'> {
  /** Magnet strength: 0–1. 0.2 = subtle (default), 0.5 = strong CTA, 0 = none. */
  strength?: number
  children: ReactNode
}

/**
 * Premium "magnetic" button — smoothly tracks cursor on hover with a spring,
 * adds a tactile `whileTap` scale-down. Reduced-motion-safe.
 */
export const MagneticButton = forwardRef<HTMLButtonElement, Props>(function MagneticButton(
  { strength = 0.22, children, className = '', onMouseLeave, ...rest },
  ref,
) {
  const reduced = useReducedMotion()
  const innerRef = useRef<HTMLButtonElement | null>(null)

  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const springX = useSpring(x, { stiffness: 220, damping: 18, mass: 0.4 })
  const springY = useSpring(y, { stiffness: 220, damping: 18, mass: 0.4 })

  // Subtle tilt on hover, derived from translation
  const rotateX = useTransform(springY, [-30, 30], [4, -4])
  const rotateY = useTransform(springX, [-30, 30], [-4, 4])

  const handleMove = useCallback(
    (e: MouseEvent | React.MouseEvent<HTMLButtonElement>) => {
      if (reduced || strength === 0) return
      const el = innerRef.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const cx = rect.left + rect.width / 2
      const cy = rect.top + rect.height / 2
      x.set((e.clientX - cx) * strength)
      y.set((e.clientY - cy) * strength)
    },
    [reduced, strength, x, y],
  )

  const handleLeave = useCallback(
    (e: MouseEvent | React.MouseEvent<HTMLButtonElement>) => {
      x.set(0)
      y.set(0)
      onMouseLeave?.(e as React.MouseEvent<HTMLButtonElement>)
    },
    [onMouseLeave, x, y],
  )

  // Allow forwarded ref + local ref via callback
  const setRef = (node: HTMLButtonElement | null) => {
    innerRef.current = node
    if (typeof ref === 'function') ref(node)
    else if (ref) (ref as React.MutableRefObject<HTMLButtonElement | null>).current = node
  }

  return (
    <motion.button
      ref={setRef}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      whileTap={reduced ? undefined : { scale: 0.96 }}
      style={{
        x: springX,
        y: springY,
        rotateX: reduced ? 0 : rotateX,
        rotateY: reduced ? 0 : rotateY,
        transformPerspective: 600,
      }}
      className={className}
      {...rest}
    >
      {children}
    </motion.button>
  )
})
