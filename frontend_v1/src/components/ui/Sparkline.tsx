/**
 * src/components/ui/Sparkline.tsx — Tiny inline SVG sparkline chart
 *
 * Usage:
 *   <Sparkline data={[100, 102, 98, 105, 110]} />
 *   <Sparkline data={values} color="#26a69a" height={24} />
 */

import { memo, useMemo } from 'react';

interface Props {
  data: number[];
  /** Chart width (default 80) */
  width?: number;
  /** Chart height (default 24) */
  height?: number;
  /** Line color (default auto green/red based on trend) */
  color?: string;
  /** Line width (default 1.5) */
  strokeWidth?: number;
  /** Show gradient fill below line */
  fill?: boolean;
  className?: string;
}

export const Sparkline = memo(function Sparkline({
  data, width = 80, height = 24, color, strokeWidth = 1.5, fill = true, className = '',
}: Props) {
  const pathData = useMemo(() => {
    const valid = data.filter(v => Number.isFinite(v));
    if (valid.length < 2) {return { d: '', fillD: '', autoColor: '#6b7280' };}

    const min = Math.min(...valid);
    const max = Math.max(...valid);
    const range = max - min || 1;
    const pad = 1;

    const points = valid.map((v, i) => ({
      x: pad + (i / (valid.length - 1)) * (width - pad * 2),
      y: pad + ((max - v) / range) * (height - pad * 2),
    }));

    const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const fillD = `${d} L${points[points.length - 1].x.toFixed(1)},${height} L${points[0].x.toFixed(1)},${height} Z`;

    const trend = valid[valid.length - 1] >= valid[0];
    const autoColor = trend ? '#26a69a' : '#ef5350';

    return { d, fillD, autoColor };
  }, [data, width, height]);

  if (data.length < 2) {return null;}

  const lineColor = color ?? pathData.autoColor;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className}>
      {fill && (
        <path d={pathData.fillD} fill={lineColor} fillOpacity={0.12} />
      )}
      <path d={pathData.d} fill="none" stroke={lineColor} strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
});
