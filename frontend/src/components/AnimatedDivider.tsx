type Props = {
  className?: string
}

/**
 * AnimatedDivider — section separator with a flowing gradient highlight
 * that travels left-to-right (5s cycle). Used between major Dashboard
 * sections for editorial pacing.
 */
export function AnimatedDivider({ className = '' }: Props) {
  return (
    <div className={`relative h-px w-full overflow-hidden ${className}`}>
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.06] to-transparent" />
      <div
        className="absolute inset-y-0 w-1/3 animate-marquee-slow"
        style={{
          background:
            'linear-gradient(90deg, transparent 0%, rgba(212,175,55,0.55) 50%, transparent 100%)',
          filter: 'blur(0.5px)',
        }}
      />
    </div>
  )
}
