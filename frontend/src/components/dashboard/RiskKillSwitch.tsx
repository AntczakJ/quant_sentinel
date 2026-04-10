/**
 * src/components/dashboard/RiskKillSwitch.tsx — Risk Kill Switch
 *
 * Compact header widget showing risk status (daily loss, consecutive losses, cooldown).
 * Red HALT button to emergency-stop trading; green RESUME to restart.
 */

import { memo, useState, useCallback } from 'react';
import { ShieldOff, ShieldCheck, Loader2, AlertTriangle, Clock, Activity } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { riskAPI } from '../../api/client';
import { useToast } from '../ui/Toast';

interface RiskStatus {
  halted: boolean;
  halt_reason?: string;
  daily_loss: number;
  daily_loss_limit: number;
  consecutive_losses: number;
  max_consecutive_losses: number;
  cooldown_until?: string;
  kelly_risk?: number;
  session?: string;
  spread?: number;
}

export const RiskKillSwitch = memo(function RiskKillSwitch() {
  const toast = useToast();
  const [actionLoading, setActionLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading, refetch } = usePollingQuery<RiskStatus>(
    'risk-status',
    () => riskAPI.getStatus(),
    15_000, // check every 15s
  );

  const handleHalt = useCallback(async () => {
    setActionLoading(true);
    try {
      const res = await riskAPI.halt('Manual halt via dashboard');
      if (res.success) {
        toast.warning('Trading HALTED');
        void refetch();
      }
    } catch (err: unknown) {
      toast.error(`Halt failed: ${err instanceof Error ? err.message : 'Error'}`);
    } finally {
      setActionLoading(false);
    }
  }, [toast, refetch]);

  const handleResume = useCallback(async () => {
    setActionLoading(true);
    try {
      const res = await riskAPI.resume();
      if (res.success) {
        toast.success('Trading RESUMED');
        void refetch();
      }
    } catch (err: unknown) {
      toast.error(`Resume failed: ${err instanceof Error ? err.message : 'Error'}`);
    } finally {
      setActionLoading(false);
    }
  }, [toast, refetch]);

  if (isLoading && !data) return null;
  if (!data) return null;

  const isHalted = data.halted;
  const dailyLossPct = data.daily_loss_limit > 0
    ? Math.min((data.daily_loss / data.daily_loss_limit) * 100, 100)
    : 0;
  const hasCooldown = data.cooldown_until && new Date(data.cooldown_until).getTime() > Date.now();

  return (
    <div className="relative">
      {/* Main button — compact, fits in header */}
      <button
        onClick={() => setExpanded(v => !v)}
        className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium transition-all border ${
          isHalted
            ? 'bg-accent-red/12 text-accent-red border-accent-red/30 animate-pulse'
            : hasCooldown
            ? 'bg-accent-orange/10 text-accent-orange border-accent-orange/25'
            : 'bg-accent-green/8 text-accent-green border-accent-green/20 hover:bg-accent-green/12'
        }`}
      >
        {isHalted ? <ShieldOff size={11} /> : <ShieldCheck size={11} />}
        <span className="hidden lg:inline">{isHalted ? 'HALTED' : 'Risk'}</span>
      </button>

      {/* Expanded dropdown */}
      {expanded && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setExpanded(false)} />

          {/* Panel */}
          <div className="absolute right-0 top-full mt-1 z-50 w-72 bg-dark-surface border border-dark-secondary rounded-xl shadow-xl p-3 space-y-3">
            {/* Status header */}
            <div className={`flex items-center gap-2 px-2 py-1.5 rounded-lg border ${
              isHalted
                ? 'bg-accent-red/10 border-accent-red/25'
                : 'bg-accent-green/8 border-accent-green/15'
            }`}>
              {isHalted ? <ShieldOff size={14} className="text-accent-red" /> : <ShieldCheck size={14} className="text-accent-green" />}
              <div className="flex-1">
                <div className={`text-xs font-bold ${isHalted ? 'text-accent-red' : 'text-accent-green'}`}>
                  {isHalted ? 'Trading HALTED' : 'Trading Active'}
                </div>
                {isHalted && data.halt_reason && (
                  <div className="text-[9px] text-th-muted mt-0.5 truncate">{data.halt_reason}</div>
                )}
              </div>
            </div>

            {/* Metrics */}
            <div className="space-y-2">
              {/* Daily Loss */}
              <div>
                <div className="flex items-center justify-between text-[10px] mb-0.5">
                  <span className="text-th-muted flex items-center gap-1">
                    <Activity size={8} /> Daily Loss
                  </span>
                  <span className={`font-mono font-bold ${dailyLossPct > 80 ? 'text-accent-red' : dailyLossPct > 50 ? 'text-accent-orange' : 'text-accent-green'}`}>
                    ${data.daily_loss.toFixed(2)} / ${data.daily_loss_limit.toFixed(2)}
                  </span>
                </div>
                <div className="h-1.5 bg-dark-secondary rounded-full overflow-hidden">
                  <div className={`h-full rounded-full transition-all duration-500 ${
                    dailyLossPct > 80 ? 'bg-accent-red' : dailyLossPct > 50 ? 'bg-accent-orange' : 'bg-accent-green'
                  }`} style={{ width: `${dailyLossPct}%` }} />
                </div>
              </div>

              {/* Consecutive losses */}
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-th-muted flex items-center gap-1">
                  <AlertTriangle size={8} /> Consecutive Losses
                </span>
                <span className={`font-mono font-bold ${
                  data.consecutive_losses >= data.max_consecutive_losses ? 'text-accent-red' :
                  data.consecutive_losses >= data.max_consecutive_losses * 0.7 ? 'text-accent-orange' : 'text-th-secondary'
                }`}>
                  {data.consecutive_losses} / {data.max_consecutive_losses}
                </span>
              </div>

              {/* Cooldown */}
              {hasCooldown && (
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-th-muted flex items-center gap-1">
                    <Clock size={8} /> Cooldown
                  </span>
                  <span className="font-mono text-accent-orange">
                    {data.cooldown_until}
                  </span>
                </div>
              )}

              {/* Kelly */}
              {data.kelly_risk !== undefined && (
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-th-muted">Kelly Risk %</span>
                  <span className="font-mono text-th-secondary">{(data.kelly_risk * 100).toFixed(2)}%</span>
                </div>
              )}
            </div>

            {/* Action button */}
            <div className="pt-1 border-t border-dark-secondary">
              {isHalted ? (
                <button
                  onClick={() => void handleResume()}
                  disabled={actionLoading}
                  className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all bg-accent-green/15 text-accent-green border border-accent-green/30 hover:bg-accent-green/25 disabled:opacity-50"
                >
                  {actionLoading ? <Loader2 size={12} className="animate-spin" /> : <ShieldCheck size={12} />}
                  Resume Trading
                </button>
              ) : (
                <button
                  onClick={() => void handleHalt()}
                  disabled={actionLoading}
                  className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all bg-accent-red/15 text-accent-red border border-accent-red/30 hover:bg-accent-red/25 disabled:opacity-50"
                >
                  {actionLoading ? <Loader2 size={12} className="animate-spin" /> : <ShieldOff size={12} />}
                  HALT Trading
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
});
