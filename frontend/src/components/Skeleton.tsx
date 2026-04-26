type Variant = 'kpi' | 'row' | 'chart' | 'sparkline' | 'pill' | 'text'

interface Props {
  variant?: Variant
  /** Pixel height for `chart` variant. Defaults sensibly per variant. */
  height?: number
  /** Optional explicit width (number → px, string → CSS value). */
  width?: number | string
  className?: string
}

/**
 * Premium shimmer skeleton. Shapes match the actual loaded content so the
 * page never "jumps" when data arrives.
 *
 * Variants:
 *   - `kpi`       large numeric block + label line
 *   - `row`       horizontal line for table/list rows
 *   - `chart`     full chart placeholder
 *   - `sparkline` thin horizontal mini-line
 *   - `pill`      rounded badge
 *   - `text`      single line of body text
 */
export function Skeleton({ variant = 'text', height, width, className = '' }: Props) {
  const w =
    typeof width === 'number' ? `${width}px` : width

  if (variant === 'kpi') {
    return (
      <div className={`flex flex-col gap-3 ${className}`}>
        <div className="skeleton h-3 w-24 opacity-50" />
        <div className="skeleton h-10 w-32" />
        <div className="skeleton h-3 w-40 opacity-50" />
      </div>
    )
  }

  if (variant === 'row') {
    return (
      <div className={`flex items-center gap-4 py-3 ${className}`}>
        <div className="skeleton h-5 w-12 rounded-full" />
        <div className="flex-1 skeleton h-4" />
        <div className="skeleton h-4 w-16" />
      </div>
    )
  }

  if (variant === 'chart') {
    return (
      <div
        className={`skeleton w-full rounded-xl2 ${className}`}
        style={{ height: height ?? 420 }}
      />
    )
  }

  if (variant === 'sparkline') {
    return (
      <div
        className={`skeleton rounded-full ${className}`}
        style={{ height: height ?? 6, width: w ?? '100%' }}
      />
    )
  }

  if (variant === 'pill') {
    return (
      <div
        className={`skeleton rounded-full ${className}`}
        style={{ height: height ?? 22, width: w ?? 64 }}
      />
    )
  }

  // text
  return (
    <div
      className={`skeleton ${className}`}
      style={{ height: height ?? 14, width: w ?? '100%' }}
    />
  )
}
