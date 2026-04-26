import { useEffect, useState } from 'react'
import { MeshGradient } from '@paper-design/shaders-react'
import { useReducedMotion } from '@/lib/useReducedMotion'

/**
 * Cursor-reactive WebGL mesh-gradient background, mounted globally in <Shell />.
 *
 * - Pinned `position: fixed`, `pointer-events: none`, `z-index: -1`.
 * - Cursor follows via `offsetX/offsetY` shader uniforms (subtle parallax).
 * - Disabled when `prefers-reduced-motion: reduce` — falls back to body
 *   gradient already defined in `globals.css`.
 * - Optionally suppressable via `enabled` prop (Chart route turns it off
 *   to avoid GPU contention with lightweight-charts canvas).
 */
export function MeshBackground({ enabled = true }: { enabled?: boolean }) {
  const reduced = useReducedMotion()
  const [offset, setOffset] = useState<[number, number]>([0, 0])

  useEffect(() => {
    if (!enabled || reduced) return
    let raf = 0
    let target: [number, number] = [0, 0]
    let current: [number, number] = [0, 0]

    const onMove = (e: PointerEvent) => {
      const x = (e.clientX / window.innerWidth - 0.5) * 0.6
      const y = (e.clientY / window.innerHeight - 0.5) * 0.6
      target = [x, y]
    }

    const tick = () => {
      // Spring lerp toward cursor target
      current = [
        current[0] + (target[0] - current[0]) * 0.06,
        current[1] + (target[1] - current[1]) * 0.06,
      ]
      setOffset([
        Number(current[0].toFixed(3)),
        Number(current[1].toFixed(3)),
      ])
      raf = requestAnimationFrame(tick)
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    raf = requestAnimationFrame(tick)
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(raf)
    }
  }, [enabled, reduced])

  if (!enabled || reduced) return null

  return (
    <div
      aria-hidden
      className="fixed inset-0 pointer-events-none -z-10"
      style={{ contain: 'layout paint', willChange: 'transform' }}
    >
      <MeshGradient
        // Quant Sentinel palette — premium gold + dark + cool accents
        colors={['#0a0a0c', '#caa12a', '#1a1a1f', '#3b82f6', '#0a0a0c']}
        speed={0.32}
        distortion={0.85}
        swirl={0.18}
        grainOverlay={0.42}
        offsetX={offset[0]}
        offsetY={offset[1]}
        scale={1.15}
        style={{
          width: '100%',
          height: '100%',
          opacity: 0.55,
          filter: 'saturate(1.15)',
        }}
      />
      {/* Layered grain noise — adds Vercel/Linear-tier texture over shader */}
      <div
        aria-hidden
        className="absolute inset-0 bg-grain mix-blend-overlay opacity-[0.08]"
      />
      {/* Vignette + bottom fade — keeps content surfaces readable */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 80% at 50% 30%, transparent 0%, rgba(10,10,12,0.45) 60%, rgba(10,10,12,0.85) 100%)',
        }}
      />
    </div>
  )
}
