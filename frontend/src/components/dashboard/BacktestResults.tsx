/**
 * src/components/dashboard/BacktestResults.tsx — Backtest run viewer.
 *
 * Reads /api/backtest/runs — shows last N backtest results as a sortable
 * table with key quant metrics. Read-only, zero production-state mutation.
 */
import { useState, useEffect, memo, useMemo } from 'react';
import {
  Loader2, TrendingUp, TrendingDown, Clock, Activity,
  CheckCircle, XCircle, BarChart3, Target, Image as ImageIcon,
  XOctagon, Dices, GitCompare,
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

type RunDetails = Awaited<ReturnType<typeof backtestResultsAPI.loadByName>>['data'];


// ── Small inline bar chart (SVG, no recharts dep) ────────────────────
function RejectionsChart({ rejections }: { rejections: Array<[string, string, number]> }) {
  if (!rejections.length) {return null;}
  const max = Math.max(...rejections.map(r => r[2]));
  return (
    <div className="space-y-1">
      {rejections.map(([filter, reason, count], i) => {
        const pct = (count / max) * 100;
        return (
          <div key={i} className="text-[10px]">
            <div className="flex items-center justify-between text-th-muted mb-0.5">
              <span className="truncate" title={`${filter}: ${reason}`}>
                {filter}
              </span>
              <span className="font-mono">{count}</span>
            </div>
            <div className="relative h-2 bg-dark-bg rounded overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-accent-orange/60"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}


function MonteCarloChart({ mc }: { mc: NonNullable<RunDetails['monte_carlo']> }) {
  const p5 = mc.return_p5 ?? 0;
  const p50 = mc.return_p50 ?? 0;
  const p95 = mc.return_p95 ?? 0;
  const prob = mc.prob_profitable ?? 0;
  // Render a distribution bar: red → gray → green based on where 0 falls
  const minV = Math.min(p5, 0) - 0.5;
  const maxV = Math.max(p95, 0) + 0.5;
  const range = maxV - minV;
  const p5Pos = ((p5 - minV) / range) * 100;
  const p50Pos = ((p50 - minV) / range) * 100;
  const p95Pos = ((p95 - minV) / range) * 100;
  const zeroPos = ((0 - minV) / range) * 100;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-th-muted">{mc.n_simulations} sims × {mc.n_trades} trades</span>
        <span className={prob > 70 ? 'text-accent-green' : prob > 50 ? 'text-accent-cyan' : 'text-accent-red'}>
          {prob.toFixed(0)}% profitable
        </span>
      </div>
      <div className="relative h-3 bg-dark-bg rounded overflow-hidden">
        <div
          className="absolute inset-y-0 bg-accent-purple/40"
          style={{ left: `${p5Pos}%`, width: `${p95Pos - p5Pos}%` }}
        />
        {/* Zero marker */}
        <div
          className="absolute inset-y-0 w-px bg-white/70"
          style={{ left: `${zeroPos}%` }}
          title="break-even (0%)"
        />
        {/* Median marker */}
        <div
          className="absolute inset-y-0 w-0.5 bg-accent-purple"
          style={{ left: `${p50Pos}%` }}
          title={`p50: ${p50.toFixed(2)}%`}
        />
      </div>
      <div className="grid grid-cols-3 text-[10px] font-mono">
        <div className="text-th-muted">p5: <span className={p5 > 0 ? 'text-accent-green' : 'text-accent-red'}>{p5.toFixed(2)}%</span></div>
        <div className="text-center">p50: {p50.toFixed(2)}%</div>
        <div className="text-right text-th-muted">p95: {p95.toFixed(2)}%</div>
      </div>
    </div>
  );
}


function CompareDialog({ runs, onClose }: { runs: Run[]; onClose: () => void }) {
  const [a, setA] = useState(runs[0]?.name ?? '');
  const [b, setB] = useState(runs[1]?.name ?? runs[0]?.name ?? '');
  const runA = runs.find(r => r.name === a);
  const runB = runs.find(r => r.name === b);

  // Close on Escape key (standard modal pattern)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') {onClose();} };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);
  const rows: Array<[string, (r: Run) => number | string | null]> = [
    ['Trades', r => r.trades],
    ['WR %', r => r.win_rate_pct],
    ['Profit Factor', r => r.profit_factor],
    ['Return %', r => r.return_pct],
    ['Max DD %', r => r.max_drawdown_pct],
    ['Max Loss Streak', r => r.max_consec_losses],
    ['Sharpe', r => r.sharpe],
    ['Sortino', r => r.sortino],
    ['Alpha vs B&H pp', r => r.alpha_vs_bh_pct],
    ['Expectancy $', r => r.expectancy],
  ];
  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="compare-dialog-title"
      onClick={(e) => { if (e.target === e.currentTarget) {onClose();} }}
    >
      <div className="bg-dark-surface border border-dark-secondary rounded-lg p-4 max-w-2xl w-full shadow-panel">
        <div className="flex items-center justify-between mb-3">
          <h3 id="compare-dialog-title" className="text-sm font-medium flex items-center gap-2">
            <GitCompare size={14} aria-hidden="true" /> Compare Runs
          </h3>
          <button
            onClick={onClose}
            className="text-th-muted hover:text-th p-1 focus-visible:outline-2 focus-visible:outline-accent"
            aria-label="Close compare dialog"
          >
            <XOctagon size={14} aria-hidden="true" />
          </button>
        </div>
        <div className="flex gap-2 mb-3 text-xs">
          <label className="flex-1">
            <span className="sr-only">Run A</span>
            <select value={a} onChange={e => setA(e.target.value)}
                    aria-label="First run to compare (A)"
                    className="w-full bg-dark-bg border border-dark-secondary rounded px-2 py-1">
              {runs.map(r => <option key={r.name} value={r.name}>A: {r.name}</option>)}
            </select>
          </label>
          <label className="flex-1">
            <span className="sr-only">Run B</span>
            <select value={b} onChange={e => setB(e.target.value)}
                    aria-label="Second run to compare (B)"
                    className="w-full bg-dark-bg border border-dark-secondary rounded px-2 py-1">
              {runs.map(r => <option key={r.name} value={r.name}>B: {r.name}</option>)}
            </select>
          </label>
        </div>
        {runA && runB && (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-th-muted border-b border-dark-secondary">
                <th className="text-left py-1">Metric</th>
                <th className="text-right">A</th>
                <th className="text-right">B</th>
                <th className="text-right">Δ (B-A)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([label, get]) => {
                const va = get(runA);
                const vb = get(runB);
                const aNum = typeof va === 'number' ? va : null;
                const bNum = typeof vb === 'number' ? vb : null;
                const delta = aNum !== null && bNum !== null ? bNum - aNum : null;
                return (
                  <tr key={label} className="border-b border-dark-secondary/30">
                    <td className="py-1 text-th-secondary">{label}</td>
                    <td className="text-right font-mono">{va ?? '—'}</td>
                    <td className="text-right font-mono">{vb ?? '—'}</td>
                    <td className={`text-right font-mono ${delta && delta > 0 ? 'text-accent-green' : delta && delta < 0 ? 'text-accent-red' : ''}`}>
                      {delta !== null ? (delta > 0 ? '+' : '') + delta.toFixed(2) : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}


export const BacktestResults = memo(function BacktestResults() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState<RunDetails | null>(null);
  const [showCompare, setShowCompare] = useState(false);

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

  // Fetch full JSON for selected run (rejections, MC, analytics)
  useEffect(() => {
    if (!selectedRun) {return;}
    let cancelled = false;
    backtestResultsAPI.loadByName(selectedRun.name)
      .then(res => { if (!cancelled) {setDetails(res.data);} })
      .catch(() => { if (!cancelled) {setDetails(null);} });
    return () => { cancelled = true; };
  }, [selectedRun?.name]);

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

          {/* Equity curve PNG (if exists) */}
          <div className="mt-3 pt-3 border-t border-dark-secondary">
            <div className="text-[10px] text-th-muted uppercase tracking-wider mb-1 flex items-center gap-1">
              <ImageIcon size={10} /> Equity Curve
            </div>
            <img
              src={backtestResultsAPI.chartUrl(selectedRun.name)}
              alt={`Equity curve for ${selectedRun.name}`}
              className="w-full rounded border border-dark-secondary bg-white"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = 'none';
                const sib = (e.currentTarget as HTMLImageElement).nextElementSibling as HTMLElement | null;
                if (sib) {sib.style.display = 'block';}
              }}
            />
            <div className="text-[10px] text-th-muted italic" style={{ display: 'none' }}>
              No equity PNG for this run — add <code>--plot-equity reports/{selectedRun.name}.png</code>
            </div>
          </div>

          {/* Monte Carlo distribution */}
          {details?.monte_carlo && (
            <div className="mt-3 pt-3 border-t border-dark-secondary">
              <div className="text-[10px] text-th-muted uppercase tracking-wider mb-2 flex items-center gap-1">
                <Dices size={10} /> Monte Carlo (bootstrap)
              </div>
              <MonteCarloChart mc={details.monte_carlo} />
            </div>
          )}

          {/* Rejection reasons */}
          {details?.top_rejections && details.top_rejections.length > 0 && (
            <div className="mt-3 pt-3 border-t border-dark-secondary">
              <div className="text-[10px] text-th-muted uppercase tracking-wider mb-2 flex items-center gap-1">
                <XOctagon size={10} /> Top rejection reasons
              </div>
              <RejectionsChart rejections={details.top_rejections} />
            </div>
          )}
        </div>
      )}

      {/* Run list (click to select) */}
      <div className="space-y-1">
        <div className="text-[10px] text-th-muted uppercase tracking-wider px-1 flex items-center justify-between">
          <span>Recent runs ({runs.length})</span>
          {runs.length >= 2 && (
            <button
              onClick={() => setShowCompare(true)}
              className="flex items-center gap-1 text-accent-cyan hover:text-accent-blue normal-case tracking-normal"
            >
              <GitCompare size={10} /> Compare
            </button>
          )}
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

      {showCompare && runs.length >= 2 && (
        <CompareDialog runs={runs} onClose={() => setShowCompare(false)} />
      )}
    </div>
  );
});
