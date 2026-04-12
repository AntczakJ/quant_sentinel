/**
 * components/dashboard/SweepLeaderboard.tsx
 *
 * Top trials from the Optuna RL sweep, refreshed every 15s. Shows which
 * region of hyperparameter space TPE is converging on — the key signal
 * operators need to decide whether to let the sweep continue or stop
 * early. Complements SweepProgressLive, which only shows CURRENT trial
 * state.
 *
 * Data source: GET /api/sweep/leaderboard (reads Optuna's SQLite
 * directly, no dependency on the heartbeat file). Safe to poll while
 * the sweep writes — SQLAlchemy / SQLite handle concurrent readers fine.
 */

import { memo, useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Trophy, RefreshCw, AlertCircle } from 'lucide-react';
import { sweepAPI } from '../../api/client';
import { EASE_OUT } from '../../lib/motion';

type Resp = Awaited<ReturnType<typeof sweepAPI.leaderboard>>;
type Trial = Resp['trials'][number];

function fmtNumber(v: unknown, digits = 3): string {
  if (typeof v !== 'number' || isNaN(v)) {return '—';}
  if (Math.abs(v) < 1e-4 && v !== 0) {return v.toExponential(1);}
  return v.toFixed(digits);
}
function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || isNaN(v)) {return '—';}
  const s = v.toFixed(digits);
  return v >= 0 ? `+${s}` : s;
}
function fmtDuration(sec: number | null): string {
  if (sec === null || isNaN(sec)) {return '—';}
  if (sec < 60) {return `${Math.round(sec)}s`;}
  const m = Math.floor(sec / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

const STATE_COLORS: Record<Trial['state'], string> = {
  COMPLETE: 'text-accent-green',
  PRUNED: 'text-accent-amber',
  RUNNING: 'text-accent-cyan',
  FAIL: 'text-accent-red',
  WAITING: 'text-th-dim',
};

export const SweepLeaderboard = memo(function SweepLeaderboard() {
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<number>(Date.now());

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await sweepAPI.leaderboard('rl_sweep_v1', 12);
        if (!cancelled) {
          setData(r);
          setLastRefresh(Date.now());
        }
      } catch {
        // Keep stale data on fetch failure — better than flashing a blank.
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void poll();
    const id = setInterval(poll, 15_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-4 justify-center">
        <RefreshCw size={12} className="animate-spin" />
        Loading leaderboard…
      </div>
    );
  }

  if (!data || data.status === 'no_study') {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-6 justify-center">
        <Trophy size={14} />
        <span>No sweep study yet</span>
        <span className="text-th-muted">·</span>
        <code className="text-[10px] text-accent-blue bg-dark-bg px-1.5 py-0.5 rounded border border-th-border">
          python tune_rl.py
        </code>
      </div>
    );
  }

  if (data.status === 'error') {
    return (
      <div className="flex items-center gap-2 text-xs text-accent-red py-4 justify-center">
        <AlertCircle size={12} />
        <span>Leaderboard error: {data.error}</span>
      </div>
    );
  }

  if (data.trials.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 text-xs text-th-dim py-6">
        <Trophy size={14} />
        <span>No completed trials yet — TPE is still exploring.</span>
        <span className="text-[10px] text-th-muted">
          {data.n_running ?? 0} running · {data.n_pruned ?? 0} pruned · {data.n_trials} total
        </span>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: EASE_OUT }}
      className="space-y-3"
    >
      {/* Header with totals */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trophy size={14} className="text-accent-green" />
          <span className="text-[11px] uppercase tracking-wider text-th-secondary font-semibold">
            Leaderboard
          </span>
          <span className="text-[10px] text-th-dim font-mono">
            · {data.study_name}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-th-muted font-mono tabular-nums">
          <span>
            best <span className="text-accent-green font-semibold">
              {fmtSigned(data.best_value)}%
            </span>
            {data.best_trial_number !== null && data.best_trial_number !== undefined && (
              <span className="text-th-dim"> (#{data.best_trial_number})</span>
            )}
          </span>
          <span>·</span>
          <span>
            {data.n_completed ?? 0}/{data.n_trials} done
          </span>
          {(data.n_pruned ?? 0) > 0 && (
            <>
              <span>·</span>
              <span className="text-accent-amber">{data.n_pruned} pruned</span>
            </>
          )}
          <span>·</span>
          <span>{Math.round((Date.now() - lastRefresh) / 1000)}s ago</span>
        </div>
      </div>

      {/* Compact table of key hyperparameters */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono tabular-nums">
          <thead>
            <tr className="border-b border-th-border text-th-dim text-[10px] uppercase tracking-wider">
              <th className="text-left py-1.5 pl-1">#</th>
              <th className="text-right">Val%</th>
              <th className="text-right">LR</th>
              <th className="text-right">γ</th>
              <th className="text-right">nStep</th>
              <th className="text-right">Net</th>
              <th className="text-right">RR</th>
              <th className="text-left pl-3">Data</th>
              <th className="text-right pr-1">Dur</th>
              <th className="text-right pr-1">State</th>
            </tr>
          </thead>
          <tbody>
            {data.trials.map((t, i) => {
              const p = t.params as Record<string, number | string>;
              const isBest = t.number === data.best_trial_number;
              return (
                <tr
                  key={t.number}
                  className={`border-b border-th-border/40 hover:bg-dark-surface/40 transition-colors
                    ${isBest ? 'bg-accent-green/5' : ''}`}
                >
                  <td className="py-1.5 pl-1 text-th-secondary">
                    {isBest && <Trophy size={10} className="inline text-accent-green mr-0.5" />}
                    {i + 1}
                    <span className="text-th-dim ml-1">({t.number})</span>
                  </td>
                  <td className={`text-right font-semibold ${
                    t.value !== null && t.value >= 0 ? 'text-accent-green' : 'text-accent-red'
                  }`}>
                    {fmtSigned(t.value, 2)}
                  </td>
                  <td className="text-right text-th-secondary">
                    {fmtNumber(p.lr, 4)}
                  </td>
                  <td className="text-right text-th-secondary">
                    {fmtNumber(p.gamma, 2)}
                  </td>
                  <td className="text-right text-th-secondary">
                    {p.n_step ?? '—'}
                  </td>
                  <td className="text-right text-th-secondary">
                    {p.net_width ?? '—'}×{p.net_depth ?? '—'}
                  </td>
                  <td className="text-right text-th-secondary">
                    {fmtNumber(p.target_rr, 1)}
                  </td>
                  <td className="text-left pl-3 text-th-secondary">
                    {String(p.data_config ?? '—')}
                  </td>
                  <td className="text-right pr-1 text-th-dim">
                    {fmtDuration(t.duration_sec)}
                  </td>
                  <td className={`text-right pr-1 text-[10px] ${STATE_COLORS[t.state]}`}>
                    {t.state}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
});
