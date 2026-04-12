/**
 * src/components/dashboard/EquityCurve.tsx — Equity curve + drawdown chart
 *
 * Uses lightweight-charts line series for equity and area series for drawdown.
 * Data from /api/portfolio/history.
 */

import { memo, useEffect, useRef, useState } from 'react';
import { TrendingUp, TrendingDown, BarChart3 } from 'lucide-react';
import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { portfolioAPI } from '../../api/client';
import { useTheme } from '../../hooks/useTheme';
import { EmptyState } from '../ui/EmptyState';

interface HistoryData {
  timestamps: string[];
  equity_values: number[];
  pnl_values: number[];
}

export const EquityCurve = memo(function EquityCurve() {
  const { isDark } = useTheme();
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const equitySeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ddSeriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const [showDrawdown, setShowDrawdown] = useState(true);

  const { data, isLoading } = usePollingQuery<HistoryData>(
    'equity-history',
    () => portfolioAPI.getHistory(),
    120_000,
  );

  // Build chart
  useEffect(() => {
    if (!chartRef.current) {return;}

    const bg = isDark ? '#0f1729' : '#ffffff';
    const text = isDark ? 'rgba(148,163,184,0.6)' : 'rgba(100,116,139,0.7)';
    const grid = isDark ? 'rgba(30,41,59,0.5)' : 'rgba(226,232,240,0.6)';

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height: 260,
      layout: { background: { color: bg }, textColor: text, fontSize: 10, fontFamily: 'Inter, sans-serif' },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      timeScale: { borderColor: grid, timeVisible: true },
      rightPriceScale: { borderColor: grid },
      crosshair: { mode: 0 },
    });

    const equitySeries = chart.addLineSeries({
      color: isDark ? 'rgb(34,197,94)' : 'rgb(22,163,74)',
      lineWidth: 2,
      priceFormat: { type: 'custom', formatter: (p: number) => p.toFixed(2) },
      title: 'Equity',
    });

    const ddSeries = chart.addAreaSeries({
      topColor: 'rgba(239,68,68,0.3)',
      bottomColor: 'rgba(239,68,68,0.02)',
      lineColor: 'rgba(239,68,68,0.5)',
      lineWidth: 1,
      priceFormat: { type: 'custom', formatter: (p: number) => p.toFixed(2) + '%' },
      title: 'Drawdown',
      visible: showDrawdown,
      priceScaleId: 'dd',
    });

    chart.priceScale('dd').applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    });

    chartApiRef.current = chart;
    equitySeriesRef.current = equitySeries;
    ddSeriesRef.current = ddSeries;

    const ro = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width });
    });
    ro.observe(chartRef.current);

    return () => { ro.disconnect(); chart.remove(); };
  }, [isDark]); // eslint-disable-line react-hooks/exhaustive-deps

  // Feed data
  useEffect(() => {
    if (!data || !equitySeriesRef.current || !ddSeriesRef.current) {return;}
    if (!data.timestamps?.length || !data.equity_values?.length) {return;}

    const len = Math.min(data.timestamps.length, data.equity_values.length);
    const equityData = data.timestamps.slice(0, len).map((ts, i) => ({
      time: (new Date(ts).getTime() / 1000) as UTCTimestamp,
      value: data.equity_values[i] ?? 0,
    }));

    // Calculate drawdown %
    let peak = equityData[0]?.value ?? 0;
    const ddData = equityData.map(p => {
      if (p.value > peak) {peak = p.value;}
      const dd = peak > 0 ? ((p.value - peak) / peak) * 100 : 0;
      return { time: p.time, value: dd };
    });

    equitySeriesRef.current.setData(equityData);
    ddSeriesRef.current.setData(ddData);
    chartApiRef.current?.timeScale().fitContent();
  }, [data]);

  // Toggle drawdown visibility
  useEffect(() => {
    ddSeriesRef.current?.applyOptions({ visible: showDrawdown });
  }, [showDrawdown]);

  if (isLoading && !data) {
    return (
      <div className="space-y-2">
        <div className="flex gap-4">
          <div className="skeleton-shimmer h-5 w-20 rounded" />
          <div className="skeleton-shimmer h-5 w-20 rounded" />
        </div>
        <div className="skeleton-shimmer h-[260px] rounded-lg" />
      </div>
    );
  }

  if (!data || !data.timestamps?.length) {
    return (
      <EmptyState
        icon="chart"
        message="Brak historii equity"
        description="Wykres pojawi sie po pierwszych zamknietych transakcjach"
      />
    );
  }

  // Summary stats
  const values = data.equity_values;
  const first = values[0] ?? 0;
  const last = values[values.length - 1] ?? 0;
  const totalReturn = first > 0 ? ((last - first) / first) * 100 : 0;
  let peak = first;
  let maxDd = 0;
  for (const v of values) {
    if (v > peak) {peak = v;}
    const dd = peak > 0 ? ((v - peak) / peak) * 100 : 0;
    if (dd < maxDd) {maxDd = dd;}
  }

  return (
    <div className="space-y-3">
      {/* Stats row */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          {totalReturn >= 0 ? <TrendingUp size={12} className="text-accent-green" /> : <TrendingDown size={12} className="text-accent-red" />}
          <span className={`text-sm font-bold font-mono ${totalReturn >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
            {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
          </span>
          <span className="text-[10px] text-th-muted">Total Return</span>
        </div>
        <div className="flex items-center gap-1.5">
          <BarChart3 size={12} className="text-accent-red" />
          <span className="text-sm font-bold font-mono text-accent-red">{maxDd.toFixed(2)}%</span>
          <span className="text-[10px] text-th-muted">Max DD</span>
        </div>
        <div className="flex-1" />
        <button
          onClick={() => setShowDrawdown(v => !v)}
          className={`text-[10px] px-2 py-0.5 rounded border transition-colors ${
            showDrawdown
              ? 'bg-accent-red/10 text-accent-red border-accent-red/25'
              : 'text-th-muted border-dark-secondary hover:text-th-secondary'
          }`}
        >
          Drawdown
        </button>
      </div>

      {/* Chart */}
      <div ref={chartRef} className="w-full rounded-lg overflow-hidden border border-dark-secondary" />
    </div>
  );
});
