/**
 * src/components/dashboard/SignalHistory.tsx - Historical trading signals
 */

import { useEffect, useState } from 'react';
import { signalsAPI } from '../../api/client';
import type { Signal } from '../../types/trading';
import { History } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: 'bg-green-900/30 border-green-500/50 text-green-400',
  BUY: 'bg-green-900/20 border-green-500/30 text-green-300',
  HOLD: 'bg-blue-900/20 border-blue-500/30 text-blue-300',
  SELL: 'bg-red-900/20 border-red-500/30 text-red-300',
  STRONG_SELL: 'bg-red-900/30 border-red-500/50 text-red-400',
};

export function SignalHistory() {
  const [history, setHistory] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await signalsAPI.getHistory(20);
        setHistory(data);
      } catch (err) {
        console.error('Error fetching signal history:', err);
        setError('Failed to load history');
      } finally {
        setLoading(false);
      }
    };

    fetchHistory();

    // Refresh every 10 seconds
    const interval = setInterval(fetchHistory, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading && history.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading history...</span>
      </div>
    );
  }

  if (error && history.length === 0) {
    return (
      <div className="text-center text-red-400 text-xs">{error}</div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="text-xs text-gray-400 font-bold flex items-center gap-2">
        <History size={14} />
        SIGNAL HISTORY
      </div>

      {/* Signals List */}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {history.length === 0 ? (
          <div className="text-center text-gray-400 text-xs py-4">No signals yet</div>
        ) : (
          history.map((signal, index) => {
            const colors = SIGNAL_COLORS[signal.consensus] || SIGNAL_COLORS.HOLD;
            const timestamp = new Date(signal.timestamp);
            const timeAgo = formatDistanceToNow(timestamp, { addSuffix: true });

            return (
              <div
                key={`${signal.timestamp}-${index}`}
                className={`border rounded p-2.5 text-xs transition-all hover:scale-105 ${colors}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">
                      {signal.consensus === 'STRONG_BUY' ? '🚀' :
                       signal.consensus === 'BUY' ? '📈' :
                       signal.consensus === 'HOLD' ? '⏸️' :
                       signal.consensus === 'SELL' ? '📉' :
                       '💥'}
                    </span>
                    <div>
                      <span className="font-bold">{signal.consensus}</span>
                                     <div className="text-gray-500 text-xs">{timeAgo}</div>
                                   </div>
                                 </div>
                                 <div className="text-right">
                                   <div className="font-semibold">${((signal.current_price ?? 0) as number).toFixed(2)}</div>
                                   <div className="text-xs text-gray-400">Score: {((signal.consensus_score ?? 0) as number).toFixed(2)}</div>
                  </div>
                </div>

                {/* Mini Stats */}
                <div className="grid grid-cols-3 gap-1 text-xs mt-2 pt-2 border-t border-current border-opacity-20">
                  <div className="text-center">
                    <div className="text-gray-500">RL</div>
                    <div className={`font-semibold ${
                      signal.rl_action === 'BUY' ? 'text-green-400' :
                      signal.rl_action === 'SELL' ? 'text-red-400' :
                      'text-blue-400'
                    }`}>
                      {signal.rl_action}
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-gray-500">LSTM</div>
                    <div className={(signal.lstm_change_pct ?? 0) >= 0 ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold'}>
                      {(signal.lstm_change_pct ?? 0) >= 0 ? '↑' : '↓'} {Math.abs(signal.lstm_change_pct ?? 0).toFixed(2)}%
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-gray-500">XGB</div>
                    <div className={`font-semibold ${
                      signal.xgb_direction === 'UP' ? 'text-green-400' :
                      signal.xgb_direction === 'DOWN' ? 'text-red-400' :
                      'text-blue-400'
                    }`}>
                      {signal.xgb_direction}
                    </div>
                  </div>
                </div>

                {/* RSI if available */}
                {signal.current_rsi !== undefined && (
                  <div className="mt-1 pt-1 border-t border-current border-opacity-20 text-xs">
                    <span className="text-gray-500">RSI: </span>
                     <span className={
                       (signal.current_rsi ?? 0) > 70 ? 'text-red-400 font-semibold' :
                       (signal.current_rsi ?? 0) < 30 ? 'text-green-400 font-semibold' :
                       'text-blue-400'
                     }>
                       {((signal.current_rsi ?? 0) as number).toFixed(1)}
                    </span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer Stats */}
      {history.length > 0 && (
        <div className="text-xs text-gray-500 pt-2 border-t border-dark-secondary space-y-1">
          <div className="flex justify-between">
            <span>Total signals: {history.length}</span>
            <span>
              Buy signals: {history.filter(s => s.consensus.includes('BUY')).length}
              {' / '}
              Sell signals: {history.filter(s => s.consensus.includes('SELL')).length}
            </span>
          </div>
          <div className="flex justify-between">
            <span>Avg Price: ${(history.reduce((sum, s) => sum + (s.current_price ?? 0), 0) / history.length).toFixed(2)}</span>
            <span>Avg Score: {(history.reduce((sum, s) => sum + (s.consensus_score ?? 0), 0) / history.length).toFixed(2)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

