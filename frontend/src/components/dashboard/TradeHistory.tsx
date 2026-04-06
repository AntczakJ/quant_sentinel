/**
 * src/components/dashboard/TradeHistory.tsx - Recent trades history
 * Enhanced with filter tabs, win rate visual, and R:R display.
 */

import { useState, useMemo, memo } from 'react';
import { TrendingUp, TrendingDown, Filter } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';

interface Trade {
  id: number;
  direction: string;
  entry: string | number;
  sl: string | number;
  tp: string | number;
  status: string;
  profit?: string | number;
  timestamp: string;
  result: string;
  timeframe?: string | null;
  pattern?: string | null;
}

interface TradesResponse {
  trades: Trade[];
  total: number;
  wins: number;
  losses: number;
}

type FilterTab = 'ALL' | 'WIN' | 'LOSS' | 'PENDING';

// Helper to safely parse timestamps from SQLite (e.g. "2025-04-05 12:30:00")
function safeParseDate(raw: string | null | undefined): Date | null {
  if (!raw) {return null;}
  let iso = raw.trim();
  iso = iso.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/, '$1T$2');
  if (!/[Zz+\-]/.test(iso.slice(-6))) {iso += 'Z';}
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

// Helper to format price
function formatPrice(value: string | number | undefined): string {
  if (!value) { return '$0.00'; }
  if (typeof value === 'string') {
    if (value.startsWith('$')) { return value; }
    const num = parseFloat(value);
    return !isNaN(num) ? `$${num.toFixed(2)}` : value;
  }
  return `$${value.toFixed(2)}`;
}

function parseNumericPrice(val: string | number | undefined): number {
  if (!val) return 0;
  if (typeof val === 'number') return val;
  return parseFloat(val.replace('$', '')) || 0;
}

export const TradeHistory = memo(function TradeHistory() {
  const [filter, setFilter] = useState<FilterTab>('ALL');

  const { data, isLoading } = usePollingQuery<TradesResponse>(
    'trade-history',
    () => analysisAPI.getRecentTrades(30),
    60_000,
  );

  const trades = data?.trades ?? [];
  const stats = useMemo(() => ({
    total: data?.total ?? 0,
    wins: data?.wins ?? 0,
    losses: data?.losses ?? 0,
  }), [data]);

  const filteredTrades = useMemo(() => {
    if (filter === 'ALL') return trades.slice(0, 15);
    return trades.filter(t => {
      if (filter === 'WIN') return t.result?.includes('WIN');
      if (filter === 'LOSS') return t.result?.includes('LOSS');
      return t.result?.includes('PENDING');
    }).slice(0, 15);
  }, [trades, filter]);

  const winRate = stats.total > 0 ? (stats.wins / stats.total) * 100 : 0;

  if (isLoading && trades.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading trades...</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Stats Summary + Win Rate Bar */}
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

      {/* Win Rate Progress Bar */}
      {stats.total > 0 && (
        <div className="bg-dark-surface rounded p-2 border border-dark-secondary">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-gray-400">Win Rate</span>
            <span className={`font-bold ${winRate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
              {winRate.toFixed(1)}%
            </span>
          </div>
          <div className="relative h-1.5 bg-red-900/40 rounded-full overflow-hidden">
            <div
              className={`absolute left-0 top-0 h-full rounded-full transition-all duration-500 ${
                winRate >= 50 ? 'bg-green-500' : 'bg-amber-500'
              }`}
              style={{ width: `${Math.min(winRate, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex items-center gap-1">
        <Filter size={10} className="text-gray-500" />
        {(['ALL', 'WIN', 'LOSS', 'PENDING'] as FilterTab[]).map(tab => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
              filter === tab
                ? tab === 'WIN' ? 'bg-green-600/30 text-green-400 border border-green-600/40'
                : tab === 'LOSS' ? 'bg-red-600/30 text-red-400 border border-red-600/40'
                : 'bg-blue-600/30 text-blue-400 border border-blue-600/40'
                : 'bg-dark-secondary text-gray-500 border border-transparent hover:text-gray-400'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Trades List */}
      <div className="space-y-2 max-h-[480px] overflow-y-auto pr-0.5 scrollbar-thin scrollbar-thumb-dark-secondary">
        {filteredTrades.length === 0 ? (
          <div className="text-center text-gray-400 text-xs py-4">
            {filter === 'ALL' ? 'Brak transakcji' : `Brak transakcji: ${filter}`}
          </div>
        ) : (
          filteredTrades.map((trade) => {
            const isWin = trade.result?.includes('WIN');
            const isLoss = trade.result?.includes('LOSS');

            // Calculate R:R ratio
            const entry = parseNumericPrice(trade.entry);
            const sl = parseNumericPrice(trade.sl);
            const tp = parseNumericPrice(trade.tp);
            const risk = Math.abs(entry - sl);
            const reward = Math.abs(tp - entry);
            const rr = risk > 0 ? (reward / risk) : 0;

            return (
              <div
                key={trade.id}
                className={`border rounded p-2 text-xs ${
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
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold">
                          {trade.direction === 'LONG' ? '📈 LONG' : '📉 SHORT'}
                        </span>
                        {trade.timeframe && (
                          <span className="px-1 py-0.5 rounded text-[9px] font-mono font-bold bg-blue-900/30 text-blue-400 border border-blue-600/20">
                            {trade.timeframe}
                          </span>
                        )}
                      </div>
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
                    {trade.profit != null && (
                      <div className={isWin ? 'text-accent-green' : 'text-accent-red'}>
                        {formatPrice(trade.profit)}
                      </div>
                    )}
                  </div>
                </div>

                {/* Trade Details */}
                <div className="grid grid-cols-3 gap-1 text-xs text-gray-500 mt-1 pt-1 border-t border-current border-opacity-20">
                  <div>SL: {formatPrice(trade.sl)}</div>
                  <div>TP: {formatPrice(trade.tp)}</div>
                  {rr > 0 && (
                    <div className={`text-right font-mono ${rr >= 2 ? 'text-green-400' : rr >= 1 ? 'text-amber-400' : 'text-red-400'}`}>
                      R:R {rr.toFixed(1)}
                    </div>
                  )}
                </div>

                {/* Timestamp */}
                <div className="text-xs text-gray-600 mt-1">
                  {(() => {
                    const d = safeParseDate(trade.timestamp);
                    return d
                      ? d.toLocaleString('pl-PL', {
                          year: 'numeric', month: '2-digit', day: '2-digit',
                          hour: '2-digit', minute: '2-digit', second: '2-digit',
                        })
                      : '—';
                  })()}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});
