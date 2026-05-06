import { useRef, type ReactNode } from 'react'
import { motion, useScroll, useTransform, useSpring, useReducedMotion } from 'framer-motion'

type Props = {
  children: ReactNode
  /** Multiplier — 0 = no parallax, 1 = follows scroll, -1 = reverse, 0.3 = subtle drift */
  speed?: number
  className?: string
}

/**
 * ParallaxItem — wrap any child to make it drift at a fractional scroll
 * rate. Used in bento grids to give cards layered depth feel.
 *
 *   <ParallaxItem speed={0.2}>...</ParallaxItem>
 *   <ParallaxItem speed={-0.1}>...</ParallaxItem>  // floats opposite
 *
 * Spring-smoothed so movement is buttery, not janky.
 * Honors reduced-motion (renders children plain).
 */
export function ParallaxItem({ children, speed = 0.2, className = '' }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  })
  // -100 .. 100px range based on speed
  const y = useSpring(useTransform(scrollYProgress, [0, 1], [100 * speed, -100 * speed]), {
    stiffness: 90, damping: 20, mass: 0.5,
  })

  if (reduced) return <div className={className}>{children}</div>

  return (
    <motion.div ref={ref} style={{ y, willChange: 'transform' }} className={className}>
      {children}
    </motion.div>
  )
}
