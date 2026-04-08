/**
 * src/components/dashboard/RiskMetrics.tsx — Professional risk analytics widget
 *
 * Shows: profit factor, expectancy, max drawdown, consecutive streaks.
 * Polls every 2 minutes (metrics rarely change).
 */

import { memo } from 'react';
import { Shield, TrendingDown, TrendingUp, Target, Flame, Zap } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';

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

function MetricCard({ label, value, icon: Icon, color, subtitle }: {
  label: string;
  value: string;
  icon: typeof Shield;
  color: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-dark-bg rounded p-2 border border-dark-secondary">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon size={10} className={color} />
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</span>
      </div>
      <div className={`text-sm font-bold font-mono ${color}`}>{value}</div>
      {subtitle && <div className="text-[9px] text-gray-600 mt-0.5">{subtitle}</div>}
    </div>
  );
}

export const RiskMetrics = memo(function RiskMetrics() {
  const { data, isLoading } = usePollingQuery<RiskData>(
    'risk-metrics',
    () => analysisAPI.getRiskMetrics(),
    60_000, // 1 minute
  );

  if (isLoading && !data) {
    return (
      <div className="text-xs text-gray-500 text-center py-4">Ładowanie metryk...</div>
    );
  }

  if (!data || data.total === 0) {
    return (
      <div className="text-xs text-gray-500 text-center py-4">
        Brak danych — metryki pojawią się po pierwszych zamkniętych transakcjach
      </div>
    );
  }

  const pfColor = data.profit_factor >= 2 ? 'text-green-400'
    : data.profit_factor >= 1 ? 'text-amber-400'
    : 'text-red-400';

  const expColor = data.expectancy > 0 ? 'text-green-400' : 'text-red-400';

  return (
    <div className="space-y-2">
      {/* Top row: Key ratios */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
        <MetricCard
          label="Profit Factor"
          value={data.profit_factor >= 999 ? '∞' : data.profit_factor.toFixed(2)}
          icon={Target}
          color={pfColor}
          subtitle="Zysk / Strata"
        />
        <MetricCard
          label="Expectancy"
          value={`$${data.expectancy.toFixed(2)}`}
          icon={Zap}
          color={expColor}
          subtitle="Oczekiwana wartość / trade"
        />
        <MetricCard
          label="Max Drawdown"
          value={`$${data.max_drawdown.toFixed(2)}`}
          icon={TrendingDown}
          color="text-red-400"
          subtitle="Najgłębsze obsunięcie"
        />
      </div>

      {/* Second row: Averages & Streaks */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        <MetricCard
          label="Avg Win"
          value={`$${data.avg_win.toFixed(2)}`}
          icon={TrendingUp}
          color="text-green-400"
        />
        <MetricCard
          label="Avg Loss"
          value={`$${data.avg_loss.toFixed(2)}`}
          icon={TrendingDown}
          color="text-red-400"
        />
        <MetricCard
          label="Win Streak"
          value={`${data.max_consecutive_wins}`}
          icon={Flame}
          color="text-green-400"
          subtitle="Max pod rząd"
        />
        <MetricCard
          label="Loss Streak"
          value={`${data.max_consecutive_losses}`}
          icon={Shield}
          color="text-red-400"
          subtitle="Max pod rząd"
        />
      </div>

      {/* Total P&L */}
      <div className="bg-dark-bg rounded p-2 border border-dark-secondary flex items-center justify-between">
        <span className="text-xs text-gray-400">Total P&L</span>
        <span className={`text-sm font-bold font-mono ${data.total_profit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {data.total_profit >= 0 ? '+' : ''}${data.total_profit.toFixed(2)}
        </span>
      </div>
    </div>
  );
});

