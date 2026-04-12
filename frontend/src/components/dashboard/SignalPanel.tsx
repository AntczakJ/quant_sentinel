/**
 * src/components/dashboard/SignalPanel.tsx - Current trading signal display
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { signalsAPI } from '../../api/client';
import type { Signal } from '../../types/trading';
import { AlertTriangle } from 'lucide-react';
import { useToast } from '../ui/Toast';

const CONSENSUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  STRONG_BUY: { bg: 'bg-accent-green/15', border: 'border-accent-green/30', text: 'text-accent-green' },
  BUY: { bg: 'bg-accent-green/8', border: 'border-accent-green/20', text: 'text-accent-green' },
  HOLD: { bg: 'bg-accent-blue/8', border: 'border-accent-blue/20', text: 'text-accent-blue' },
  SELL: { bg: 'bg-accent-red/8', border: 'border-accent-red/20', text: 'text-accent-red' },
  STRONG_SELL: { bg: 'bg-accent-red/15', border: 'border-accent-red/30', text: 'text-accent-red' },
};

const MODEL_COLORS: Record<string, string> = {
  BUY: 'text-accent-green', SELL: 'text-accent-red', HOLD: 'text-accent-blue',
  UP: 'text-accent-green', DOWN: 'text-accent-red', NEUTRAL: 'text-accent-blue',
};

export const SignalPanel = memo(function SignalPanel() {
  const toast = useToast();
  const { setCurrentSignal } = useTradingStore();
  const [signal, setSignal] = useState<Signal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    const fetchSignal = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await signalsAPI.getCurrent();
        setSignal(data);
        setCurrentSignal(data);
        setLastUpdate(new Date());
      } catch {
        toast.error('Failed to load signal');
        setError('Failed to load signal');
      } finally {
        setLoading(false);
      }
    };

    // Stagger by 3s to let market endpoints (candles, ticker) settle first
    const initTimer = setTimeout(() => void fetchSignal(), 3000);
    // Refresh every 45 seconds
    const interval = setInterval(fetchSignal, 45000);
    return () => { clearTimeout(initTimer); clearInterval(interval); };
  }, [setCurrentSignal]);

  if (loading && !signal) {
    return (
      <div className="space-y-3">
        <div className="skeleton-shimmer h-8 w-24 rounded" />
        <div className="skeleton-shimmer h-4 rounded-full" />
        <div className="skeleton-shimmer h-4 w-3/4 rounded-full" />
        <div className="skeleton-shimmer h-16 rounded-lg" />
      </div>
    );
  }

  if (error && !signal) {
    return (
      <div className="flex items-center justify-center h-32 text-accent-red text-xs gap-2">
        <AlertTriangle size={14} /> {error}
      </div>
    );
  }

  if (!signal) {return null;}

  const cs = CONSENSUS_COLORS[signal.consensus] || CONSENSUS_COLORS.HOLD;

  return (
    <div className="space-y-4">
      {/* Consensus — hero section */}
      <div className={`${cs.bg} border ${cs.border} rounded-xl p-4`}>
        <div className="flex items-end justify-between">
          <div>
            <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1.5">Consensus</div>
            <div className={`text-3xl font-bold ${cs.text} tracking-tight`}>{signal.consensus}</div>
            <div className="text-xs text-th-muted mt-1.5 font-mono">
              Score: <span className={`${cs.text} font-semibold`}>{(signal.consensus_score ?? 0).toFixed(2)}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1">Price</div>
            <div className="text-xl font-bold text-th font-mono">${(signal.current_price ?? 0).toFixed(2)}</div>
          </div>
        </div>
      </div>

      {/* Models — horizontal on wide, vertical on narrow */}
      <div>
        <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-3">Models</div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
          {/* RL Agent */}
          <div className="model-card">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-blue shadow-glow-blue" />
              <span className="text-[11px] font-medium text-th-secondary">RL Agent</span>
            </div>
            <div className={`text-lg font-bold ${MODEL_COLORS[signal.rl_action] || 'text-th-secondary'}`}>{signal.rl_action}</div>
            <div className="flex justify-between text-[10px] text-th-muted mt-2 font-mono">
              <span>{(signal.rl_confidence * 100).toFixed(1)}%</span>
              <span className="text-th-dim">{signal.rl_epsilon.toFixed(3)}</span>
            </div>
          </div>

          {/* LSTM */}
          <div className="model-card">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-purple shadow-[0_0_6px_rgb(var(--c-purple)/0.4)]" />
              <span className="text-[11px] font-medium text-th-secondary">LSTM</span>
            </div>
            <div className={`text-lg font-bold ${signal.lstm_change_pct >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
              {signal.lstm_change_pct >= 0 ? '+' : ''}{signal.lstm_change_pct.toFixed(2)}%
            </div>
            <div className="text-[10px] text-th-muted mt-2 font-mono">
              Pred: ${signal.lstm_prediction.toFixed(2)}
            </div>
          </div>

          {/* XGBoost */}
          <div className="model-card">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-orange shadow-[0_0_6px_rgb(var(--c-orange)/0.4)]" />
              <span className="text-[11px] font-medium text-th-secondary">XGBoost</span>
            </div>
            <div className={`text-lg font-bold ${MODEL_COLORS[signal.xgb_direction] || 'text-th-secondary'}`}>{signal.xgb_direction}</div>
            <div className="text-[10px] text-th-muted mt-2 font-mono">
              Prob: {(signal.xgb_probability * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {lastUpdate && (
        <div className="text-[10px] text-th-dim pt-3 border-t border-dark-secondary font-mono">
          Updated: {lastUpdate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      )}
    </div>
  );
});
