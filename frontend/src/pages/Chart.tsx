import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type UTCTimestamp,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts'
import { api } from '@/api/client'
import { Card } from '@/components/Card'
import { MagneticButton } from '@/components/MagneticButton'
import { Skeleton } from '@/components/Skeleton'
import { GradientText } from '@/components/GradientText'
import { TextReveal } from '@/components/TextReveal'
import { LiveDot } from '@/components/LiveDot'

const TFS = [
  { label: '5m', value: '5m' },
  { label: '15m', value: '15m' },
  { label: '1h', value: '1h' },
  { label: '4h', value: '4h' },
] as const

export default function ChartPage() {
  const [tf, setTf] = useState<(typeof TFS)[number]['value']>('15m')
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['candles', tf],
    queryFn: () => api.candles('XAU/USD', tf, 500),
    refetchInterval: 30_000,
  })

  // Init chart once
  useEffect(() => {
    if (!containerRef.current || chartRef.current) return
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#bdbdc6',
        fontFamily:
          'ui-sans-serif, -apple-system, BlinkMacSystemFont, Inter, Segoe UI, sans-serif',
        fontSize: 12,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.06)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.06)', timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    })
    const series = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    chartRef.current = chart
    seriesRef.current = series

    const resize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        })
      }
    }
    resize()
    const obs = new ResizeObserver(resize)
    obs.observe(containerRef.current)

    return () => {
      obs.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // Update data when fetched. lightweight-charts requires:
  //   - time: UTCTimestamp (number, seconds since epoch)
  //   - strictly ascending, no duplicates
  // Our api.candles already returns time as a unix-seconds number.
  useEffect(() => {
    if (!data?.length || !seriesRef.current) return
    // Dedup + sort guard (the API may return duplicates around session boundaries)
    const seen = new Set<number>()
    const sorted: CandlestickData[] = []
    for (const c of data) {
      if (typeof c.time !== 'number' || !Number.isFinite(c.time)) continue
      if (seen.has(c.time)) continue
      seen.add(c.time)
      sorted.push({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })
    }
    sorted.sort((a, b) => (a.time as number) - (b.time as number))
    if (sorted.length === 0) return
    try {
      seriesRef.current.setData(sorted)
      chartRef.current?.timeScale().fitContent()
    } catch (err) {
      // Don't crash the whole page on a malformed payload — log and recover.
      console.warn('chart setData failed', err)
    }
  }, [data])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-display-sm font-display tracking-tight flex items-center gap-3">
          <GradientText>
            <TextReveal text="XAU/USD" splitBy="char" />
          </GradientText>
          <LiveDot color="gold" />
        </h1>
        <div className="flex gap-2">
          {TFS.map((t) => (
            <MagneticButton
              key={t.value}
              strength={0.18}
              onClick={() => setTf(t.value)}
              className={`px-4 py-2 rounded-full text-caption transition-colors ${
                tf === t.value
                  ? 'bg-white/[0.08] text-ink-900 border border-white/15 shadow-glow-gold'
                  : 'border border-white/[0.06] text-ink-600 hover:text-ink-800 hover:border-white/15'
              }`}
            >
              {t.label}
            </MagneticButton>
          ))}
        </div>
      </div>

      <Card variant="raised" className="relative">
        <div ref={containerRef} className="w-full h-[640px] rounded-xl2 overflow-hidden" />
        {isLoading && !isError && (
          <div className="absolute inset-0 p-6 pointer-events-none">
            <Skeleton variant="chart" height={596} />
          </div>
        )}
        {isError && (
          <div className="absolute inset-0 flex items-center justify-center text-caption text-bear pointer-events-none">
            Failed to load candles.
          </div>
        )}
      </Card>
    </div>
  )
}
