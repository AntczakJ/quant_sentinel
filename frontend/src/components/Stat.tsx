import { type ReactNode } from 'react'
import NumberFlow, { type Format } from '@number-flow/react'
import { FlashOnChange } from './FlashOnChange'
import { useReducedMotion } from '@/lib/useReducedMotion'

type Size = 'sm' | 'md' | 'lg'

interface BaseProps {
  label: string
  delta?: { value: number; suffix?: string } | null
  hint?: string
  size?: Size
  /** Pulse a bull/bear flash on numeric changes (default: true if `numeric`). */
  flash?: boolean
}

type StringProps = BaseProps & {
  value: ReactNode
  numeric?: never
  format?: never
  prefix?: never
  suffix?: never
}

type NumericProps = BaseProps & {
  value?: never
  numeric: number | null | undefined
  format?: Format
  prefix?: string
  suffix?: string
}

type StatProps = StringProps | NumericProps

const sizeClass: Record<Size, string> = {
  sm: 'text-headline',
  md: 'text-display-sm text-display-gradient',
  lg: 'text-display-md text-display-gradient',
}

export function Stat(props: StatProps) {
  const { label, delta, hint, size = 'md' } = props
  const reduced = useReducedMotion()
  const valueClass = `num font-display tracking-tightest ${sizeClass[size]}`

  const positive = delta && delta.value > 0
  const negative = delta && delta.value < 0

  let valueNode: ReactNode
  if ('numeric' in props && props.numeric !== undefined) {
    const { numeric, format, prefix, suffix, flash = true } = props
    const inner = numeric == null ? (
      <span className="text-ink-500">—</span>
    ) : (
      <NumberFlow
        value={numeric}
        format={format}
        prefix={prefix}
        suffix={suffix}
        respectMotionPreference
      />
    )
    valueNode = flash && !reduced ? (
      <FlashOnChange value={numeric ?? null}>{inner}</FlashOnChange>
    ) : (
      inner
    )
  } else {
    valueNode = (props as StringProps).value
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="text-micro uppercase tracking-wider text-ink-600">{label}</div>
      <div className={valueClass}>{valueNode}</div>
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
