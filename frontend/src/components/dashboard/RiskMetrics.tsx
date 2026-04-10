/**
 * src/components/dashboard/RiskMetrics.tsx — Professional risk analytics dashboard
 *
 * Displays full risk profile from /api/analysis/risk-metrics:
 * Profit factor, expectancy, max drawdown, Sharpe-like ratios,
 * win/loss streaks, average trade sizes, and total P&L.
 */

import { memo } from 'react';
import {
  Shield, TrendingDown, TrendingUp, Flame, Zap,
  BarChart3, Percent, Activity,
} from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';
import { Tooltip } from '../ui/Tooltip';

interface RiskData {
  total: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  expectancy: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  max_drawdown: number;
  total_profit: number;
}

/* ── Mini ring gauge (used for win rate and profit factor) ──────────────── */
function RingGauge({ value, max, label, color, size = 56 }: {
  value: number; max: number; label: string; color: string; size?: number;
}) {
  const pct = Math.min(value / max, 1);
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - pct);
  const center = size / 2;

  return (
    <div className="flex flex-col items-center gap-0.5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={center} cy={center} r={r} fill="none"
          stroke="rgb(var(--c-border))" strokeWidth="4" />
        <circle cx={center} cy={center} r={r} fill="none"
          stroke={color} strokeWidth="4" strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={offset}
          transform={`rotate(-90 ${center} ${center})`}
          className="transition-all duration-700 ease-out" />
      </svg>
      <span className="text-[9px] text-th-muted font-medium">{label}</span>
    </div>
  );
}

/* ── Horizontal bar comparing two values (win avg vs loss avg) ─────────── */
function CompareBar({ left, right, leftLabel, rightLabel }: {
  left: number; right: number; leftLabel: string; rightLabel: string;
}) {
  const total = left + right;
  const leftPct = total > 0 ? (left / total) * 100 : 50;

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] font-medium">
        <span className="text-accent-green">{leftLabel}: ${left.toFixed(2)}</span>
        <span className="text-accent-red">{rightLabel}: ${right.toFixed(2)}</span>
      </div>
      <div className="relative h-2 rounded-full overflow-hidden bg-accent-red/30">
        <div className="absolute inset-y-0 left-0 bg-accent-green/70 rounded-full transition-all duration-500"
          style={{ width: `${leftPct}%` }} />
      </div>
    </div>
  );
}

/* ── Streak indicator (visual dots) ───────────────────────────────────── */
function StreakDots({ count, maxDisplay, color }: { count: number; maxDisplay: number; color: string }) {
  const dots = Math.min(count, maxDisplay);
  return (
    <div className="flex items-center gap-0.5">
      {Array.from({ length: dots }).map((_, i) => (
        <div key={i} className={`w-1.5 h-1.5 rounded-full ${color}`} />
      ))}
      {count > maxDisplay && (
        <span className="text-[9px] text-th-dim ml-0.5">+{count - maxDisplay}</span>
      )}
    </div>
  );
}

/* ── Main metric card ────────────────────────────────────────────────── */
function MetricCard({ label, value, icon: Icon, color, subtitle, highlight, tooltip }: {
  label: string;
  value: string;
  icon: typeof Shield;
  color: string;
  subtitle?: string;
  highlight?: boolean;
  tooltip?: string;
}) {
  const labelEl = (
    <span className="text-[10px] text-th-muted uppercase tracking-wider font-medium">{label}</span>
  );
  return (
    <div className={`stat-item ${highlight ? 'ring-1 ring-accent-green/20' : ''}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={10} className={color} />
        {tooltip ? <Tooltip content={tooltip}>{labelEl}</Tooltip> : labelEl}
      </div>
      <div className={`text-sm font-bold font-mono ${color}`}>{value}</div>
      {subtitle && <div className="text-[9px] text-th-dim mt-0.5">{subtitle}</div>}
    </div>
  );
}

export const RiskMetrics = memo(function RiskMetrics() {
  const { data, isLoading } = usePollingQuery<RiskData>(
    'risk-metrics',
    () => analysisAPI.getRiskMetrics(),
    60_000,
  );

  if (isLoading && !data) {
    return (
      <div className="space-y-3">
        <div className="flex gap-4">
          <div className="skeleton-shimmer w-14 h-14 rounded-full" />
          <div className="skeleton-shimmer w-14 h-14 rounded-full" />
          <div className="flex-1 grid grid-cols-2 gap-2">
            <div className="skeleton-shimmer h-14 rounded-lg" />
            <div className="skeleton-shimmer h-14 rounded-lg" />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[1,2,3].map(i => <div key={i} className="skeleton-shimmer h-16 rounded-lg" />)}
        </div>
      </div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="text-xs text-th-muted text-center py-4">
        Brak danych — metryki pojawia sie po pierwszych zamknietych transakcjach
      </div>
    );
  }

  const pfColor = data.profit_factor >= 2 ? 'text-accent-green'
    : data.profit_factor >= 1 ? 'text-accent-orange'
    : 'text-accent-red';

  const expColor = data.expectancy > 0 ? 'text-accent-green' : 'text-accent-red';
  const wrColor = data.win_rate >= 0.5 ? 'text-accent-green' : 'text-accent-red';
  const pfDisplay = data.profit_factor >= 999 ? '∞' : data.profit_factor.toFixed(2);

  // Risk/reward ratio from avg win/loss
  const rrRatio = data.avg_loss > 0 ? data.avg_win / data.avg_loss : 0;
  const rrColor = rrRatio >= 2 ? 'text-accent-green' : rrRatio >= 1 ? 'text-accent-orange' : 'text-accent-red';

  return (
    <div className="space-y-3">
      {/* ── Hero row: Win Rate gauge + P/F gauge + Key stats ─────── */}
      <div className="flex items-start gap-4">
        {/* Gauges */}
        <div className="flex gap-3">
          <div className="flex flex-col items-center">
            <RingGauge value={data.win_rate * 100} max={100} label="Win Rate"
              color={data.win_rate >= 0.5 ? 'rgb(var(--c-green))' : 'rgb(var(--c-red))'} />
            <span className={`text-sm font-bold font-mono mt-0.5 ${wrColor}`}>
              {(data.win_rate * 100).toFixed(1)}%
            </span>
          </div>
          <div className="flex flex-col items-center">
            <RingGauge value={Math.min(data.profit_factor, 5)} max={5} label="Profit Factor"
              color={data.profit_factor >= 2 ? 'rgb(var(--c-green))' : data.profit_factor >= 1 ? 'rgb(var(--c-orange))' : 'rgb(var(--c-red))'} />
            <span className={`text-sm font-bold font-mono mt-0.5 ${pfColor}`}>
              {pfDisplay}
            </span>
          </div>
        </div>

        {/* Quick stats */}
        <div className="flex-1 grid grid-cols-2 gap-2">
          <div className="stat-item">
            <div className="flex items-center gap-1 mb-0.5">
              <Activity size={9} className="text-th-muted" />
              <span className="text-[9px] text-th-muted uppercase tracking-wider">Trades</span>
            </div>
            <div className="text-sm font-bold text-th font-mono">{data.total}</div>
            <div className="text-[9px] text-th-dim">
              <span className="text-accent-green">{data.wins}W</span>
              {' / '}
              <span className="text-accent-red">{data.losses}L</span>
            </div>
          </div>

          <div className="stat-item">
            <div className="flex items-center gap-1 mb-0.5">
              <Percent size={9} className="text-th-muted" />
              <span className="text-[9px] text-th-muted uppercase tracking-wider">R:R Ratio</span>
            </div>
            <div className={`text-sm font-bold font-mono ${rrColor}`}>
              {rrRatio.toFixed(2)}
            </div>
            <div className="text-[9px] text-th-dim">avg win / avg loss</div>
          </div>
        </div>
      </div>

      {/* ── Key ratios grid ────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
        <MetricCard
          label="Expectancy"
          value={`$${data.expectancy.toFixed(2)}`}
          icon={Zap}
          color={expColor}
          subtitle="Oczekiwana wartosc / trade"
          highlight={data.expectancy > 0}
          tooltip="Sredni zysk na transakcje = (WR × avgWin) - ((1-WR) × avgLoss)"
        />
        <MetricCard
          label="Max Drawdown"
          value={`$${data.max_drawdown.toFixed(2)}`}
          icon={TrendingDown}
          color="text-accent-red"
          subtitle="Najglebsze obsuniecie"
          tooltip="Maksymalne obsuniecie od szczytu equity do dolka"
        />
        <MetricCard
          label="Total P&L"
          value={`${data.total_profit >= 0 ? '+' : ''}$${data.total_profit.toFixed(2)}`}
          icon={data.total_profit >= 0 ? TrendingUp : TrendingDown}
          color={data.total_profit >= 0 ? 'text-accent-green' : 'text-accent-red'}
          highlight={data.total_profit > 0}
          tooltip="Calkowity zysk/strata ze wszystkich zamknietych transakcji"
        />
      </div>

      {/* ── Avg Win vs Avg Loss comparison bar ─────────────────── */}
      <div className="stat-item">
        <CompareBar
          left={data.avg_win} right={data.avg_loss}
          leftLabel="Avg Win" rightLabel="Avg Loss"
        />
      </div>

      {/* ── Streaks ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-2">
        <div className="stat-item">
          <div className="flex items-center gap-1 mb-1">
            <Flame size={10} className="text-accent-green" />
            <span className="text-[10px] text-th-muted uppercase tracking-wider">Win Streak</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold font-mono text-accent-green">{data.max_consecutive_wins}</span>
            <StreakDots count={data.max_consecutive_wins} maxDisplay={8} color="bg-accent-green" />
          </div>
        </div>
        <div className="stat-item">
          <div className="flex items-center gap-1 mb-1">
            <Shield size={10} className="text-accent-red" />
            <span className="text-[10px] text-th-muted uppercase tracking-wider">Loss Streak</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold font-mono text-accent-red">{data.max_consecutive_losses}</span>
            <StreakDots count={data.max_consecutive_losses} maxDisplay={8} color="bg-accent-red" />
          </div>
        </div>
      </div>

      {/* ── Risk summary bar ───────────────────────────────────── */}
      <div className="stat-item flex items-center gap-3">
        <BarChart3 size={12} className="text-th-muted" />
        <div className="flex-1 flex items-center gap-3 text-[10px]">
          <span className="text-th-muted">Risk Profile:</span>
          {data.profit_factor >= 2 && data.expectancy > 0 && data.max_drawdown < Math.abs(data.total_profit) ? (
            <span className="text-accent-green font-bold">ZDROWY</span>
          ) : data.profit_factor >= 1 ? (
            <span className="text-accent-orange font-bold">UMIARKOWANY</span>
          ) : (
            <span className="text-accent-red font-bold">RYZYKOWNY</span>
          )}
          <span className="text-th-dim">|</span>
          <span className="text-th-dim">
            DD/Profit: {data.total_profit > 0
              ? `${((data.max_drawdown / data.total_profit) * 100).toFixed(0)}%`
              : '—'}
          </span>
        </div>
      </div>
    </div>
  );
});
