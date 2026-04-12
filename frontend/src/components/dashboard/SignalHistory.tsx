/**
 * src/components/dashboard/SignalHistory.tsx - Historical trading signals (rich SMC view)
 */

import { useEffect, useState, memo } from 'react';
import { signalsAPI } from '../../api/client';
import { useTradingStore } from '../../store/tradingStore';
import { History, TrendingUp, TrendingDown } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { useToast } from '../ui/Toast';

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

const fmt = (v: number | undefined | null, d = 2) => (v !== null && v !== undefined ? v.toFixed(d) : '—');

export const SignalHistory = memo(function SignalHistory() {
  const toast = useToast();
  const [signals, setSignals] = useState<ScannerSignal[]>([]);
  const [stats, setStats] = useState({ total: 0, wins: 0, losses: 0, win_rate: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const apiConnected = useTradingStore((s) => s.apiConnected);

  useEffect(() => {
    if (!apiConnected) {return;}
    const fetchData = async () => {
      try {
        setError(null);
        const [scannerData, statsData] = await Promise.all([
          signalsAPI.getScannerHistory(25),
          signalsAPI.getStats(),
        ]);
        setSignals(scannerData);
        setStats(statsData);
      } catch {
        toast.error('Failed to load signal history');
        setError('Failed to load history');
      } finally {
        setLoading(false);
      }
    };

    const initTimer = setTimeout(() => void fetchData(), 2000);
    const interval = setInterval(fetchData, 45000);
    return () => { clearTimeout(initTimer); clearInterval(interval); };
  }, [apiConnected]);

  if (loading && signals.length === 0) {
    return (
      <div className="space-y-2">
        {[1,2,3,4,5].map(i => (
          <div key={i} className="flex items-center gap-3">
            <div className="skeleton-shimmer w-6 h-6 rounded-full" />
            <div className="flex-1 space-y-1">
              <div className="skeleton-shimmer h-3 rounded-full" style={{ width: `${70 + (i % 3) * 10}%` }} />
              <div className="skeleton-shimmer h-2 w-1/2 rounded-full" />
            </div>
            <div className="skeleton-shimmer h-5 w-12 rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (error && signals.length === 0) {
    return <div className="text-center text-accent-red text-xs">{error}</div>;
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-th-secondary font-bold flex items-center gap-2">
          <History size={14} />
          SIGNAL HISTORY
        </div>
        {stats.total > 0 && (
          <div className="text-xs text-th-muted">
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
          <div className="text-center text-th-secondary text-xs py-4">
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
              ? 'bg-accent-green/5 border-accent-green/30'
              : isLoss
              ? 'bg-accent-red/5 border-accent-red/30'
              : isLong
              ? 'bg-accent-green/3 border-accent-green/20'
              : 'bg-accent-red/3 border-accent-red/20';

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
                      <span className="text-th-muted text-xs">{sig.structure}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {sig.result && (
                      <span
                        className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                          isWin
                            ? 'bg-accent-green/15 text-accent-green'
                            : isLoss
                            ? 'bg-accent-red/15 text-accent-red'
                            : 'bg-accent-blue/15 text-accent-blue'
                        }`}
                      >
                        {sig.result}
                      </span>
                    )}
                    <span className="text-th-dim">{timeAgo}</span>
                  </div>
                </div>

                {/* Entry / SL / TP grid */}
                <div className="grid grid-cols-3 gap-1 text-xs">
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-th-muted text-xs leading-none mb-0.5">Entry</div>
                    <div className="font-mono font-semibold text-accent-blue">
                      ${fmt(sig.entry_price)}
                    </div>
                  </div>
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-th-muted text-xs leading-none mb-0.5">SL</div>
                    <div className="font-mono font-semibold text-accent-red">
                      ${fmt(sig.sl)}
                    </div>
                  </div>
                  <div className="bg-dark-bg/50 rounded px-1.5 py-1 text-center">
                    <div className="text-th-muted text-xs leading-none mb-0.5">TP</div>
                    <div className="font-mono font-semibold text-accent-green">
                      ${fmt(sig.tp)}
                    </div>
                  </div>
                </div>

                {/* RSI badge */}
                {sig.rsi !== null && (
                  <div className="mt-1.5 flex items-center gap-1 text-xs">
                    <span className="text-th-muted">RSI:</span>
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
        <div className="text-xs text-th-muted pt-2 border-t border-dark-secondary flex justify-between">
          <span>{signals.length} signals shown</span>
          <span>
            {signals.filter((s) => s.direction === 'LONG').length}L /{' '}
            {signals.filter((s) => s.direction === 'SHORT').length}S
          </span>
        </div>
      )}
    </div>
  );
});
