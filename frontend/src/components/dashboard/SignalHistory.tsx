/**
 * src/components/dashboard/SignalHistory.tsx - Historical trading signals (rich SMC view)
 */

import { useEffect, useState } from 'react';
import { signalsAPI } from '../../api/client';
import { History, TrendingUp, TrendingDown } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

interface ScannerSignal {
  signal_id?: string;
  timestamp: string;
  direction?: string;
  entry_price?: number;
  sl?: number;
  tp?: number;
  rsi?: number;
  structure?: string;
  result?: string;
}

const fmt = (v: number | undefined | null, d = 2) => (v != null ? v.toFixed(d) : '—');

export function SignalHistory() {
  const [signals, setSignals] = useState<ScannerSignal[]>([]);
  const [stats, setStats] = useState({ total: 0, wins: 0, losses: 0, win_rate: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [scannerData, statsData] = await Promise.all([
          signalsAPI.getScannerHistory(25),
          signalsAPI.getStats(),
        ]);
        setSignals(scannerData);
        setStats(statsData);
      } catch (err) {
        console.error('Error fetching scanner history:', err);
        setError('Failed to load history');
      } finally {
        setLoading(false);
      }
    };

    void fetchData();
    const interval = setInterval(fetchData, 90000);
    return () => clearInterval(interval);
  }, []);

  if (loading && signals.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading history...</span>
      </div>
    );
  }

  if (error && signals.length === 0) {
    return <div className="text-center text-red-400 text-xs">{error}</div>;
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-400 font-bold flex items-center gap-2">
          <History size={14} />
          SIGNAL HISTORY
        </div>
        {stats.total > 0 && (
          <div className="text-xs text-gray-500">
            WR:{' '}
            <span className={stats.win_rate >= 0.5 ? 'text-accent-green font-bold' : 'text-accent-red font-bold'}>
              {(stats.win_rate * 100).toFixed(0)}%
            </span>
            &nbsp;({stats.wins}W/{stats.losses}L)
          </div>
        )}
      </div>

      {/* Signals List */}
      <div className="space-y-2 max-h-[480px] overflow-y-auto pr-0.5">
        {signals.length === 0 ? (
          <div className="text-center text-gray-400 text-xs py-4">
            No signals yet — scanner runs every 15 min
          </div>
        ) : (
          signals.map((sig, index) => {
            const isLong = sig.direction === 'LONG';
            const isWin = sig.result === 'WIN';
            const isLoss = sig.result === 'LOSS';
            const ts = new Date(sig.timestamp);
            const timeAgo = formatDistanceToNow(ts, { addSuffix: true });

            const rsiColor =
              (sig.rsi ?? 50) > 70
                ? 'text-accent-red'
                : (sig.rsi ?? 50) < 30
                ? 'text-accent-green'
                : 'text-accent-blue';

            const cardColor = isWin
              ? 'bg-green-900/10 border-green-500/30'
              : isLoss
              ? 'bg-red-900/10 border-red-500/30'
              : isLong
              ? 'bg-green-900/5 border-green-500/20'
              : 'bg-red-900/5 border-red-500/20';

            return (
              <div
                key={`${sig.signal_id ?? index}-${sig.timestamp}`}
                className={`border rounded p-2.5 text-xs ${cardColor}`}
              >
                {/* Top row: direction + price + time */}
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    {isLong ? (
                      <TrendingUp size={13} className="text-accent-green" />
                    ) : (
                      <TrendingDown size={13} className="text-accent-red" />
                    )}
                    <span className={`font-bold ${isLong ? 'text-accent-green' : 'text-accent-red'}`}>
                      {sig.direction ?? '?'}
                    </span>
                    {sig.structure && (
                      <span className="text-gray-500 text-xs">· {sig.structure}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {sig.result && (
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                          isWin
                            ? 'bg-green-900/30 text-accent-green'
                            : isLoss
                            ? 'bg-red-900/30 text-accent-red'
                            : 'bg-blue-900/30 text-blue-400'
                        }`}
                      >
                        {sig.result}
                      </span>
                    )}
                    <span className="text-gray-600">{timeAgo}</span>
                  </div>
                </div>

                {/* Entry / SL / TP grid */}
                <div className="grid grid-cols-3 gap-1 text-xs">
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-gray-500 text-xs leading-none mb-0.5">Entry</div>
                    <div className="font-mono font-semibold text-accent-blue">
                      ${fmt(sig.entry_price)}
                    </div>
                  </div>
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-gray-500 text-xs leading-none mb-0.5">SL</div>
                    <div className="font-mono font-semibold text-accent-red">
                      ${fmt(sig.sl)}
                    </div>
                  </div>
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-gray-500 text-xs leading-none mb-0.5">TP</div>
                    <div className="font-mono font-semibold text-accent-green">
                      ${fmt(sig.tp)}
                    </div>
                  </div>
                </div>

                {/* RSI badge */}
                {sig.rsi != null && (
                  <div className="mt-1.5 flex items-center gap-1 text-xs">
                    <span className="text-gray-500">RSI:</span>
                    <span className={`font-bold ${rsiColor}`}>{fmt(sig.rsi, 1)}</span>
                    {(sig.rsi ?? 50) > 70 && (
                      <span className="text-accent-red">Overbought</span>
                    )}
                    {(sig.rsi ?? 50) < 30 && (
                      <span className="text-accent-green">Oversold</span>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer stats */}
      {signals.length > 0 && (
        <div className="text-xs text-gray-500 pt-2 border-t border-dark-secondary flex justify-between">
          <span>{signals.length} signals shown</span>
          <span>
            {signals.filter((s) => s.direction === 'LONG').length}L /{' '}
            {signals.filter((s) => s.direction === 'SHORT').length}S
          </span>
        </div>
      )}
    </div>
  );
}
