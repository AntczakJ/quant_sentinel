import type { ReactNode } from 'react'

/**
 * ShinyText — premium liquid sheen on text.
 *
 * A diagonal highlight sweeps across the text every 4s. Below the sheen
 * sits a soft gradient base. Combo creates a "polished metal" effect
 * popular in 2026 dashboards (Linear's brand, Apple Watch UI, etc).
 *
 * Subtler than GradientText (which is full color cycle) — this is for
 * primary headings where you want polish but not distraction.
 *
 * Variants:
 *   - 'gold' (default): muted gold base + champagne sheen
 *   - 'silver': slate base + white sheen
 *   - 'bull': dark green base + light green sheen
 *   - 'bear': deep red base + crimson sheen
 */

type Variant = 'gold' | 'silver' | 'bull' | 'bear'

const VARIANTS: Record<Variant, { base: string; sheen: string }> = {
  gold: {
    base: 'linear-gradient(180deg, #f5e9c5 0%, #d4af37 50%, #a8861f 100%)',
    sheen: 'linear-gradient(110deg, transparent 35%, rgba(255,250,235,0.85) 50%, transparent 65%)',
  },
  silver: {
    base: 'linear-gradient(180deg, #fafafa 0%, #bdbdc6 100%)',
    sheen: 'linear-gradient(110deg, transparent 35%, rgba(255,255,255,0.65) 50%, transparent 65%)',
  },
  bull: {
    base: 'linear-gradient(180deg, #4ade80 0%, #16a34a 100%)',
    sheen: 'linear-gradient(110deg, transparent 35%, rgba(187,247,208,0.7) 50%, transparent 65%)',
  },
  bear: {
    base: 'linear-gradient(180deg, #f87171 0%, #b91c1c 100%)',
    sheen: 'linear-gradient(110deg, transparent 35%, rgba(252,165,165,0.7) 50%, transparent 65%)',
  },
}

export function ShinyText({
  children,
  variant = 'gold',
  className = '',
  duration = 4,
}: {
  children: ReactNode
  variant?: Variant
  className?: string
  duration?: number
}) {
  const { base, sheen } = VARIANTS[variant]

  return (
    <span
      className={`relative inline-block bg-clip-text text-transparent ${className}`}
      style={{
        backgroundImage: `${sheen}, ${base}`,
        backgroundSize: '200% 100%, 100% 100%',
        backgroundPosition: '-100% 0%, 0% 0%',
        animation: `shineSlide ${duration}s linear infinite`,
        WebkitBackgroundClip: 'text',
        backgroundClip: 'text',
      }}
    >
      {children}
    </span>
  )
}
