import { useEffect, useRef, useState, type ReactNode } from 'react'
import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion'
import { useReducedMotion } from '@/lib/useReducedMotion'

type Props = {
  children: ReactNode
  className?: string
  intensity?: number
  glare?: boolean
}

export function TiltCard({ children, className = '', intensity = 8, glare = true }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)
  const reduced = useReducedMotion()
  const [finePointer, setFinePointer] = useState(true)
  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(pointer: fine)')
    setFinePointer(mq.matches)
    const handler = (e: MediaQueryListEvent) => setFinePointer(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  const mx = useMotionValue(0.5)
  const my = useMotionValue(0.5)

  const rx = useSpring(useTransform(my, [0, 1], [intensity, -intensity]), { stiffness: 220, damping: 22 })
  const ry = useSpring(useTransform(mx, [0, 1], [-intensity, intensity]), { stiffness: 220, damping: 22 })
  const glareX = useTransform(mx, (v) => `${v * 100}%`)
  const glareY = useTransform(my, (v) => `${v * 100}%`)

  function handleMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    mx.set((e.clientX - rect.left) / rect.width)
    my.set((e.clientY - rect.top) / rect.height)
  }
  function handleLeave() {
    mx.set(0.5)
    my.set(0.5)
  }

  // Touch / reduced-motion: render children plainly, no 3D transform stack
  if (reduced || !finePointer) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
      style={{
        rotateX: rx,
        rotateY: ry,
        transformStyle: 'preserve-3d',
        transformPerspective: 900,
      }}
      className={`relative will-change-transform ${className}`}
    >
      <div style={{ transform: 'translateZ(0)' }}>{children}</div>
      {glare && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[inherit]"
          style={{
            background: useTransform(
              [glareX, glareY] as any,
              ([gx, gy]: any) =>
                `radial-gradient(circle at ${gx} ${gy}, rgba(255,255,255,0.10), transparent 45%)`,
            ),
          }}
        />
      )}
    </motion.div>
  )
}
