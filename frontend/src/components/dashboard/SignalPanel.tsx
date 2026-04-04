/**
 * src/components/dashboard/SignalPanel.tsx - Current trading signal display
 */

import { useEffect, useState } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { signalsAPI } from '../../api/client';
import type { Signal } from '../../types/trading';
import { AlertTriangle } from 'lucide-react';

const CONSENSUS_COLORS: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  STRONG_BUY: { bg: 'bg-green-900/30', border: 'border-green-500/50', text: 'text-green-400', icon: '🚀' },
  BUY: { bg: 'bg-green-900/20', border: 'border-green-500/30', text: 'text-green-300', icon: '📈' },
  HOLD: { bg: 'bg-blue-900/20', border: 'border-blue-500/30', text: 'text-blue-300', icon: '⏸️' },
  SELL: { bg: 'bg-red-900/20', border: 'border-red-500/30', text: 'text-red-300', icon: '📉' },
  STRONG_SELL: { bg: 'bg-red-900/30', border: 'border-red-500/50', text: 'text-red-400', icon: '💥' },
};

const MODEL_COLORS: Record<string, string> = {
  BUY: 'text-green-400',
  SELL: 'text-red-400',
  HOLD: 'text-blue-400',
  UP: 'text-green-400',
  DOWN: 'text-red-400',
  NEUTRAL: 'text-blue-400',
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

    fetchSignal();

    // Refresh every 5 seconds
    const interval = setInterval(fetchSignal, 5000);
    return () => clearInterval(interval);
  }, [setCurrentSignal]);

  if (loading && !signal) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading signal...</span>
      </div>
    );
  }

  if (error && !signal) {
    return (
      <div className="flex items-center justify-center h-40 bg-red-900/10 border border-red-500/30 rounded-lg">
        <div className="flex items-center gap-2 text-red-400">
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  if (!signal) return null;

  const consensusStyle = CONSENSUS_COLORS[signal.consensus] || CONSENSUS_COLORS.HOLD;

  return (
    <div className="space-y-4">
      {/* Consensus Signal - Main */}
      <div className={`${consensusStyle.bg} border-2 ${consensusStyle.border} rounded-xl p-5 backdrop-blur-md transition-all hover:shadow-glow`}>
        <div className="flex items-center gap-2 text-xs text-gray-400 mb-3 font-semibold uppercase tracking-wider">
          <span className="text-lg">⚡</span>
          CONSENSUS SIGNAL
        </div>

        <div className="flex items-end justify-between">
          <div>
            <div className={`text-4xl font-bold ${consensusStyle.text} font-display`}>
              {consensusStyle.icon} {signal.consensus}
            </div>
            <div className="text-xs text-gray-400 mt-3 font-mono">
              Score: <span className={`${consensusStyle.text} font-bold`}>{signal.consensus_score.toFixed(2)}/1.0</span>
            </div>
          </div>

          <div className="text-right">
            <div className="text-xs text-gray-400 font-semibold">Current Price</div>
            <div className="text-2xl font-bold text-accent-green font-mono">${signal.current_price.toFixed(2)}</div>
          </div>
        </div>
      </div>

      {/* Individual Model Signals */}
      <div className="space-y-3 mt-5">
        <div className="text-xs text-gray-400 font-bold uppercase tracking-wider font-display">🤖 Model Signals</div>

        {/* RL Agent */}
        <div className="card hover:shadow-glow-blue">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-accent-blue animate-pulse"></div>
              <span className="text-xs font-semibold text-gray-300 uppercase">RL Agent</span>
            </div>
            <div className={`text-sm font-bold ${MODEL_COLORS[signal.rl_action] || 'text-gray-400'}`}>
              {signal.rl_action}
            </div>
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-3 font-mono">
            <span>Confidence: <span className="text-accent-blue font-semibold">{(signal.rl_confidence * 100).toFixed(1)}%</span></span>
            <span>ε: <span className="text-accent-blue font-semibold">{signal.rl_epsilon.toFixed(3)}</span></span>
          </div>
        </div>

        {/* LSTM */}
        <div className="card hover:shadow-glow">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-accent-purple animate-pulse"></div>
              <span className="text-xs font-semibold text-gray-300 uppercase">LSTM</span>
            </div>
            <div className="text-sm font-bold">
              <span className={signal.lstm_change_pct >= 0 ? 'text-accent-green' : 'text-accent-red'}>
                {signal.lstm_change_pct >= 0 ? '📈' : '📉'} {signal.lstm_change_pct.toFixed(2)}%
              </span>
            </div>
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-3 font-mono">
            <span>Prediction: <span className="text-accent-purple font-semibold">${signal.lstm_prediction.toFixed(2)}</span></span>
          </div>
        </div>

        {/* XGBoost */}
        <div className="card hover:shadow-glow-red">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-accent-orange animate-pulse"></div>
              <span className="text-xs font-semibold text-gray-300 uppercase">XGBoost</span>
            </div>
            <div className={`text-sm font-bold ${MODEL_COLORS[signal.xgb_direction] || 'text-gray-400'}`}>
              {signal.xgb_direction}
            </div>
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-3 font-mono">
            <span>Probability: <span className="text-accent-orange font-semibold">{(signal.xgb_probability * 100).toFixed(1)}%</span></span>
          </div>
        </div>
      </div>

      {/* Signal Timestamp */}
      {lastUpdate && (
        <div className="text-xs text-gray-500 pt-4 mt-4 border-t border-dark-secondary border-opacity-30 font-mono">
          🕐 Updated: {lastUpdate.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      )}
    </div>
  );
}

