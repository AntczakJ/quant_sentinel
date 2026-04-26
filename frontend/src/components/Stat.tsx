import { type ReactNode } from 'react'

interface StatProps {
  label: string
  value: ReactNode
  delta?: { value: number; suffix?: string } | null
  hint?: string
  size?: 'sm' | 'md' | 'lg'
}

export function Stat({ label, value, delta, hint, size = 'md' }: StatProps) {
  const valueClass =
    size === 'lg'
      ? 'text-display-md text-display-gradient'
      : size === 'sm'
      ? 'text-headline'
      : 'text-display-sm text-display-gradient'

  const positive = delta && delta.value > 0
  const negative = delta && delta.value < 0

  return (
    <div className="flex flex-col gap-2">
      <div className="text-micro uppercase tracking-wider text-ink-600">{label}</div>
      <div className={`num font-display ${valueClass}`}>{value}</div>
      {(delta != null || hint) && (
        <div className="flex items-center gap-2 text-caption">
          {delta != null && (
            <span
              className={`num ${positive ? 'text-bull' : negative ? 'text-bear' : 'text-ink-600'}`}
            >
              {positive ? '+' : ''}
              {delta.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              {delta.suffix ?? ''}
            </span>
          )}
          {hint && <span className="text-ink-600">{hint}</span>}
        </div>
      )}
    </div>
  )
}
