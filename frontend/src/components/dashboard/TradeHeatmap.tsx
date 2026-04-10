/**
 * src/components/dashboard/TradeHeatmap.tsx — GitHub-style P&L calendar heatmap
 *
 * Shows daily P&L as colored cells. Green=profit, Red=loss, Gray=no trades.
 * Covers last 90 days.
 */

import { memo, useMemo } from 'react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';

interface Trade {
  profit?: string | number;
  timestamp: string;
  result: string;
}

interface TradesData {
  trades: Trade[];
}

const DAYS = 91; // ~13 weeks
const CELL = 11;
const GAP = 2;
const ROWS = 7;
const DAY_LABELS = ['', 'Pn', '', 'Sr', '', 'Pt', ''];

function parseProfit(val: string | number | undefined): number {
  if (!val) return 0;
  if (typeof val === 'number') return val;
  return parseFloat(val.replace(/[$,]/g, '')) || 0;
}

function getColor(pnl: number): string {
  if (pnl > 50) return 'rgb(var(--c-green))';
  if (pnl > 10) return 'rgba(var(--c-green), 0.6)';
  if (pnl > 0) return 'rgba(var(--c-green), 0.3)';
  if (pnl < -50) return 'rgb(var(--c-red))';
  if (pnl < -10) return 'rgba(var(--c-red), 0.6)';
  if (pnl < 0) return 'rgba(var(--c-red), 0.3)';
  return 'var(--color-secondary)';
}

export const TradeHeatmap = memo(function TradeHeatmap() {
  const { data } = usePollingQuery<TradesData>(
    'heatmap-trades',
    () => analysisAPI.getRecentTrades(500),
    120_000,
  );

  const { cells, months } = useMemo(() => {
    const now = new Date();
    const dayMap = new Map<string, number>();

    // Aggregate P&L per day
    for (const t of (data?.trades ?? [])) {
      const ts = t.timestamp?.trim();
      if (!ts) continue;
      const d = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z');
      if (isNaN(d.getTime())) continue;
      const key = d.toISOString().slice(0, 10);
      dayMap.set(key, (dayMap.get(key) ?? 0) + parseProfit(t.profit));
    }

    // Build grid of last DAYS days
    const cells: { date: string; pnl: number; col: number; row: number }[] = [];
    const startDate = new Date(now);
    startDate.setDate(startDate.getDate() - DAYS + 1);
    // Align to Monday
    const startDow = startDate.getDay();
    const offset = startDow === 0 ? 6 : startDow - 1; // Mon=0
    startDate.setDate(startDate.getDate() - offset);

    const totalDays = DAYS + offset;
    const cols = Math.ceil(totalDays / 7);

    for (let i = 0; i < cols * 7; i++) {
      const d = new Date(startDate);
      d.setDate(d.getDate() + i);
      if (d > now) continue;
      const key = d.toISOString().slice(0, 10);
      const col = Math.floor(i / 7);
      const row = i % 7;
      cells.push({ date: key, pnl: dayMap.get(key) ?? 0, col, row });
    }

    // Month labels
    const months: { label: string; col: number }[] = [];
    let lastMonth = -1;
    for (const c of cells) {
      const m = new Date(c.date).getMonth();
      if (m !== lastMonth && c.row === 0) {
        months.push({ label: new Date(c.date).toLocaleString('pl-PL', { month: 'short' }), col: c.col });
        lastMonth = m;
      }
    }

    return { cells, months };
  }, [data]);

  const maxCol = cells.length > 0 ? Math.max(...cells.map(c => c.col)) + 1 : 0;
  const svgW = 20 + maxCol * (CELL + GAP);
  const svgH = 16 + ROWS * (CELL + GAP);

  return (
    <div className="overflow-x-auto">
      <svg width={svgW} height={svgH} viewBox={`0 0 ${svgW} ${svgH}`} className="min-w-fit">
        {/* Day labels */}
        {DAY_LABELS.map((label, i) => label && (
          <text key={i} x={0} y={16 + i * (CELL + GAP) + CELL - 2}
            fill="var(--color-text-muted)" fontSize="8" fontFamily="Inter, sans-serif">
            {label}
          </text>
        ))}

        {/* Month labels */}
        {months.map((m, i) => (
          <text key={i} x={20 + m.col * (CELL + GAP)} y={10}
            fill="var(--color-text-muted)" fontSize="8" fontFamily="Inter, sans-serif">
            {m.label}
          </text>
        ))}

        {/* Cells */}
        {cells.map((c) => (
          <rect
            key={c.date}
            x={20 + c.col * (CELL + GAP)}
            y={16 + c.row * (CELL + GAP)}
            width={CELL}
            height={CELL}
            rx={2}
            fill={getColor(c.pnl)}
            opacity={c.pnl === 0 ? 0.4 : 1}
          >
            <title>{c.date}: {c.pnl === 0 ? 'brak trades' : `${c.pnl >= 0 ? '+' : ''}$${c.pnl.toFixed(2)}`}</title>
          </rect>
        ))}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-2 mt-2 text-[9px] text-th-dim">
        <span>Mniej</span>
        {[-50, -10, 0, 10, 50].map(v => (
          <div key={v} className="w-[10px] h-[10px] rounded-sm" style={{ background: getColor(v), opacity: v === 0 ? 0.4 : 1 }} />
        ))}
        <span>Wiecej</span>
      </div>
    </div>
  );
});
