import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts'
import { api } from '@/api/client'
import { Card } from '@/components/Card'

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

  const { data, isLoading } = useQuery({
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

  // Update data when fetched
  useEffect(() => {
    if (!data?.candles || !seriesRef.current) return
    const formatted: CandlestickData[] = data.candles.map((c) => ({
      time: c.time as never,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
    seriesRef.current.setData(formatted)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-display-sm font-display tracking-tight text-display-gradient">XAU/USD</h1>
        <div className="flex gap-2">
          {TFS.map((t) => (
            <button
              key={t.value}
              onClick={() => setTf(t.value)}
              className={`px-4 py-2 rounded-full text-caption transition-all ${
                tf === t.value
                  ? 'bg-white/[0.08] text-ink-900 border border-white/15'
                  : 'border border-white/[0.06] text-ink-600 hover:text-ink-800 hover:border-white/15'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <Card variant="raised" className="p-1">
        <div ref={containerRef} className="w-full h-[640px] rounded-xl2 overflow-hidden" />
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center text-caption text-ink-600">
            Loading candles…
          </div>
        )}
      </Card>
    </div>
  )
}
