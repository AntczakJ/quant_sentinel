/**
 * src/components/dashboard/SignalPanel.tsx - Current trading signal display
 */

import { useEffect, useState, memo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { useTradingStore } from '../../store/tradingStore';
import { signalsAPI } from '../../api/client';
import type { Signal } from '../../types/trading';
import { AlertTriangle } from 'lucide-react';
import { useToast } from '../ui/Toast';
import { staggerContainer, staggerItem, DUR_MD, EASE_OUT } from '../../lib/motion';

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
    <motion.div
      variants={staggerContainer(0.06)}
      initial="hidden"
      animate="show"
      className="space-y-4"
    >
      {/* Consensus — hero tile. The consensus value itself is keyed so it
          animates on change (cross-fade + scale) — strong signal that a new
          decision just arrived. */}
      <motion.div variants={staggerItem} className={`relative overflow-hidden ${cs.bg} border ${cs.border} rounded-xl p-4`}>
        <div className="flex items-end justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] text-th-muted font-medium uppercase tracking-[0.14em] mb-1.5">
              Consensus
            </div>
            <AnimatePresence mode="wait">
              <motion.div
                key={signal.consensus}
                initial={{ opacity: 0, y: 6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.98 }}
                transition={{ duration: DUR_MD, ease: EASE_OUT }}
                className={`text-[30px] font-display font-semibold ${cs.text} tracking-tight leading-none`}
              >
                {signal.consensus}
              </motion.div>
            </AnimatePresence>
            <div className="text-xs text-th-muted mt-2 font-mono tabular-nums">
              Score: <span className={`${cs.text} font-semibold`}>{(signal.consensus_score ?? 0).toFixed(2)}</span>
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-[10px] text-th-muted font-medium uppercase tracking-[0.14em] mb-1">
              Price
            </div>
            <div className="text-xl font-display font-semibold text-th font-mono tabular-nums">
              ${(signal.current_price ?? 0).toFixed(2)}
            </div>
          </div>
        </div>
      </motion.div>

      {/* Models — three cards, hover lift, dot with glow emphasis */}
      <motion.div variants={staggerItem}>
        <div className="text-[10px] text-th-muted font-medium uppercase tracking-[0.14em] mb-3">Models</div>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
          {/* RL Agent */}
          <div className="model-card transition-colors hover:border-th-border-h">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-blue shadow-glow-blue" />
              <span className="text-[11px] font-medium text-th-secondary">RL Agent</span>
            </div>
            <div className={`text-lg font-semibold font-display tracking-tight ${MODEL_COLORS[signal.rl_action] || 'text-th-secondary'}`}>
              {signal.rl_action}
            </div>
            {/* Confidence bar — quick visual of strength */}
            <div className="mt-2 h-1 rounded-full bg-dark-tertiary overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${signal.rl_confidence * 100}%` }}
                transition={{ duration: 0.6, ease: EASE_OUT }}
                className="h-full bg-accent-blue"
              />
            </div>
            <div className="flex justify-between text-[10px] text-th-muted mt-1.5 font-mono tabular-nums">
              <span>{(signal.rl_confidence * 100).toFixed(1)}%</span>
              <span className="text-th-dim">ε {signal.rl_epsilon.toFixed(3)}</span>
            </div>
          </div>

          {/* LSTM */}
          <div className="model-card transition-colors hover:border-th-border-h">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-purple shadow-[0_0_6px_rgb(var(--c-purple)/0.4)]" />
              <span className="text-[11px] font-medium text-th-secondary">LSTM</span>
            </div>
            <div className={`text-lg font-semibold font-display tracking-tight ${signal.lstm_change_pct >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
              {signal.lstm_change_pct >= 0 ? '+' : ''}{signal.lstm_change_pct.toFixed(2)}%
            </div>
            <div className="text-[10px] text-th-muted mt-2 font-mono tabular-nums">
              Pred: ${signal.lstm_prediction.toFixed(2)}
            </div>
          </div>

          {/* XGBoost */}
          <div className="model-card transition-colors hover:border-th-border-h">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-accent-orange shadow-[0_0_6px_rgb(var(--c-orange)/0.4)]" />
              <span className="text-[11px] font-medium text-th-secondary">XGBoost</span>
            </div>
            <div className={`text-lg font-semibold font-display tracking-tight ${MODEL_COLORS[signal.xgb_direction] || 'text-th-secondary'}`}>
              {signal.xgb_direction}
            </div>
            <div className="mt-2 h-1 rounded-full bg-dark-tertiary overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${signal.xgb_probability * 100}%` }}
                transition={{ duration: 0.6, ease: EASE_OUT }}
                className="h-full bg-accent-orange"
              />
            </div>
            <div className="text-[10px] text-th-muted mt-1.5 font-mono tabular-nums">
              Prob: {(signal.xgb_probability * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </motion.div>

      {lastUpdate && (
        <motion.div variants={staggerItem} className="text-[10px] text-th-dim pt-3 border-t border-th-border font-mono tabular-nums">
          Updated: {lastUpdate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </motion.div>
      )}
    </motion.div>
  );
});
