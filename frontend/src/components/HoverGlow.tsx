import { useRef, type ReactNode } from 'react'

type Props = {
  children: ReactNode
  className?: string
  color?: string
  size?: number
}

/**
 * HoverGlow — radial gold glow that follows the cursor along the
 * inside of the wrapper. Looks like a moving spotlight tracing the
 * card. Pairs well with TiltCard or standalone on plain Cards.
 *
 * Implementation: 1 absolute layer + 2 CSS vars (--gx, --gy) updated
 * on mousemove. Pure CSS render, no React state churn.
 */
export function HoverGlow({
  children,
  className = '',
  color = 'rgba(212,175,55,0.18)',
  size = 260,
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null)

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    el.style.setProperty('--gx', `${e.clientX - r.left}px`)
    el.style.setProperty('--gy', `${e.clientY - r.top}px`)
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      className={`group relative ${className}`}
      style={{ ['--gx' as any]: '-200px', ['--gy' as any]: '-200px' }}
    >
      {children}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background: `radial-gradient(${size}px circle at var(--gx) var(--gy), ${color}, transparent 65%)`,
        }}
      />
    </div>
  )
}
