/**
 * src/components/dashboard/OverviewStrip.tsx — Compact metrics bar
 *
 * Horizontal strip showing key trading metrics at a glance:
 * P&L, Win Rate, Open Positions, Active Alerts, Ensemble Signal
 */

import { memo } from 'react';
import { TrendingUp, TrendingDown, Target, Bell, Brain, Minus } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI, riskAPI } from '../../api/client';
import { AnimatePresence, motion } from 'motion/react';

interface RiskMetrics {
  total: number;
  wins: number;
  losses: number;
  win_rate: number;
  profit_factor: number;
  expectancy: number;
  total_profit: number;
}

interface RiskStatus {
  halted: boolean;
  daily_loss_pct: number;
  consecutive_losses: number;
}

function Metric({ label, value, color, icon: Icon }: {
  label: string;
  value: string | number;
  color?: string;
  icon?: typeof TrendingUp;
}) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5">
      {Icon && <Icon size={11} className={color ?? 'text-th-muted'} />}
      <span className="text-[9px] text-th-muted uppercase tracking-wider">{label}</span>
      <span className={`text-xs font-bold font-mono ${color ?? 'text-th'}`}>{value}</span>
    </div>
  );
}

export const OverviewStrip = memo(function OverviewStrip() {
  const currentSignal = useTradingStore(s => s.currentSignal);
  const portfolio = useTradingStore(s => s.portfolio);

  const { data: metrics } = usePollingQuery<RiskMetrics>(
    'overview-risk-metrics',
    () => analysisAPI.getRiskMetrics(),
    60_000,
  );

  const { data: risk } = usePollingQuery<RiskStatus>(
    'overview-risk-status',
    () => riskAPI.getStatus(),
    30_000,
  );

  const pnl = portfolio?.pnl ?? 0;
  const pnlPositive = pnl >= 0;
  const wr = metrics ? (metrics.win_rate * 100).toFixed(0) : '--';
  const pf = metrics?.profit_factor ? (metrics.profit_factor >= 999 ? '∞' : metrics.profit_factor.toFixed(1)) : '--';
  const totalTrades = metrics?.total ?? 0;

  const signal = currentSignal?.consensus ?? 'HOLD';
  const signalColor = signal.includes('BUY') ? 'text-accent-green'
    : signal.includes('SELL') ? 'text-accent-red'
    : 'text-th-muted';

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.5 }}
        className="flex items-center gap-0 overflow-x-auto scrollbar-none"
        style={{
          background: 'var(--color-surface)',
          borderBottom: '1px solid rgba(168,85,247,0.08)',
        }}
      >
        {/* P&L */}
        <Metric
          label="P&L"
          value={`${pnlPositive ? '+' : ''}$${pnl.toFixed(0)}`}
          color={pnlPositive ? 'text-accent-green' : 'text-accent-red'}
          icon={pnlPositive ? TrendingUp : TrendingDown}
        />

        <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

        {/* Win Rate */}
        <Metric
          label="WR"
          value={`${wr}%`}
          color={Number(wr) >= 50 ? 'text-accent-green' : Number(wr) > 0 ? 'text-accent-orange' : 'text-th-muted'}
          icon={Target}
        />

        <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

        {/* Profit Factor */}
        <Metric
          label="PF"
          value={pf}
          color={Number(pf) >= 2 ? 'text-accent-green' : Number(pf) >= 1 ? 'text-accent-orange' : 'text-accent-red'}
        />

        <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

        {/* Total Trades */}
        <Metric label="Trades" value={totalTrades} icon={Minus} />

        <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

        {/* Ensemble Signal */}
        <Metric
          label="Signal"
          value={signal}
          color={signalColor}
          icon={Brain}
        />

        <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

        {/* Risk Status */}
        {risk?.halted ? (
          <Metric label="Risk" value="HALTED" color="text-accent-red" icon={Bell} />
        ) : (
          <Metric
            label="Loss"
            value={`${(risk?.daily_loss_pct ?? 0).toFixed(1)}%`}
            color={
              (risk?.daily_loss_pct ?? 0) > 3 ? 'text-accent-red'
              : (risk?.daily_loss_pct ?? 0) > 1 ? 'text-accent-orange'
              : 'text-accent-green'
            }
          />
        )}

        {/* Consecutive losses badge */}
        {(risk?.consecutive_losses ?? 0) >= 3 && (
          <>
            <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />
            <div className="flex items-center gap-1 px-2 py-1 text-[9px] font-bold text-accent-red">
              <Bell size={9} className="animate-pulse" />
              {risk!.consecutive_losses} losses
            </div>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
});
