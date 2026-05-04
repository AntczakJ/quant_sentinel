type Props = {
  className?: string
  variant?: 'gold' | 'cool' | 'mixed'
}

export function BlobField({ className = '', variant = 'mixed' }: Props) {
  const colors = variant === 'gold'
    ? ['rgba(212,175,55,0.42)', 'rgba(244,214,118,0.30)', 'rgba(168,134,31,0.36)']
    : variant === 'cool'
    ? ['rgba(59,130,246,0.34)', 'rgba(139,92,246,0.28)', 'rgba(34,197,94,0.22)']
    : ['rgba(212,175,55,0.36)', 'rgba(59,130,246,0.28)', 'rgba(34,197,94,0.20)']

  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}
    >
      <div
        className="absolute h-[480px] w-[480px] animate-blob animate-float-slow"
        style={{
          top: '-20%',
          left: '-10%',
          background: colors[0],
          filter: 'blur(70px)',
          mixBlendMode: 'screen',
        }}
      />
      <div
        className="absolute h-[420px] w-[420px] animate-blob animate-float-slow"
        style={{
          bottom: '-25%',
          right: '-8%',
          background: colors[1],
          filter: 'blur(80px)',
          animationDelay: '4s, 3s',
          mixBlendMode: 'screen',
        }}
      />
      <div
        className="absolute h-[320px] w-[320px] animate-blob animate-float-slow"
        style={{
          top: '40%',
          left: '50%',
          background: colors[2],
          filter: 'blur(90px)',
          animationDelay: '8s, 6s',
          mixBlendMode: 'screen',
        }}
      />
    </div>
  )
}
