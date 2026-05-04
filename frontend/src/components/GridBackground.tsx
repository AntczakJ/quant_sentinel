type Props = {
  className?: string
  spacing?: number
  opacity?: number
}

/**
 * GridBackground — subtle blueprint-style grid pattern with a slow drifting
 * radial mask. Production-grade SaaS texture (Linear, Vercel, Stripe vibe).
 * Uses CSS background-image only — no SVG, no extra DOM.
 */
export function GridBackground({ className = '', spacing = 32, opacity = 0.06 }: Props) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 ${className}`}
      style={{
        backgroundImage: `
          linear-gradient(rgba(255,255,255,${opacity}) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,${opacity}) 1px, transparent 1px)
        `,
        backgroundSize: `${spacing}px ${spacing}px, ${spacing}px ${spacing}px`,
        maskImage:
          'radial-gradient(ellipse 60% 50% at 50% 50%, #000 35%, transparent 80%)',
        WebkitMaskImage:
          'radial-gradient(ellipse 60% 50% at 50% 50%, #000 35%, transparent 80%)',
      }}
    />
  )
}
