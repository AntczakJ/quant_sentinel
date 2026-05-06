import { useEffect, useRef, type ReactNode } from 'react'

/**
 * WeightFlux — wraps any number/text and animates font-weight when
 * the wrapped value changes. Pairs beautifully with NumberFlow's
 * digit-flip (NumberFlow handles the digits, WeightFlux pulses
 * the weight axis).
 *
 * Editorial typography pattern — the BIG numbers get heavier briefly
 * on update, then settle back. Top-tier 2026 dashboards (Linear,
 * Stripe, Vercel) all do this with variable fonts.
 *
 * Requires a variable-weight font in CSS. Inter Variable / Recursive
 * are widely supported; fallback gracefully when font isn't variable
 * (just renders normally).
 *
 * Usage:
 *   <WeightFlux watchValue={balance}>
 *     <NumberFlow value={balance} />
 *   </WeightFlux>
 */
export function WeightFlux({
  watchValue,
  children,
  baseWeight = 600,
  pulseWeight = 800,
  durationMs = 700,
  className = '',
}: {
  watchValue: number | string | null | undefined
  children: ReactNode
  baseWeight?: number
  pulseWeight?: number
  durationMs?: number
  className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const prevRef = useRef(watchValue)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (prevRef.current === watchValue) return
    prevRef.current = watchValue

    // Force pulse: jump to pulseWeight, then ease back to baseWeight
    el.style.transition = 'none'
    el.style.fontVariationSettings = `'wght' ${pulseWeight}`
    el.style.fontWeight = String(pulseWeight)

    // Force reflow to commit the jump
    void el.offsetWidth

    el.style.transition = `font-variation-settings ${durationMs}ms cubic-bezier(0.22, 1, 0.36, 1), font-weight ${durationMs}ms cubic-bezier(0.22, 1, 0.36, 1)`
    el.style.fontVariationSettings = `'wght' ${baseWeight}`
    el.style.fontWeight = String(baseWeight)
  }, [watchValue, baseWeight, pulseWeight, durationMs])

  return (
    <span
      ref={ref}
      className={className}
      style={{
        fontVariationSettings: `'wght' ${baseWeight}`,
        fontWeight: baseWeight,
        display: 'inline-block',
      }}
    >
      {children}
    </span>
  )
}
