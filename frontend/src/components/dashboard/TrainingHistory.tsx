/**
 * src/components/dashboard/TrainingHistory.tsx — Recent RL training runs.
 *
 * Consumes /api/training/history. Shows val_return trend, best historical
 * run, git commit hash, and timestamps. Useful for "did yesterday's retrain
 * actually improve things?" questions.
 */
import { useState, useEffect, memo } from 'react';
import { GitCommit, TrendingUp, TrendingDown, Clock, Loader2 } from 'lucide-react';
import { trainingHistoryAPI } from '../../api/client';

type Run = {
  model_type: string;
  timestamp: string;
  git_commit?: string;
  git_dirty?: boolean;
  metrics: Record<string, unknown>;
  notes?: string | null;
  artifact_size_kb?: number | null;
};

function formatAgo(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;
  if (isNaN(diffMs)) {return '?';}
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 60) {return `${mins}m ago`;}
  const hours = Math.floor(mins / 60);
  if (hours < 24) {return `${hours}h ago`;}
  return `${Math.floor(hours / 24)}d ago`;
}

export const TrainingHistory = memo(function TrainingHistory() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      try {
        const data = await trainingHistoryAPI.list(15, 'rl_agent');
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

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-th-muted text-sm">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading history...
      </div>
    );
  }

  if (error) {
    return <div className="text-xs text-accent-red p-2">Error: {error}</div>;
  }

  if (!runs || runs.length === 0) {
    return (
      <div className="text-xs text-th-muted p-4 text-center">
        <p>No training history yet.</p>
        <p className="mt-1">Run <code className="bg-dark-bg px-1 rounded">python train_rl.py 300</code> to create the first entry.</p>
      </div>
    );
  }

  // Find best val_return in history
  const bestReturn = runs.reduce((best, r) => {
    const v = Number(r.metrics.val_return ?? NaN);
    return !isNaN(v) && v > best ? v : best;
  }, -Infinity);

  return (
    <div className="space-y-2">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-th-muted uppercase tracking-wider text-[10px] border-b border-dark-secondary">
            <th className="text-left py-1.5 pl-1">When</th>
            <th className="text-right">Val %</th>
            <th className="text-right">WR %</th>
            <th className="text-right">Trades</th>
            <th className="text-left">Commit</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r, i) => {
            const valReturn = Number(r.metrics.val_return ?? NaN);
            const valWr = Number(r.metrics.val_win_rate ?? NaN);
            const trades = Number(r.metrics.val_trades ?? NaN);
            const isBest = !isNaN(valReturn) && valReturn === bestReturn;
            const positive = !isNaN(valReturn) && valReturn > 0;
            return (
              <tr key={i} className={`border-b border-dark-secondary/30 hover:bg-dark-bg/50 ${isBest ? 'bg-accent-green/5' : ''}`}>
                <td className="py-1.5 pl-1 text-th-secondary">
                  <span className="flex items-center gap-1">
                    <Clock size={9} className="text-th-muted" />
                    {formatAgo(r.timestamp)}
                  </span>
                </td>
                <td className={`text-right font-mono ${positive ? 'text-accent-green' : 'text-accent-red'}`}>
                  {!isNaN(valReturn) ? (
                    <span className="flex items-center justify-end gap-0.5">
                      {positive ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
                      {valReturn > 0 ? '+' : ''}{valReturn.toFixed(1)}
                    </span>
                  ) : '—'}
                </td>
                <td className="text-right font-mono text-th-secondary">
                  {!isNaN(valWr) ? valWr.toFixed(0) : '—'}
                </td>
                <td className="text-right font-mono text-th-muted">
                  {!isNaN(trades) ? trades : '—'}
                </td>
                <td className="text-th-muted font-mono text-[10px]">
                  {r.git_commit ? (
                    <span className="flex items-center gap-0.5">
                      <GitCommit size={9} />
                      {r.git_commit}
                      {r.git_dirty && <span className="text-accent-orange" title="uncommitted changes">*</span>}
                    </span>
                  ) : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="text-[10px] text-th-muted flex items-center justify-between px-1">
        <span>{runs.length} runs</span>
        {bestReturn > -Infinity && (
          <span>best val: <span className="text-accent-green font-mono">{bestReturn > 0 ? '+' : ''}{bestReturn.toFixed(1)}%</span></span>
        )}
      </div>
    </div>
  );
});
