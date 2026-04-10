/**
 * src/components/dashboard/TradeHistory.tsx - Trade Journal with advanced filters
 *
 * Features: filter by result, direction, session, grade, pattern;
 * sorting by date/P&L; pagination limit.
 */

import { useState, useMemo, memo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TrendingUp, TrendingDown, Filter, ArrowUpDown, X, Search, ExternalLink } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
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
  grade?: string | null;
  session?: string | null;
}

interface TradesResponse {
  trades: Trade[];
  total: number;
  wins: number;
  losses: number;
}

type ResultFilter = 'ALL' | 'WIN' | 'LOSS' | 'PENDING';
type DirectionFilter = 'ALL' | 'LONG' | 'SHORT';
type SortField = 'date' | 'pnl';
type SortDir = 'asc' | 'desc';

function safeParseDate(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  let iso = raw.trim();
  iso = iso.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/, '$1T$2');
  if (!/[Zz+\-]/.test(iso.slice(-6))) iso += 'Z';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function formatPrice(value: string | number | undefined): string {
  if (!value) return '$0.00';
  if (typeof value === 'string') {
    if (value.startsWith('$')) return value;
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

function parseProfit(val: string | number | undefined): number {
  if (!val) return 0;
  if (typeof val === 'number') return val;
  return parseFloat(val.replace(/[$,]/g, '')) || 0;
}

/** Detect session from timestamp */
function detectSession(ts: string | null | undefined): string {
  const d = safeParseDate(ts);
  if (!d) return 'unknown';
  const h = d.getUTCHours();
  if (h >= 0 && h < 7) return 'asian';
  if (h >= 7 && h < 13) return 'london';
  if (h >= 13 && h < 22) return 'new_york';
  return 'off_hours';
}

const SESSION_LABELS: Record<string, string> = {
  asian: 'Asian', london: 'London', new_york: 'NY', off_hours: 'Off', unknown: '?',
};

const SESSION_COLORS: Record<string, string> = {
  asian: 'bg-accent-orange/12 text-accent-orange border-accent-orange/20',
  london: 'bg-accent-blue/12 text-accent-blue border-accent-blue/20',
  new_york: 'bg-accent-green/12 text-accent-green border-accent-green/20',
  off_hours: 'bg-dark-secondary text-th-dim border-dark-secondary',
  unknown: 'bg-dark-secondary text-th-dim border-dark-secondary',
};

const GRADE_COLORS: Record<string, string> = {
  'A+': 'text-accent-green', 'A': 'text-accent-green',
  'B': 'text-accent-blue', 'C': 'text-accent-orange', 'D': 'text-accent-red',
};

/** Mini SVG chart showing Entry/SL/TP levels */
function TradeMiniChart({ entry, sl, tp, direction, isWin }: {
  entry: number; sl: number; tp: number; direction: string; isWin: boolean | undefined;
}) {
  if (!entry || !sl || !tp || entry === 0) return null;
  const prices = [sl, entry, tp];
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const w = 80;
  const h = 32;
  const pad = 2;

  const yOf = (p: number) => pad + ((max - p) / range) * (h - pad * 2);

  const entryY = yOf(entry);
  const slY = yOf(sl);
  const tpY = yOf(tp);

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="flex-shrink-0">
      {/* TP zone */}
      <rect x={0} y={Math.min(entryY, tpY)} width={w} height={Math.abs(tpY - entryY)}
        fill={isWin ? 'rgba(34,197,94,0.12)' : 'rgba(34,197,94,0.06)'} />
      {/* SL zone */}
      <rect x={0} y={Math.min(entryY, slY)} width={w} height={Math.abs(slY - entryY)}
        fill="rgba(239,68,68,0.08)" />
      {/* Lines */}
      <line x1={0} y1={tpY} x2={w} y2={tpY} stroke="rgb(34,197,94)" strokeWidth={1} strokeDasharray="3,2" />
      <line x1={0} y1={entryY} x2={w} y2={entryY} stroke="rgb(59,130,246)" strokeWidth={1.5} />
      <line x1={0} y1={slY} x2={w} y2={slY} stroke="rgb(239,68,68)" strokeWidth={1} strokeDasharray="3,2" />
      {/* Labels */}
      <text x={2} y={tpY - 2} fill="rgb(34,197,94)" fontSize="7" fontFamily="monospace">TP</text>
      <text x={2} y={entryY - 2} fill="rgb(59,130,246)" fontSize="7" fontFamily="monospace">E</text>
      <text x={2} y={slY + 8} fill="rgb(239,68,68)" fontSize="7" fontFamily="monospace">SL</text>
      {/* Direction arrow */}
      {direction === 'LONG' ? (
        <polygon points={`${w-8},${entryY} ${w-4},${entryY-6} ${w},${entryY}`} fill="rgb(34,197,94)" opacity={0.7} />
      ) : (
        <polygon points={`${w-8},${entryY} ${w-4},${entryY+6} ${w},${entryY}`} fill="rgb(239,68,68)" opacity={0.7} />
      )}
    </svg>
  );
}

export const TradeHistory = memo(function TradeHistory() {
  const navigate = useNavigate();
  const setSelectedInterval = useTradingStore(s => s.setSelectedInterval);
  const [resultFilter, setResultFilter] = useState<ResultFilter>('ALL');
  const [dirFilter, setDirFilter] = useState<DirectionFilter>('ALL');
  const [sessionFilter, setSessionFilter] = useState<string>('ALL');
  const [gradeFilter, setGradeFilter] = useState<string>('ALL');
  const [patternSearch, setPatternSearch] = useState('');
  const [sortField, setSortField] = useState<SortField>('date');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [showFilters, setShowFilters] = useState(false);

  const { data, isLoading } = usePollingQuery<TradesResponse>(
    'trade-history',
    () => analysisAPI.getRecentTrades(100), // fetch more for client-side filtering
    30_000,
  );

  const trades = data?.trades ?? [];
  const stats = useMemo(() => ({
    total: data?.total ?? 0,
    wins: data?.wins ?? 0,
    losses: data?.losses ?? 0,
  }), [data]);

  // Unique values for filter dropdowns
  const uniqueGrades = useMemo(() => {
    const grades = new Set<string>();
    for (const t of trades) {
      if (t.grade) grades.add(t.grade);
    }
    return [...grades].sort();
  }, [trades]);

  const uniquePatterns = useMemo(() => {
    const patterns = new Set<string>();
    for (const t of trades) {
      if (t.pattern) patterns.add(t.pattern);
    }
    return [...patterns].sort();
  }, [trades]);

  const hasActiveFilters = resultFilter !== 'ALL' || dirFilter !== 'ALL' ||
    sessionFilter !== 'ALL' || gradeFilter !== 'ALL' || patternSearch !== '';

  const clearFilters = useCallback(() => {
    setResultFilter('ALL');
    setDirFilter('ALL');
    setSessionFilter('ALL');
    setGradeFilter('ALL');
    setPatternSearch('');
  }, []);

  const toggleSort = useCallback((field: SortField) => {
    if (sortField === field) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortField(field); setSortDir('desc'); }
  }, [sortField]);

  const filteredTrades = useMemo(() => {
    let result = [...trades];

    // Result filter
    if (resultFilter !== 'ALL') {
      result = result.filter(t => {
        if (resultFilter === 'WIN') return t.result?.includes('WIN');
        if (resultFilter === 'LOSS') return t.result?.includes('LOSS');
        return t.result?.includes('PENDING');
      });
    }

    // Direction filter
    if (dirFilter !== 'ALL') {
      result = result.filter(t => t.direction === dirFilter);
    }

    // Session filter
    if (sessionFilter !== 'ALL') {
      result = result.filter(t => {
        const sess = t.session ?? detectSession(t.timestamp);
        return sess === sessionFilter;
      });
    }

    // Grade filter
    if (gradeFilter !== 'ALL') {
      result = result.filter(t => t.grade === gradeFilter);
    }

    // Pattern search
    if (patternSearch) {
      const q = patternSearch.toLowerCase();
      result = result.filter(t => t.pattern?.toLowerCase().includes(q));
    }

    // Sort
    result.sort((a, b) => {
      let cmp = 0;
      if (sortField === 'date') {
        const da = safeParseDate(a.timestamp)?.getTime() ?? 0;
        const db = safeParseDate(b.timestamp)?.getTime() ?? 0;
        cmp = da - db;
      } else {
        cmp = parseProfit(a.profit) - parseProfit(b.profit);
      }
      return sortDir === 'desc' ? -cmp : cmp;
    });

    return result.slice(0, 50);
  }, [trades, resultFilter, dirFilter, sessionFilter, gradeFilter, patternSearch, sortField, sortDir]);

  const winRate = stats.total > 0 ? (stats.wins / stats.total) * 100 : 0;

  if (isLoading && trades.length === 0) {
    return <div className="flex items-center justify-center h-40 text-th-secondary"><span>Loading trades...</span></div>;
  }

  return (
    <div className="space-y-3">
      {/* Stats Summary + Win Rate Bar */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="bg-dark-surface rounded p-2 border border-dark-secondary">
          <div className="text-th-secondary">Total</div>
          <div className="text-lg font-bold text-accent-cyan">{stats.total}</div>
        </div>
        <div className="bg-dark-surface rounded p-2 border border-accent-green/30">
          <div className="text-th-secondary">Wins</div>
          <div className="text-lg font-bold text-accent-green">{stats.wins}</div>
        </div>
        <div className="bg-dark-surface rounded p-2 border border-accent-red/30">
          <div className="text-th-secondary">Losses</div>
          <div className="text-lg font-bold text-accent-red">{stats.losses}</div>
        </div>
      </div>

      {/* Win Rate Progress Bar */}
      {stats.total > 0 && (
        <div className="bg-dark-surface rounded p-2 border border-dark-secondary">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-th-secondary">Win Rate</span>
            <span className={`font-bold ${winRate >= 50 ? 'text-accent-green' : 'text-accent-red'}`}>
              {winRate.toFixed(1)}%
            </span>
          </div>
          <div className="relative h-1.5 bg-accent-red/25 rounded-full overflow-hidden">
            <div
              className={`absolute left-0 top-0 h-full rounded-full transition-all duration-500 ${
                winRate >= 50 ? 'bg-accent-green' : 'bg-accent-orange'
              }`}
              style={{ width: `${Math.min(winRate, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="space-y-2">
        <div className="flex items-center gap-1 flex-wrap">
          {/* Result tabs */}
          <Filter size={10} className="text-th-muted" />
          {(['ALL', 'WIN', 'LOSS', 'PENDING'] as ResultFilter[]).map(tab => (
            <button
              key={tab}
              onClick={() => setResultFilter(tab)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                resultFilter === tab
                  ? tab === 'WIN' ? 'bg-accent-green/30 text-accent-green border border-accent-green/40'
                  : tab === 'LOSS' ? 'bg-accent-red/30 text-accent-red border border-accent-red/40'
                  : 'bg-accent-blue/30 text-accent-blue border border-accent-blue/40'
                  : 'bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary'
              }`}
            >
              {tab}
            </button>
          ))}

          <div className="w-px h-4 bg-dark-secondary mx-1" />

          {/* Direction toggle */}
          {(['ALL', 'LONG', 'SHORT'] as DirectionFilter[]).map(d => (
            <button
              key={d}
              onClick={() => setDirFilter(d)}
              className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                dirFilter === d
                  ? d === 'LONG' ? 'bg-accent-green/20 text-accent-green border border-accent-green/30'
                  : d === 'SHORT' ? 'bg-accent-red/20 text-accent-red border border-accent-red/30'
                  : 'bg-accent-blue/20 text-accent-blue border border-accent-blue/30'
                  : 'bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary'
              }`}
            >
              {d === 'ALL' ? 'Both' : d}
            </button>
          ))}

          <div className="flex-1" />

          {/* Advanced filters toggle */}
          <button
            onClick={() => setShowFilters(v => !v)}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors flex items-center gap-1 ${
              showFilters || hasActiveFilters
                ? 'bg-accent-purple/20 text-accent-purple border border-accent-purple/30'
                : 'bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary'
            }`}
          >
            <Search size={9} />
            Filters
            {hasActiveFilters && (
              <button onClick={(e) => { e.stopPropagation(); clearFilters(); }}
                className="ml-1 hover:text-accent-red"><X size={8} /></button>
            )}
          </button>

          {/* Sort buttons */}
          <button onClick={() => toggleSort('date')}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors flex items-center gap-0.5 ${
              sortField === 'date' ? 'bg-accent-blue/20 text-accent-blue border border-accent-blue/30'
                : 'bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary'
            }`}>
            <ArrowUpDown size={8} />
            Data {sortField === 'date' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
          </button>
          <button onClick={() => toggleSort('pnl')}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors flex items-center gap-0.5 ${
              sortField === 'pnl' ? 'bg-accent-blue/20 text-accent-blue border border-accent-blue/30'
                : 'bg-dark-secondary text-th-muted border border-transparent hover:text-th-secondary'
            }`}>
            <ArrowUpDown size={8} />
            P&L {sortField === 'pnl' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
          </button>
        </div>

        {/* Advanced filter row */}
        {showFilters && (
          <div className="flex items-center gap-2 flex-wrap text-[10px]">
            {/* Session */}
            <div className="flex items-center gap-1">
              <span className="text-th-muted">Session:</span>
              <select value={sessionFilter} onChange={e => setSessionFilter(e.target.value)}
                className="bg-dark-tertiary border border-dark-secondary rounded px-1.5 py-0.5 text-[10px] text-th-secondary outline-none">
                <option value="ALL">All</option>
                <option value="asian">Asian</option>
                <option value="london">London</option>
                <option value="new_york">New York</option>
                <option value="off_hours">Off-Hours</option>
              </select>
            </div>

            {/* Grade */}
            {uniqueGrades.length > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-th-muted">Grade:</span>
                <select value={gradeFilter} onChange={e => setGradeFilter(e.target.value)}
                  className="bg-dark-tertiary border border-dark-secondary rounded px-1.5 py-0.5 text-[10px] text-th-secondary outline-none">
                  <option value="ALL">All</option>
                  {uniqueGrades.map(g => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
            )}

            {/* Pattern search */}
            {uniquePatterns.length > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-th-muted">Pattern:</span>
                <input
                  type="text"
                  value={patternSearch}
                  onChange={e => setPatternSearch(e.target.value)}
                  placeholder="Szukaj..."
                  className="bg-dark-tertiary border border-dark-secondary rounded px-1.5 py-0.5 text-[10px] text-th-secondary outline-none w-24"
                />
              </div>
            )}

            {/* Matched count */}
            <span className="text-th-dim ml-auto">{filteredTrades.length} wynikow</span>
          </div>
        )}
      </div>

      {/* Trades List */}
      <div className="space-y-2 max-h-[480px] overflow-y-auto pr-0.5 scrollbar-thin scrollbar-thumb-dark-secondary">
        {filteredTrades.length === 0 ? (
          <div className="text-center text-th-secondary text-xs py-4">
            {hasActiveFilters ? 'Brak transakcji pasujacych do filtrow' : 'Brak transakcji'}
          </div>
        ) : (
          filteredTrades.map((trade) => {
            const isWin = trade.result?.includes('WIN');
            const isLoss = trade.result?.includes('LOSS');
            const entry = parseNumericPrice(trade.entry);
            const sl = parseNumericPrice(trade.sl);
            const tp = parseNumericPrice(trade.tp);
            const risk = Math.abs(entry - sl);
            const reward = Math.abs(tp - entry);
            const rr = risk > 0 ? (reward / risk) : 0;
            const session = trade.session ?? detectSession(trade.timestamp);
            const sessStyle = SESSION_COLORS[session] ?? SESSION_COLORS.unknown;

            return (
              <div
                key={trade.id}
                className={`border rounded p-2 text-xs ${
                  isWin ? 'bg-accent-green/5 border-accent-green/30'
                  : isLoss ? 'bg-accent-red/5 border-accent-red/30'
                  : 'bg-accent-blue/5 border-accent-blue/30'
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
                        <span className="font-bold">{trade.direction}</span>
                        {trade.timeframe && (
                          <span className="px-1 py-0.5 rounded text-[9px] font-mono font-bold bg-accent-blue/15 text-accent-blue border border-accent-blue/20">
                            {trade.timeframe}
                          </span>
                        )}
                        {trade.grade && (
                          <span className={`text-[9px] font-bold ${GRADE_COLORS[trade.grade] ?? 'text-th-muted'}`}>
                            {trade.grade}
                          </span>
                        )}
                        <span className={`px-1 py-0.5 rounded text-[8px] font-medium border ${sessStyle}`}>
                          {SESSION_LABELS[session] ?? session}
                        </span>
                      </div>
                      <div className="text-th-muted">Entry: {formatPrice(trade.entry)}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`font-bold ${isWin ? 'text-accent-green' : isLoss ? 'text-accent-red' : 'text-accent-blue'}`}>
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
                <div className="grid grid-cols-3 gap-1 text-xs text-th-muted mt-1 pt-1 border-t border-current border-opacity-20">
                  <div>SL: {formatPrice(trade.sl)}</div>
                  <div>TP: {formatPrice(trade.tp)}</div>
                  {rr > 0 && (
                    <div className={`text-right font-mono ${rr >= 2 ? 'text-accent-green' : rr >= 1 ? 'text-accent-orange' : 'text-accent-red'}`}>
                      R:R {rr.toFixed(1)}
                    </div>
                  )}
                </div>

                {/* Mini chart + Pattern + Timestamp + Nav button */}
                <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-current border-opacity-10">
                  <TradeMiniChart entry={entry} sl={sl} tp={tp} direction={trade.direction} isWin={isWin} />
                  <div className="flex-1 min-w-0 text-xs text-th-dim">
                    {trade.pattern && <div className="truncate">{trade.pattern}</div>}
                    <div>
                      {(() => {
                        const d = safeParseDate(trade.timestamp);
                        return d ? d.toLocaleString('pl-PL', {
                          year: 'numeric', month: '2-digit', day: '2-digit',
                          hour: '2-digit', minute: '2-digit',
                        }) : '—';
                      })()}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      if (trade.timeframe) setSelectedInterval(trade.timeframe);
                      navigate('/');
                    }}
                    className="flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[9px] text-accent-blue hover:bg-accent-blue/10 transition-colors flex-shrink-0"
                    title="Otworz wykres w tym momencie"
                  >
                    <ExternalLink size={8} />
                    Chart
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
});
