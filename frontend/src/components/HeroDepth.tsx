import { useRef, type ReactNode } from 'react'
import { motion, useScroll, useTransform, useSpring, useReducedMotion } from 'framer-motion'

/**
 * HeroDepth — Apple Card-style 3D depth on scroll.
 *
 * As the user scrolls past the Hero, the card:
 *   - tilts back (rotateX 0 → -8deg)
 *   - scales down (1 → 0.96)
 *   - blurs slightly (0 → 4px)
 *   - parallax-shifts up (0 → -40px)
 *
 * All driven by `useScroll` with spring smoothing. Honors reduced-motion.
 *
 * Wrap your existing Hero JSX inside <HeroDepth>...</HeroDepth>.
 */
export function HeroDepth({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start start', 'end start'],
  })

  const rotX = useSpring(useTransform(scrollYProgress, [0, 1], [0, -8]), {
    stiffness: 120, damping: 22,
  })
  const scale = useSpring(useTransform(scrollYProgress, [0, 1], [1, 0.96]), {
    stiffness: 120, damping: 22,
  })
  const y = useSpring(useTransform(scrollYProgress, [0, 1], [0, -40]), {
    stiffness: 120, damping: 22,
  })
  const blurPx = useTransform(scrollYProgress, [0, 1], [0, 4])
  const filter = useTransform(blurPx, (v) => `blur(${v}px)`)

  if (reduced) {
    return <div ref={ref} className={className}>{children}</div>
  }

  return (
    <div ref={ref} style={{ perspective: '1200px' }} className={className}>
      <motion.div
        style={{
          rotateX: rotX,
          scale,
          y,
          filter,
          transformStyle: 'preserve-3d',
          willChange: 'transform, filter',
        }}
      >
        {children}
      </motion.div>
    </div>
  )
}
