type Props = {
  label?: string
  color?: 'bull' | 'gold' | 'info' | 'bear'
  size?: 'sm' | 'md'
}

const colorMap = {
  bull: 'bg-bull',
  gold: 'bg-gold-400',
  info: 'bg-info',
  bear: 'bg-bear',
}

export function LiveDot({ label, color = 'bull', size = 'sm' }: Props) {
  const dim = size === 'sm' ? 'h-2 w-2' : 'h-3 w-3'
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative inline-flex">
        <span
          className={`relative ${dim} rounded-full ${colorMap[color]} animate-live-pulse`}
          style={{ boxShadow: '0 0 0 0 currentColor' }}
        />
        <span
          aria-hidden
          className={`pointer-events-none absolute inset-0 ${dim} rounded-full border ${
            color === 'bull' ? 'border-bull' :
            color === 'gold' ? 'border-gold-400' :
            color === 'info' ? 'border-info' : 'border-bear'
          } animate-ripple`}
        />
        <span
          aria-hidden
          className={`pointer-events-none absolute inset-0 ${dim} rounded-full border ${
            color === 'bull' ? 'border-bull' :
            color === 'gold' ? 'border-gold-400' :
            color === 'info' ? 'border-info' : 'border-bear'
          } animate-ripple [animation-delay:1.2s]`}
        />
      </span>
      {label && (
        <span className="text-micro uppercase tracking-wider text-ink-700">{label}</span>
      )}
    </span>
  )
}
