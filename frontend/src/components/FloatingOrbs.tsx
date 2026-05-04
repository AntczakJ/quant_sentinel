type Props = {
  variant?: 'gold' | 'mixed' | 'cool'
  density?: 'low' | 'normal' | 'rich'
}

export function FloatingOrbs({ variant = 'mixed', density = 'normal' }: Props) {
  const orbs = density === 'low' ? 2 : density === 'rich' ? 5 : 3

  const palettes: Record<string, string[]> = {
    gold:  ['rgba(212,175,55,0.34)', 'rgba(244,214,118,0.22)', 'rgba(168,134,31,0.30)'],
    mixed: ['rgba(212,175,55,0.30)', 'rgba(59,130,246,0.22)', 'rgba(34,197,94,0.18)', 'rgba(168,134,31,0.30)', 'rgba(59,130,246,0.20)'],
    cool:  ['rgba(59,130,246,0.30)', 'rgba(139,92,246,0.22)', 'rgba(34,197,94,0.18)'],
  }
  const colors = palettes[variant]

  const positions = [
    { top: '-10%', left: '-5%',  size: 320 },
    { top: '20%',  left: '60%',  size: 260 },
    { top: '60%',  left: '-10%', size: 360 },
    { top: '70%',  left: '70%',  size: 280 },
    { top: '40%',  left: '30%',  size: 220 },
  ]

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {Array.from({ length: orbs }).map((_, i) => {
        const p = positions[i % positions.length]
        const c = colors[i % colors.length]
        return (
          <div
            key={i}
            className="glow-orb"
            style={{
              top: p.top,
              left: p.left,
              width: p.size,
              height: p.size,
              background: c,
              animationDelay: `${i * 1.7}s, ${i * 2.3}s`,
            }}
          />
        )
      })}
    </div>
  )
}
