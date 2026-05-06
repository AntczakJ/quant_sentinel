import { useEffect, useRef } from 'react'

/**
 * CursorAura — full-viewport radial gold halo that follows the cursor.
 * Different from CursorFollower (small dot+trail) — this is the AMBIENT
 * page-wide accent. Top-tier 2026 pattern (Linear, Vercel, Stripe).
 *
 * Pure CSS via CSS variables; no framer overhead. Updates --aura-x/y
 * on mousemove via direct DOM mutation (no React re-render churn).
 *
 * Disabled on touch / reduced-motion via match-media at mount.
 */
export function CursorAura() {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    const fine = window.matchMedia('(pointer: fine)')
    if (reduce.matches || !fine.matches) return

    const el = ref.current
    if (!el) return

    let raf = 0
    let tx = window.innerWidth / 2
    let ty = window.innerHeight / 2
    let cx = tx
    let cy = ty

    const handleMove = (e: MouseEvent) => {
      tx = e.clientX
      ty = e.clientY
    }

    const tick = () => {
      // Smooth follow with lerp (~0.08 = soft trail)
      cx += (tx - cx) * 0.08
      cy += (ty - cy) * 0.08
      el.style.setProperty('--aura-x', `${cx}px`)
      el.style.setProperty('--aura-y', `${cy}px`)
      raf = requestAnimationFrame(tick)
    }

    window.addEventListener('mousemove', handleMove, { passive: true })
    raf = requestAnimationFrame(tick)

    return () => {
      window.removeEventListener('mousemove', handleMove)
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <div
      ref={ref}
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[5] mix-blend-screen"
      style={{
        background: `
          radial-gradient(
            500px circle at var(--aura-x, 50%) var(--aura-y, 50%),
            rgba(212, 175, 55, 0.12),
            rgba(212, 175, 55, 0.04) 35%,
            transparent 65%
          )
        `,
      }}
    />
  )
}
