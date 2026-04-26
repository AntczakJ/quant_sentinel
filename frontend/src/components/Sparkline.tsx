import { useId, useMemo } from 'react'

interface Props {
  values: number[]
  width?: number
  height?: number
  /** Override stroke color. Default = derived from trend (bull/bear). */
  color?: string
  /** Render the area below the line as a soft gradient. */
  area?: boolean
  /** Stroke thickness. */
  strokeWidth?: number
  /** Optional zero-line baseline (drawn faintly when 0 falls within range). */
  zeroLine?: boolean
  className?: string
  ariaLabel?: string
}

/**
 * Compact SVG sparkline. Auto-fits Y range, derives bull/bear color from
 * net change. Used on bento KPI cards (WR / PnL trend) and as the inline
 * equity curve inside `BalanceDetail`.
 */
export function Sparkline({
  values,
  width = 160,
  height = 44,
  color,
  area = true,
  strokeWidth = 1.6,
  zeroLine = false,
  className = '',
  ariaLabel,
}: Props) {
  const id = useId()
  const { path, areaPath, stroke, ymin, ymax, zeroY } = useMemo(() => {
    if (!values.length) {
      return { path: '', areaPath: '', stroke: '#8b8b95', ymin: 0, ymax: 0, zeroY: null as number | null }
    }
    const n = values.length
    let _min = values[0]
    let _max = values[0]
    for (const v of values) {
      if (v < _min) _min = v
      if (v > _max) _max = v
    }
    if (_min === _max) {
      // Pad flat series so the line shows centered
      _min -= 1
      _max += 1
    }
    const xStep = n > 1 ? width / (n - 1) : 0
    const yScale = (v: number) => {
      const t = (v - _min) / (_max - _min)
      return height - t * (height - 4) - 2
    }
    let d = ''
    let a = ''
    values.forEach((v, i) => {
      const x = i * xStep
      const y = yScale(v)
      d += i === 0 ? `M ${x.toFixed(2)},${y.toFixed(2)}` : ` L ${x.toFixed(2)},${y.toFixed(2)}`
    })
    if (area) {
      a = `${d} L ${(width).toFixed(2)},${height} L 0,${height} Z`
    }
    const trend = values[n - 1] - values[0]
    const stk = color ?? (trend > 0 ? '#22c55e' : trend < 0 ? '#ef4444' : '#a1a1aa')
    const _zeroY = zeroLine && _min < 0 && _max > 0 ? yScale(0) : null
    return { path: d, areaPath: a, stroke: stk, ymin: _min, ymax: _max, zeroY: _zeroY }
  }, [values, width, height, color, area, zeroLine])

  if (!values.length) {
    return (
      <svg width={width} height={height} className={className} aria-label={ariaLabel ?? 'no data'}>
        <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="rgba(255,255,255,0.06)" strokeDasharray="3 3" />
      </svg>
    )
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label={ariaLabel ?? `Sparkline range ${ymin.toFixed(2)} – ${ymax.toFixed(2)}`}
    >
      {area && (
        <>
          <defs>
            <linearGradient id={`spark-fill-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.32" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#spark-fill-${id})`} />
        </>
      )}
      {zeroY != null && (
        <line x1="0" y1={zeroY} x2={width} y2={zeroY} stroke="rgba(255,255,255,0.10)" strokeDasharray="2 3" />
      )}
      <path d={path} stroke={stroke} strokeWidth={strokeWidth} fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
