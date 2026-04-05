/**
 * src/components/dashboard/SignalPanel.tsx - Current trading signal display
 */

import { useEffect, useState } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { signalsAPI } from '../../api/client';
import type { Signal } from '../../types/trading';
import { AlertTriangle } from 'lucide-react';

const CONSENSUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  STRONG_BUY: { bg: 'bg-green-950/20', border: 'border-green-600/30', text: 'text-green-400' },
  BUY: { bg: 'bg-green-950/10', border: 'border-green-600/20', text: 'text-green-400' },
  HOLD: { bg: 'bg-blue-950/10', border: 'border-blue-600/20', text: 'text-blue-400' },
  SELL: { bg: 'bg-red-950/10', border: 'border-red-600/20', text: 'text-red-400' },
  STRONG_SELL: { bg: 'bg-red-950/20', border: 'border-red-600/30', text: 'text-red-400' },
};

const MODEL_COLORS: Record<string, string> = {
  BUY: 'text-green-400', SELL: 'text-red-400', HOLD: 'text-blue-400',
  UP: 'text-green-400', DOWN: 'text-red-400', NEUTRAL: 'text-blue-400',
};

export function SignalPanel() {
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
      } catch (err) {
        console.error('Error fetching signal:', err);
        setError('Failed to load signal');
      } finally {
        setLoading(false);
      }
    };

    void fetchSignal();
    // Refresh every 60 seconds
    const interval = setInterval(fetchSignal, 60000);
    return () => clearInterval(interval);
  }, [setCurrentSignal]);

  if (loading && !signal) {
    return <div className="flex items-center justify-center h-32 text-gray-500 text-sm">Loading signal...</div>;
  }

  if (error && !signal) {
    return (
      <div className="flex items-center justify-center h-32 text-red-400 text-xs gap-2">
        <AlertTriangle size={14} /> {error}
      </div>
    );
  }

  if (!signal) return null;

  const cs = CONSENSUS_COLORS[signal.consensus] || CONSENSUS_COLORS.HOLD;

  return (
    <div className="space-y-3">
      {/* Consensus */}
      <div className={`${cs.bg} border ${cs.border} rounded-lg p-3`}>
        <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Consensus</div>
        <div className="flex items-end justify-between">
          <div>
            <div className={`text-2xl font-bold ${cs.text}`}>{signal.consensus}</div>
            <div className="text-xs text-gray-500 mt-1 font-mono">
              Score: <span className={`${cs.text} font-semibold`}>{signal.consensus_score.toFixed(2)}</span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-500">Price</div>
            <div className="text-lg font-bold text-white font-mono">${signal.current_price.toFixed(2)}</div>
          </div>
        </div>
      </div>

      {/* Models */}
      <div className="space-y-2">
        <div className="text-xs text-gray-500 font-medium uppercase tracking-wider">Models</div>

        {/* RL Agent */}
        <div className="bg-dark-bg rounded-lg p-2.5 border border-dark-secondary">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500" />
              <span className="text-xs font-medium text-gray-400">RL Agent</span>
            </div>
            <span className={`text-xs font-bold ${MODEL_COLORS[signal.rl_action] || 'text-gray-400'}`}>{signal.rl_action}</span>
          </div>
          <div className="flex justify-between text-xs text-gray-500 mt-1.5 font-mono">
            <span>{(signal.rl_confidence * 100).toFixed(1)}%</span>
            <span>ε {signal.rl_epsilon.toFixed(3)}</span>
          </div>
        </div>

        {/* LSTM */}
        <div className="bg-dark-bg rounded-lg p-2.5 border border-dark-secondary">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-purple-500" />
              <span className="text-xs font-medium text-gray-400">LSTM</span>
            </div>
            <span className={`text-xs font-bold ${signal.lstm_change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {signal.lstm_change_pct >= 0 ? '+' : ''}{signal.lstm_change_pct.toFixed(2)}%
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-1.5 font-mono">
            Pred: ${signal.lstm_prediction.toFixed(2)}
          </div>
        </div>

        {/* XGBoost */}
        <div className="bg-dark-bg rounded-lg p-2.5 border border-dark-secondary">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-orange-500" />
              <span className="text-xs font-medium text-gray-400">XGBoost</span>
            </div>
            <span className={`text-xs font-bold ${MODEL_COLORS[signal.xgb_direction] || 'text-gray-400'}`}>{signal.xgb_direction}</span>
          </div>
          <div className="text-xs text-gray-500 mt-1.5 font-mono">
            Prob: {(signal.xgb_probability * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {lastUpdate && (
        <div className="text-xs text-gray-600 pt-2 border-t border-dark-secondary font-mono">
          Updated: {lastUpdate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      )}
    </div>
  );
}
