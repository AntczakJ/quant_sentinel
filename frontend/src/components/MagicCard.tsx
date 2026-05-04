import { useRef, type ReactNode } from 'react'

type Props = {
  children: ReactNode
  className?: string
  size?: number
}

/**
 * MagicCard — content with a rainbow gradient border that follows the
 * cursor on hover. Inspired by Magic UI / Linear card styling.
 *
 * The trick: use a 2-layer mask (content-box vs full) so the conic
 * gradient only shows as a thin border ring, and reveal it via
 * radial-gradient mask anchored to the cursor (--mx, --my CSS vars).
 */
export function MagicCard({ children, className = '', size = 220 }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)

  function onMove(e: React.MouseEvent<HTMLDivElement>) {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    el.style.setProperty('--mx', `${e.clientX - r.left}px`)
    el.style.setProperty('--my', `${e.clientY - r.top}px`)
  }

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      className={`group relative rounded-xl ${className}`}
      style={{
        ['--mx' as any]: '-200px',
        ['--my' as any]: '-200px',
      }}
    >
      {/* Animated border layer */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          padding: 1,
          background: `radial-gradient(${size}px circle at var(--mx) var(--my), rgba(212,175,55,0.65) 0%, rgba(244,214,118,0.5) 25%, rgba(59,130,246,0.45) 50%, rgba(34,197,94,0.4) 75%, transparent 100%)`,
          WebkitMask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
          mask: 'linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0)',
          WebkitMaskComposite: 'xor',
          maskComposite: 'exclude',
        }}
      />
      {/* Inner glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-xl opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{
          background: `radial-gradient(${size * 1.5}px circle at var(--mx) var(--my), rgba(212,175,55,0.10) 0%, transparent 60%)`,
        }}
      />
      <div className="relative">{children}</div>
    </div>
  )
}
