import { useEffect, useState } from 'react'
import { motion, useMotionValue, useSpring } from 'framer-motion'

/**
 * CursorFollower — soft glow + small dot that lags behind the system cursor
 * with spring physics. Hides on touch devices and respects prefers-reduced-motion.
 *
 * Mounted once at the Shell level, always-on, very cheap (2 motion divs).
 */
export function CursorFollower() {
  const [enabled, setEnabled] = useState(false)
  const [hovering, setHovering] = useState(false)
  const x = useMotionValue(-200)
  const y = useMotionValue(-200)

  // Two springs: dot is snappier, glow lags slightly for trail effect
  const dotX = useSpring(x, { stiffness: 480, damping: 32, mass: 0.4 })
  const dotY = useSpring(y, { stiffness: 480, damping: 32, mass: 0.4 })
  const glowX = useSpring(x, { stiffness: 120, damping: 22, mass: 0.6 })
  const glowY = useSpring(y, { stiffness: 120, damping: 22, mass: 0.6 })

  useEffect(() => {
    // Skip on touch / coarse pointer + reduced motion
    if (typeof window === 'undefined') return
    const mql = window.matchMedia('(pointer: fine)')
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (!mql.matches || reduce.matches) return
    setEnabled(true)

    const onMove = (e: MouseEvent) => {
      x.set(e.clientX)
      y.set(e.clientY)
    }
    const onOver = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null
      if (!t) return
      // Treat clickables / interactive elements as "magnetic"
      const isInteractive =
        t.closest('a, button, [role="button"], input, select, textarea, [data-magnetic]') !== null
      setHovering(isInteractive)
    }
    const onOut = () => setHovering(false)

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseover', onOver)
    window.addEventListener('mouseout', onOut)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseover', onOver)
      window.removeEventListener('mouseout', onOut)
    }
  }, [x, y])

  if (!enabled) return null

  return (
    <>
      <motion.div
        aria-hidden
        className="pointer-events-none fixed top-0 left-0 z-[80] mix-blend-screen"
        style={{
          x: glowX,
          y: glowY,
          width: hovering ? 64 : 36,
          height: hovering ? 64 : 36,
          marginLeft: hovering ? -32 : -18,
          marginTop: hovering ? -32 : -18,
          borderRadius: '50%',
          background:
            'radial-gradient(circle, rgba(212,175,55,0.42) 0%, rgba(212,175,55,0.10) 50%, transparent 75%)',
          filter: 'blur(6px)',
          transition: 'width 200ms ease-out, height 200ms ease-out, margin 200ms ease-out',
        }}
      />
      <motion.div
        aria-hidden
        className="pointer-events-none fixed top-0 left-0 z-[81]"
        style={{
          x: dotX,
          y: dotY,
          width: hovering ? 10 : 6,
          height: hovering ? 10 : 6,
          marginLeft: hovering ? -5 : -3,
          marginTop: hovering ? -5 : -3,
          borderRadius: '50%',
          background: hovering ? '#f4d676' : '#d4af37',
          boxShadow:
            '0 0 8px rgba(212,175,55,0.55), 0 0 18px rgba(212,175,55,0.25)',
          transition: 'width 180ms ease-out, height 180ms ease-out, margin 180ms ease-out, background 200ms ease',
        }}
      />
    </>
  )
}
