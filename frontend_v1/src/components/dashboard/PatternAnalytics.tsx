/**
 * src/components/dashboard/PatternAnalytics.tsx — Pattern Performance Analytics
 *
 * Shows win rate by pattern, session heatmap, and direction breakdown.
 * Data from /api/analysis/stats and /api/analysis/trades.
 */

import { memo, useMemo, useState } from 'react';
import { BarChart3, TrendingUp, TrendingDown, Filter } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';

/* ── Types ─────────────────────────────────────────────────────────── */

interface PatternStat {
  pattern: string;
  count: number;
  wins: number;
  losses: number;
  win_rate: number;
}

interface StatsData {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  patterns: PatternStat[];
}

interface Trade {
  direction: string;
  result: string;
  pattern?: string | null;
  timestamp: string;
  profit?: string | number;
  session?: string | null;
}

interface TradesData {
  trades: Trade[];
}

/* ── Helpers ───────────────────────────────────────────────────────── */

function detectSession(ts: string): string {
  const d = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T') + 'Z');
  if (isNaN(d.getTime())) {return 'unknown';}
  const h = d.getUTCHours();
  if (h >= 0 && h < 7) {return 'Asian';}
  if (h >= 7 && h < 13) {return 'London';}
  if (h >= 13 && h < 22) {return 'NY';}
  return 'Off';
}

const SESSIONS = ['Asian', 'London', 'NY', 'Off'] as const;
const DIRECTIONS = ['LONG', 'SHORT'] as const;

type SortBy = 'count' | 'win_rate' | 'pattern';

/* ── Pattern Bar ───────────────────────────────────────────────────── */

function PatternBar({ stat }: { stat: PatternStat }) {
  const wrColor = stat.win_rate >= 0.5 ? 'text-accent-green' : stat.win_rate >= 0.3 ? 'text-accent-orange' : 'text-accent-red';
  const barColor = stat.win_rate >= 0.5 ? 'bg-accent-green/60' : stat.win_rate >= 0.3 ? 'bg-accent-orange/50' : 'bg-accent-red/50';

  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="text-[10px] text-th-secondary font-medium w-28 truncate" title={stat.pattern}>
        {stat.pattern || 'Unknown'}
      </span>
      <div className="flex-1 h-3 bg-dark-secondary rounded-full overflow-hidden relative">
        <div className={`h-full ${barColor} rounded-full transition-all duration-500`}
          style={{ width: `${Math.min(stat.win_rate * 100, 100)}%` }} />
        <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold text-th font-mono">
          {stat.wins}W / {stat.losses}L
        </span>
      </div>
      <span className={`text-[10px] font-bold font-mono w-10 text-right ${wrColor}`}>
        {(stat.win_rate * 100).toFixed(0)}%
      </span>
      <span className="text-[9px] text-th-dim w-6 text-right">{stat.count}</span>
    </div>
  );
}

/* ── Session × Direction Heatmap ───────────────────────────────────── */

function Heatmap({ trades }: { trades: Trade[] }) {
  const grid = useMemo(() => {
    const cells: Record<string, { wins: number; losses: number; total: number }> = {};
    for (const s of SESSIONS) {
      for (const d of DIRECTIONS) {
        cells[`${s}-${d}`] = { wins: 0, losses: 0, total: 0 };
      }
    }
    for (const t of trades) {
      const session = t.session ?? detectSession(t.timestamp);
      const mapped = SESSIONS.find(s => session.toLowerCase().includes(s.toLowerCase())) ?? 'Off';
      const dir = t.direction === 'LONG' ? 'LONG' : 'SHORT';
      const key = `${mapped}-${dir}`;
      if (!cells[key]) {cells[key] = { wins: 0, losses: 0, total: 0 };}
      cells[key].total++;
      if (t.result?.includes('WIN')) {cells[key].wins++;}
      if (t.result?.includes('LOSS')) {cells[key].losses++;}
    }
    return cells;
  }, [trades]);

  const getColor = (wr: number) => {
    if (wr >= 0.6) {return 'bg-accent-green/25 text-accent-green';}
    if (wr >= 0.4) {return 'bg-accent-orange/20 text-accent-orange';}
    if (wr > 0) {return 'bg-accent-red/20 text-accent-red';}
    return 'bg-dark-secondary text-th-dim';
  };

  return (
    <div className="space-y-1">
      <div className="text-[9px] text-th-muted uppercase tracking-wider font-medium mb-1">
        Session x Direction — Win Rate
      </div>
      {/* Header */}
      <div className="grid grid-cols-3 gap-1 text-center text-[9px] text-th-muted font-medium">
        <div />
        <div>LONG</div>
        <div>SHORT</div>
      </div>
      {/* Rows */}
      {SESSIONS.map(session => (
        <div key={session} className="grid grid-cols-3 gap-1">
          <div className="text-[10px] text-th-secondary font-medium flex items-center">{session}</div>
          {DIRECTIONS.map(dir => {
            const cell = grid[`${session}-${dir}`];
            if (!cell || cell.total === 0) {
              return <div key={dir} className="bg-dark-secondary rounded px-2 py-1.5 text-center text-[9px] text-th-dim">—</div>;
            }
            const wr = cell.total > 0 ? cell.wins / cell.total : 0;
            return (
              <div key={dir} className={`rounded px-2 py-1.5 text-center text-[10px] font-bold font-mono ${getColor(wr)}`}>
                {(wr * 100).toFixed(0)}%
                <div className="text-[8px] font-normal opacity-70">{cell.wins}W/{cell.losses}L</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────── */

export const PatternAnalytics = memo(function PatternAnalytics() {
  const [sortBy, setSortBy] = useState<SortBy>('count');

  const { data: statsData, isLoading: statsLoading } = usePollingQuery<StatsData>(
    'analysis-stats',
    () => analysisAPI.getStats(),
    120_000,
  );

  const { data: tradesData, isLoading: tradesLoading } = usePollingQuery<TradesData>(
    'analysis-trades-100',
    () => analysisAPI.getRecentTrades(100),
    120_000,
  );

  const patterns = useMemo(() => {
    if (!statsData?.patterns) {return [];}
    const sorted = [...statsData.patterns];
    if (sortBy === 'win_rate') {sorted.sort((a, b) => b.win_rate - a.win_rate);}
    else if (sortBy === 'count') {sorted.sort((a, b) => b.count - a.count);}
    else {sorted.sort((a, b) => a.pattern.localeCompare(b.pattern));}
    return sorted;
  }, [statsData?.patterns, sortBy]);

  const trades = tradesData?.trades ?? [];

  // Direction stats
  const dirStats = useMemo(() => {
    const long = { wins: 0, losses: 0, total: 0 };
    const short = { wins: 0, losses: 0, total: 0 };
    for (const t of trades) {
      const bucket = t.direction === 'LONG' ? long : short;
      bucket.total++;
      if (t.result?.includes('WIN')) {bucket.wins++;}
      if (t.result?.includes('LOSS')) {bucket.losses++;}
    }
    return { long, short };
  }, [trades]);

  if ((statsLoading || tradesLoading) && !statsData) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div className="skeleton-shimmer h-16 rounded-lg" />
          <div className="skeleton-shimmer h-16 rounded-lg" />
        </div>
        <div className="space-y-1">
          {[1,2,3,4].map(i => <div key={i} className="skeleton-shimmer h-5 rounded-full" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Direction summary */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'LONG', icon: TrendingUp, color: 'text-accent-green', stats: dirStats.long },
          { label: 'SHORT', icon: TrendingDown, color: 'text-accent-red', stats: dirStats.short },
        ].map(({ label, icon: Icon, color, stats }) => (
          <div key={label} className="stat-item">
            <div className="flex items-center gap-1.5 mb-1">
              <Icon size={10} className={color} />
              <span className={`text-[10px] font-bold ${color}`}>{label}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm font-bold font-mono text-th">
                {stats.total > 0 ? `${((stats.wins / stats.total) * 100).toFixed(0)}% WR` : '—'}
              </span>
              <span className="text-[9px] text-th-dim">
                {stats.wins}W / {stats.losses}L ({stats.total})
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Pattern Win Rate Bars */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5">
            <BarChart3 size={10} className="text-th-muted" />
            <span className="text-[10px] text-th-muted uppercase tracking-wider font-medium">Pattern Win Rate</span>
          </div>
          <div className="flex items-center gap-1">
            <Filter size={8} className="text-th-dim" />
            {(['count', 'win_rate', 'pattern'] as SortBy[]).map(s => (
              <button key={s} onClick={() => setSortBy(s)}
                className={`text-[9px] px-1.5 py-0.5 rounded transition-colors ${
                  sortBy === s ? 'bg-accent-blue/20 text-accent-blue' : 'text-th-dim hover:text-th-muted'
                }`}>
                {s === 'count' ? 'Count' : s === 'win_rate' ? 'WR' : 'A-Z'}
              </button>
            ))}
          </div>
        </div>
        {patterns.length === 0 ? (
          <div className="text-xs text-th-muted text-center py-4">Brak danych o patternach</div>
        ) : (
          <div className="space-y-0.5">
            {patterns.slice(0, 15).map(p => <PatternBar key={p.pattern} stat={p} />)}
          </div>
        )}
      </div>

      {/* Session x Direction Heatmap */}
      {trades.length > 0 && <Heatmap trades={trades} />}
    </div>
  );
});
