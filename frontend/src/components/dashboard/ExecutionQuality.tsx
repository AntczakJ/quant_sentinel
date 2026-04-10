/**
 * src/components/dashboard/ExecutionQuality.tsx — Trade execution quality report
 *
 * Displays fill rate, slippage, and win rate by setup grade
 * from /api/export/execution-quality endpoint.
 */

import { memo } from 'react';
import { Activity, Crosshair, Award, TrendingUp } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { exportAPI } from '../../api/client';
import { EmptyState } from '../ui/EmptyState';

interface GradeStats {
  wins: number;
  losses: number;
  pnl: number;
  win_rate: number;
  total: number;
}

interface ExecutionData {
  period_days: number;
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  fill_rate: number;
  avg_slippage: number;
  slippage_samples: number;
  by_grade: Record<string, GradeStats>;
  error?: string;
}

/* ── Grade color mapping ─────────────────────────────────────────────── */
const GRADE_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  'A+': { bg: 'bg-accent-green/12', text: 'text-accent-green', border: 'border-accent-green/25' },
  'A':  { bg: 'bg-accent-green/8',  text: 'text-accent-green', border: 'border-accent-green/20' },
  'B':  { bg: 'bg-accent-blue/8',   text: 'text-accent-blue',  border: 'border-accent-blue/20' },
  'C':  { bg: 'bg-accent-orange/8', text: 'text-accent-orange', border: 'border-accent-orange/20' },
  'D':  { bg: 'bg-accent-red/8',    text: 'text-accent-red',   border: 'border-accent-red/20' },
};

function getGradeStyle(grade: string) {
  return GRADE_COLORS[grade] ?? { bg: 'bg-dark-secondary', text: 'text-th-secondary', border: 'border-dark-secondary' };
}

/* ── Fill rate / slippage stat card ──────────────────────────────────── */
function StatCard({ label, value, icon: Icon, color, subtitle }: {
  label: string; value: string; icon: typeof Activity; color: string; subtitle?: string;
}) {
  return (
    <div className="stat-item">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={10} className={color} />
        <span className="text-[10px] text-th-muted uppercase tracking-wider font-medium">{label}</span>
      </div>
      <div className={`text-lg font-bold font-mono ${color}`}>{value}</div>
      {subtitle && <div className="text-[9px] text-th-dim mt-0.5">{subtitle}</div>}
    </div>
  );
}

/* ── Grade row in the table ──────────────────────────────────────────── */
function GradeRow({ grade, stats }: { grade: string; stats: GradeStats }) {
  const style = getGradeStyle(grade);
  const wrColor = stats.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red';
  const pnlColor = stats.pnl >= 0 ? 'text-accent-green' : 'text-accent-red';

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${style.bg} ${style.border}`}>
      {/* Grade badge */}
      <span className={`text-sm font-bold font-mono w-8 ${style.text}`}>{grade}</span>

      {/* Win rate bar */}
      <div className="flex-1">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-[10px] text-th-muted">
            {stats.wins}W / {stats.losses}L
          </span>
          <span className={`text-[10px] font-bold font-mono ${wrColor}`}>
            {(stats.win_rate * 100).toFixed(0)}%
          </span>
        </div>
        <div className="h-1.5 bg-dark-secondary rounded-full overflow-hidden">
          <div className="h-full bg-accent-green/60 rounded-full transition-all duration-500"
            style={{ width: `${Math.min(stats.win_rate * 100, 100)}%` }} />
        </div>
      </div>

      {/* P&L */}
      <div className="text-right min-w-[70px]">
        <div className={`text-xs font-bold font-mono ${pnlColor}`}>
          {stats.pnl >= 0 ? '+' : ''}${stats.pnl.toFixed(2)}
        </div>
        <div className="text-[9px] text-th-dim">{stats.total} trades</div>
      </div>
    </div>
  );
}

export const ExecutionQuality = memo(function ExecutionQuality() {
  const { data, isLoading } = usePollingQuery<ExecutionData>(
    'execution-quality',
    () => exportAPI.getExecutionQuality(30),
    120_000, // 2 min — this is a heavy query
  );

  if (isLoading && !data) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {[1,2,3,4].map(i => <div key={i} className="skeleton-shimmer h-16 rounded-lg" />)}
        </div>
        <div className="space-y-1.5">
          {[1,2,3].map(i => <div key={i} className="skeleton-shimmer h-12 rounded-lg" />)}
        </div>
      </div>
    );
  }

  if (!data || data.error || data.total_trades === 0) {
    return (
      <EmptyState
        icon="report"
        message={data?.error ?? 'Brak danych o egzekucji'}
        description="Raport pojawi sie po pierwszych zamknietych transakcjach"
      />
    );
  }

  // Sort grades: A+ > A > B > C > D > Unknown
  const gradeOrder = ['A+', 'A', 'B', 'C', 'D'];
  const sortedGrades = Object.entries(data.by_grade).sort(([a], [b]) => {
    const ia = gradeOrder.indexOf(a);
    const ib = gradeOrder.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });

  const fillColor = data.fill_rate >= 0.8 ? 'text-accent-green'
    : data.fill_rate >= 0.5 ? 'text-accent-orange'
    : 'text-accent-red';

  const slippageColor = data.avg_slippage <= 0.5 ? 'text-accent-green'
    : data.avg_slippage <= 2 ? 'text-accent-orange'
    : 'text-accent-red';

  return (
    <div className="space-y-3">
      {/* ── Top stats row ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <StatCard
          label="Fill Rate"
          value={`${(data.fill_rate * 100).toFixed(1)}%`}
          icon={Crosshair}
          color={fillColor}
          subtitle={`${data.total_trades} z propozycji`}
        />
        <StatCard
          label="Avg Slippage"
          value={`$${data.avg_slippage.toFixed(4)}`}
          icon={Activity}
          color={slippageColor}
          subtitle={`${data.slippage_samples} probek`}
        />
        <StatCard
          label="Avg P&L"
          value={`${data.avg_pnl >= 0 ? '+' : ''}$${data.avg_pnl.toFixed(2)}`}
          icon={TrendingUp}
          color={data.avg_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}
          subtitle="per trade"
        />
        <StatCard
          label="Period"
          value={`${data.period_days}d`}
          icon={Award}
          color="text-accent-blue"
          subtitle={`${data.total_trades} trades`}
        />
      </div>

      {/* ── Win Rate by Grade ─────────────────────────────────── */}
      {sortedGrades.length > 0 && (
        <div>
          <div className="text-[10px] text-th-muted uppercase tracking-wider font-medium mb-2">
            Win Rate by Setup Grade
          </div>
          <div className="space-y-1.5">
            {sortedGrades.map(([grade, stats]) => (
              <GradeRow key={grade} grade={grade} stats={stats} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
});
