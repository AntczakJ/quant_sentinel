/**
 * src/components/dashboard/BacktestResults.tsx — Backtest run viewer.
 *
 * Reads /api/backtest/runs — shows last N backtest results as a sortable
 * table with key quant metrics. Read-only, zero production-state mutation.
 */
import { useState, useEffect, memo, useMemo } from 'react';
import {
  Loader2, TrendingUp, TrendingDown, Clock, Activity,
  CheckCircle, XCircle, BarChart3, Target,
} from 'lucide-react';
import { backtestResultsAPI } from '../../api/client';

type Run = {
  path: string;
  name: string;
  mtime: number;
  trades: number;
  wins: number;
  losses: number;
  breakevens: number;
  win_rate_pct: number;
  profit_factor: number | string;
  return_pct: number;
  max_drawdown_pct: number;
  max_consec_losses: number;
  cycles_total: number;
  alpha_vs_bh_pct: number | null;
  sharpe: number | null;
  sortino: number | null;
  expectancy: number | null;
};

function formatAgo(unixTs: number): string {
  const diff = (Date.now() / 1000) - unixTs;
  if (diff < 60) {return `${Math.round(diff)}s ago`;}
  if (diff < 3600) {return `${Math.round(diff / 60)}m ago`;}
  if (diff < 86400) {return `${Math.round(diff / 3600)}h ago`;}
  return `${Math.round(diff / 86400)}d ago`;
}

function colorForReturn(pct: number): string {
  if (pct > 2) {return 'text-accent-green';}
  if (pct > 0) {return 'text-accent-cyan';}
  if (pct < -2) {return 'text-accent-red';}
  return 'text-accent-orange';
}

export const BacktestResults = memo(function BacktestResults() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      try {
        const data = await backtestResultsAPI.listRuns(10);
        if (!cancelled) {
          setRuns(data.runs);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'load failed');
        }
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void fetch();
    const id = setInterval(fetch, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const selectedRun = useMemo(
    () => runs?.find(r => r.path === selected) ?? runs?.[0],
    [runs, selected],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-th-muted text-sm">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading backtest runs...
      </div>
    );
  }

  if (error) {
    return <div className="text-xs text-accent-red p-2">Error: {error}</div>;
  }

  if (!runs || runs.length === 0) {
    return (
      <div className="text-xs text-th-muted p-4 text-center">
        <p>No backtest runs yet.</p>
        <p className="mt-1">
          Run <code className="bg-dark-bg px-1 rounded">python run_production_backtest.py --reset --days 14 --output reports/bt.json</code> to create the first entry.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Latest run summary card */}
      {selectedRun && (
        <div className="bg-dark-bg border border-dark-secondary rounded-lg p-3">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <BarChart3 size={14} className="text-accent-purple" />
              <span className="font-medium text-sm">{selectedRun.name}</span>
              <span className="text-[10px] text-th-muted flex items-center gap-0.5">
                <Clock size={9} /> {formatAgo(selectedRun.mtime)}
              </span>
            </div>
            <div className="text-[10px] text-th-muted">{selectedRun.cycles_total} cycles</div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <div>
              <div className="text-th-muted text-[10px] uppercase tracking-wider">Trades</div>
              <div className="font-mono font-medium">{selectedRun.trades}</div>
              <div className="text-[10px] text-th-muted">
                {selectedRun.wins}W · {selectedRun.losses}L
                {selectedRun.breakevens > 0 && ` · ${selectedRun.breakevens}BE`}
              </div>
            </div>
            <div>
              <div className="text-th-muted text-[10px] uppercase tracking-wider">Win Rate</div>
              <div className="font-mono font-medium">{selectedRun.win_rate_pct.toFixed(1)}%</div>
              <div className="text-[10px] text-th-muted">
                max loss streak: {selectedRun.max_consec_losses}
              </div>
            </div>
            <div>
              <div className="text-th-muted text-[10px] uppercase tracking-wider">Profit Factor</div>
              <div className="font-mono font-medium">
                {typeof selectedRun.profit_factor === 'number'
                  ? selectedRun.profit_factor.toFixed(2)
                  : selectedRun.profit_factor}
              </div>
              {selectedRun.expectancy !== null && (
                <div className="text-[10px] text-th-muted">
                  E: ${selectedRun.expectancy.toFixed(2)}/trade
                </div>
              )}
            </div>
            <div>
              <div className="text-th-muted text-[10px] uppercase tracking-wider">Return</div>
              <div className={`font-mono font-medium flex items-center gap-0.5 ${colorForReturn(selectedRun.return_pct)}`}>
                {selectedRun.return_pct > 0 ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                {selectedRun.return_pct > 0 ? '+' : ''}{selectedRun.return_pct.toFixed(2)}%
              </div>
              <div className="text-[10px] text-th-muted">
                MaxDD: {selectedRun.max_drawdown_pct.toFixed(2)}%
              </div>
            </div>
          </div>

          {/* Sharpe/Sortino row if available */}
          {(selectedRun.sharpe !== null || selectedRun.sortino !== null || selectedRun.alpha_vs_bh_pct !== null) && (
            <div className="grid grid-cols-3 gap-2 mt-2 pt-2 border-t border-dark-secondary text-xs">
              {selectedRun.sharpe !== null && (
                <div>
                  <div className="text-th-muted text-[10px] flex items-center gap-1">
                    <Target size={9} /> Sharpe
                  </div>
                  <div className={`font-mono ${selectedRun.sharpe > 1 ? 'text-accent-green' : 'text-th-secondary'}`}>
                    {selectedRun.sharpe.toFixed(2)}
                  </div>
                </div>
              )}
              {selectedRun.sortino !== null && (
                <div>
                  <div className="text-th-muted text-[10px]">Sortino</div>
                  <div className={`font-mono ${selectedRun.sortino > 1 ? 'text-accent-green' : 'text-th-secondary'}`}>
                    {selectedRun.sortino.toFixed(2)}
                  </div>
                </div>
              )}
              {selectedRun.alpha_vs_bh_pct !== null && (
                <div>
                  <div className="text-th-muted text-[10px] flex items-center gap-1">
                    <Activity size={9} /> Alpha vs B&H
                  </div>
                  <div className={`font-mono ${selectedRun.alpha_vs_bh_pct > 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                    {selectedRun.alpha_vs_bh_pct > 0 ? '+' : ''}{selectedRun.alpha_vs_bh_pct.toFixed(2)}pp
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Run list (click to select) */}
      <div className="space-y-1">
        <div className="text-[10px] text-th-muted uppercase tracking-wider px-1">
          Recent runs ({runs.length})
        </div>
        {runs.map(r => (
          <button
            key={r.path}
            onClick={() => setSelected(r.path)}
            className={`w-full text-left text-xs px-2 py-1.5 rounded transition-colors flex items-center justify-between ${
              (selected ?? runs[0].path) === r.path
                ? 'bg-accent-purple/15 border border-accent-purple/30'
                : 'hover:bg-dark-bg border border-transparent'
            }`}
          >
            <span className="flex items-center gap-2 min-w-0">
              {r.return_pct > 0 ? (
                <CheckCircle size={11} className="text-accent-green shrink-0" />
              ) : (
                <XCircle size={11} className="text-accent-red shrink-0" />
              )}
              <span className="truncate">{r.name}</span>
            </span>
            <span className="flex items-center gap-3 text-th-muted shrink-0 ml-2">
              <span>{r.trades}tr</span>
              <span>{r.win_rate_pct.toFixed(0)}%</span>
              <span className={`font-mono ${colorForReturn(r.return_pct)}`}>
                {r.return_pct > 0 ? '+' : ''}{r.return_pct.toFixed(1)}%
              </span>
              <span className="text-[10px]">{formatAgo(r.mtime)}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
});
