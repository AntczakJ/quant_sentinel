/**
 * src/components/dashboard/TradeHistory.tsx - Recent trades history
 */

import { useEffect, useState } from 'react';
import { analysisAPI } from '../../api/client';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface Trade {
  id: number;
  direction: string;
  entry: string | number;  // ← Can be "$2050.50" or 2050.50
  sl: string | number;     // ← Can be "$2048.50" or 2048.50
  tp: string | number;     // ← Can be "$2055.00" or 2055.00
  status: string;
  profit?: string | number;
  timestamp: string;
  result: string;
}

// Helper to format price
function formatPrice(value: string | number | undefined): string {
  if (!value) return '$0.00';
  if (typeof value === 'string') {
    // Already formatted like "$2050.50"
    if (value.startsWith('$')) return value;
    // Try to parse as number
    const num = parseFloat(value);
    return !isNaN(num) ? `$${num.toFixed(2)}` : value;
  }
  // It's a number
  return `$${value.toFixed(2)}`;
}

export function TradeHistory() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ total: 0, wins: 0, losses: 0 });

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await analysisAPI.getRecentTrades(15);
        setTrades(data.trades || []);
        setStats({
          total: data.total || 0,
          wins: data.wins || 0,
          losses: data.losses || 0,
        });
      } catch (err) {
        console.error('Error fetching trades:', err);
        setError('Failed to load trades');
      } finally {
        setLoading(false);
      }
    };

    fetchTrades();

    // Refresh every 10 seconds
    const interval = setInterval(fetchTrades, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading && trades.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading trades...</span>
      </div>
    );
  }

  if (error && trades.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 bg-red-900/10 border border-red-500/30 rounded-lg">
        <span className="text-red-400 text-xs">{error}</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Stats Summary */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-dark-surface rounded p-2 border border-dark-secondary">
          <div className="text-gray-400">Total</div>
          <div className="text-lg font-bold text-accent-cyan">{stats.total}</div>
        </div>
        <div className="bg-dark-surface rounded p-2 border border-accent-green/30">
          <div className="text-gray-400">Wins</div>
          <div className="text-lg font-bold text-accent-green">{stats.wins}</div>
        </div>
        <div className="bg-dark-surface rounded p-2 border border-accent-red/30">
          <div className="text-gray-400">Losses</div>
          <div className="text-lg font-bold text-accent-red">{stats.losses}</div>
        </div>
      </div>

      {/* Trades List */}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {trades.length === 0 ? (
          <div className="text-center text-gray-400 text-xs py-4">No trades yet</div>
        ) : (
          trades.map((trade) => {
            const isWin = trade.result.includes('WIN');
            const isLoss = trade.result.includes('LOSS');

            return (
              <div
                key={trade.id}
                className={`border rounded p-2 text-xs transition-all hover:scale-105 ${
                  isWin
                    ? 'bg-green-900/10 border-green-500/30'
                    : isLoss
                    ? 'bg-red-900/10 border-red-500/30'
                    : 'bg-blue-900/10 border-blue-500/30'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span>
                      {trade.direction === 'LONG' ? (
                        <TrendingUp size={14} className="text-accent-green" />
                      ) : (
                        <TrendingDown size={14} className="text-accent-red" />
                      )}
                    </span>
                    <div>
                      <span className="font-bold">
                        {trade.direction === 'LONG' ? '📈 LONG' : '📉 SHORT'}
                      </span>
                      <div className="text-gray-500">
                        Entry: {formatPrice(trade.entry)}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <span
                      className={`font-bold ${
                        isWin
                          ? 'text-accent-green'
                          : isLoss
                          ? 'text-accent-red'
                          : 'text-accent-blue'
                      }`}
                    >
                      {trade.result}
                    </span>
                    {trade.profit && trade.profit !== null && (
                      <div className={isWin ? 'text-accent-green' : 'text-accent-red'}>
                        {formatPrice(trade.profit)}
                      </div>
                    )}
                  </div>
                </div>

                {/* Trade Details */}
                <div className="grid grid-cols-2 gap-1 text-xs text-gray-500 mt-1 pt-1 border-t border-current border-opacity-20">
                  <div>SL: {formatPrice(trade.sl)}</div>
                  <div>TP: {formatPrice(trade.tp)}</div>
                </div>

                {/* Timestamp */}
                <div className="text-xs text-gray-600 mt-1">
                  {new Date(trade.timestamp).toLocaleString('pl-PL', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Win Rate */}
      {stats.total > 0 && (
        <div className="text-xs text-gray-400 pt-2 border-t border-dark-secondary">
          <div className="flex justify-between items-center">
            <span>Win Rate:</span>
            <span className="text-accent-green font-bold">
              {((stats.wins / stats.total) * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}
    </div>
  );
}


