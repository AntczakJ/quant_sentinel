import { type RefObject, useEffect, useId, useState } from 'react'
import { motion } from 'framer-motion'
import { useReducedMotion } from '@/lib/useReducedMotion'

interface Props {
  containerRef: RefObject<HTMLElement>
  fromRef: RefObject<HTMLElement>
  toRef: RefObject<HTMLElement>
  curvature?: number
  pathColor?: string
  pathWidth?: number
  pathOpacity?: number
  gradientStartColor?: string
  gradientStopColor?: string
  duration?: number
  delay?: number
  reverse?: boolean
  startXOffset?: number
  startYOffset?: number
  endXOffset?: number
  endYOffset?: number
  /** Visual emphasis 0..1 — scales beam opacity + width. */
  intensity?: number
  /** Anchor on the source element. Default 'center'. */
  fromAnchor?: 'center' | 'left' | 'right' | 'top' | 'bottom'
  /** Anchor on the target element. Default 'center'. */
  toAnchor?: 'center' | 'left' | 'right' | 'top' | 'bottom'
}

/**
 * AnimatedBeam — port of Magic UI's beam component, simplified for our case.
 * Renders an SVG curve between two refs, with an animated gradient "particle"
 * sliding along the path. Used on the Models page to visualize voter → ensemble.
 */
export function AnimatedBeam({
  containerRef,
  fromRef,
  toRef,
  curvature = -60,
  pathColor = 'rgba(255,255,255,0.12)',
  pathWidth = 2,
  pathOpacity = 0.6,
  gradientStartColor = '#d4af37',
  gradientStopColor = '#3b82f6',
  duration = 4.5,
  delay = 0,
  reverse = false,
  startXOffset = 0,
  startYOffset = 0,
  endXOffset = 0,
  endYOffset = 0,
  intensity = 1,
  fromAnchor = 'center',
  toAnchor = 'center',
}: Props) {
  const id = useId()
  const reduced = useReducedMotion()
  const [pathD, setPathD] = useState('')
  const [svgDim, setSvgDim] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const updatePath = () => {
      if (!containerRef.current || !fromRef.current || !toRef.current) return
      const cRect = containerRef.current.getBoundingClientRect()
      const fRect = fromRef.current.getBoundingClientRect()
      const tRect = toRef.current.getBoundingClientRect()

      const w = cRect.width
      const h = cRect.height
      setSvgDim({ width: w, height: h })

      // Anchor helper — picks the requested edge or center on a rect
      const anchor = (rect: DOMRect, where: typeof fromAnchor) => {
        const cx = rect.left + rect.width / 2
        const cy = rect.top + rect.height / 2
        switch (where) {
          case 'left':   return { x: rect.left,            y: cy }
          case 'right':  return { x: rect.right,           y: cy }
          case 'top':    return { x: cx,                   y: rect.top }
          case 'bottom': return { x: cx,                   y: rect.bottom }
          default:       return { x: cx,                   y: cy }
        }
      }
      const fAnch = anchor(fRect, fromAnchor)
      const tAnch = anchor(tRect, toAnchor)

      const fx = fAnch.x - cRect.left + startXOffset
      const fy = fAnch.y - cRect.top  + startYOffset
      const tx = tAnch.x - cRect.left + endXOffset
      const ty = tAnch.y - cRect.top  + endYOffset

      // Quadratic Bezier with adjustable curvature
      const cx = (fx + tx) / 2
      const cy = (fy + ty) / 2 + curvature

      setPathD(`M ${fx},${fy} Q ${cx},${cy} ${tx},${ty}`)
    }

    updatePath()
    const ro = new ResizeObserver(updatePath)
    if (containerRef.current) ro.observe(containerRef.current)
    if (fromRef.current) ro.observe(fromRef.current)
    if (toRef.current) ro.observe(toRef.current)
    window.addEventListener('resize', updatePath)
    // Re-measure on next frame to handle layout settle
    const raf = requestAnimationFrame(updatePath)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', updatePath)
      cancelAnimationFrame(raf)
    }
  }, [containerRef, fromRef, toRef, curvature, startXOffset, startYOffset, endXOffset, endYOffset])

  if (!pathD) return null

  return (
    <svg
      width={svgDim.width}
      height={svgDim.height}
      className="pointer-events-none absolute left-0 top-0"
      style={{ opacity: Math.max(0.2, Math.min(1, intensity)) }}
      aria-hidden
    >
      {/* Static base path */}
      <path
        d={pathD}
        stroke={pathColor}
        strokeWidth={pathWidth}
        strokeOpacity={pathOpacity}
        strokeLinecap="round"
        fill="none"
      />
      {/* Animated gradient stop traveling along the path */}
      <defs>
        <linearGradient id={`beam-${id}`} gradientUnits="userSpaceOnUse">
          <stop stopColor={gradientStartColor} stopOpacity="0" />
          <stop offset="0.45" stopColor={gradientStartColor} />
          <stop offset="0.55" stopColor={gradientStopColor} />
          <stop offset="1" stopColor={gradientStopColor} stopOpacity="0" />
          {!reduced && (
            <>
              <animate
                attributeName="x1"
                values={reverse ? '120%; -20%' : '-20%; 120%'}
                dur={`${duration}s`}
                begin={`${delay}s`}
                repeatCount="indefinite"
              />
              <animate
                attributeName="x2"
                values={reverse ? '100%; -40%' : '-40%; 100%'}
                dur={`${duration}s`}
                begin={`${delay}s`}
                repeatCount="indefinite"
              />
            </>
          )}
        </linearGradient>
      </defs>
      <motion.path
        d={pathD}
        stroke={`url(#beam-${id})`}
        strokeWidth={pathWidth + 1}
        strokeLinecap="round"
        fill="none"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.8, delay, ease: 'easeOut' }}
      />
    </svg>
  )
}
