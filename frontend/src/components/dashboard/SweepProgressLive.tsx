/**
 * components/dashboard/SweepProgressLive.tsx
 *
 * Live widget for an active Optuna hyperparameter sweep. Polls
 * /api/sweep/active every 5 seconds and renders trial progress + current
 * trial episode + best-so-far + ETA. Self-hides when no sweep is running.
 *
 * Data source: tune_rl.py writes data/sweep_heartbeat.json at each
 * validation checkpoint (~every 100-300s during training). The API has
 * a 300s grace window before declaring the sweep idle.
 *
 * Intended mount point: Models page, directly below Live Training so
 * operators can see both at-a-glance.
 */

import { memo, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Activity, Clock, FlaskConical, TrendingUp, Zap } from 'lucide-react';
import { sweepAPI } from '../../api/client';
import { EASE_OUT } from '../../lib/motion';

type ActiveResp = Awaited<ReturnType<typeof sweepAPI.active>>;
type Running = Extract<ActiveResp, { status: 'running' | 'completed' | 'interrupted' }>;

function formatDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || isNaN(sec)) {return '—';}
  if (sec < 60) {return `${Math.round(sec)}s`;}
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m < 60) {return `${m}m ${s}s`;}
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function signed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || isNaN(v)) {return '—';}
  const s = v.toFixed(digits);
  return v >= 0 ? `+${s}` : s;
}

export const SweepProgressLive = memo(function SweepProgressLive() {
  const [data, setData] = useState<ActiveResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await sweepAPI.active();
        if (!cancelled) {setData(r);}
      } catch {
        if (!cancelled) {setData({ status: 'idle' });}
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void poll();
    // 5s cadence matches the training widget for visual consistency.
    // Endpoint just reads one JSON file, so there's no backend cost concern.
    const id = setInterval(poll, 5_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-4 justify-center">
        <Activity size={12} className="animate-pulse" />
        Checking sweep status...
      </div>
    );
  }

  if (!data || data.status === 'idle') {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-6 justify-center">
        <FlaskConical size={14} />
        <span>No active hyperparameter sweep</span>
        <span className="text-th-muted">·</span>
        <code className="text-[10px] text-accent-blue bg-dark-bg px-1.5 py-0.5 rounded border border-th-border">
          python tune_rl.py --n-trials 60 --episodes 150
        </code>
      </div>
    );
  }

  const r = data as Running;
  const trials_done = (r.completed_trials ?? 0) + (r.pruned_trials ?? 0);
  const trial_pct = r.n_trials_target > 0 ? (trials_done / r.n_trials_target) * 100 : 0;
  const ep = r.current_episode ?? 0;
  const total = r.total_episodes ?? 0;
  const ep_pct = total > 0 ? (ep / total) * 100 : 0;
  const statusColor =
    r.status === 'running' ? 'accent-green'
    : r.status === 'completed' ? 'accent-blue'
    : 'accent-amber';

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="active"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE_OUT }}
        className="space-y-4"
      >
        {/* Header — status pulse + study name */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              {r.status === 'running' && (
                <span className={`absolute inset-0 rounded-full bg-${statusColor}/40 animate-ping`} />
              )}
              <span className={`relative inline-flex h-2 w-2 rounded-full bg-${statusColor}`} />
            </span>
            <span className={`text-[11px] uppercase tracking-wider text-${statusColor} font-semibold`}>
              Sweep {r.status}
            </span>
            <span className="text-[10px] text-th-dim font-mono">
              · {r.study_name}
            </span>
          </div>
          <span className="text-[10px] text-th-dim font-mono tabular-nums">
            updated {Math.round(r.age_sec)}s ago
          </span>
        </div>

        {/* Trial progress bar (the primary progress signal) */}
        <div>
          <div className="flex items-baseline justify-between mb-2">
            <div className="flex items-baseline gap-2">
              <span className="text-[22px] font-display font-semibold text-th tabular-nums leading-none">
                {trials_done}
              </span>
              <span className="text-sm text-th-muted tabular-nums">/ {r.n_trials_target}</span>
              <span className="text-[11px] text-th-dim ml-1">trials</span>
              {r.pruned_trials > 0 && (
                <span className="text-[10px] text-accent-amber ml-2 font-mono">
                  ({r.pruned_trials} pruned)
                </span>
              )}
            </div>
            <span className={`text-sm font-mono text-${statusColor} tabular-nums font-semibold`}>
              {trial_pct.toFixed(1)}%
            </span>
          </div>
          <div className="relative h-2 rounded-full bg-dark-tertiary overflow-hidden">
            <motion.div
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-accent-green via-accent-cyan to-accent-blue rounded-full"
              initial={false}
              animate={{ width: `${trial_pct}%` }}
              transition={{ duration: 0.5, ease: EASE_OUT }}
            />
          </div>
        </div>

        {/* Current trial mini-progress (secondary) */}
        {r.status === 'running' && total > 0 && (
          <div>
            <div className="flex items-center justify-between text-[11px] text-th-muted">
              <span>
                Trial <span className="font-mono text-th-secondary">#{r.trial_number}</span>
                {' '}episode <span className="font-mono text-th-secondary">{ep}/{total}</span>
              </span>
              <span className="font-mono tabular-nums">{ep_pct.toFixed(0)}%</span>
            </div>
            <div className="relative h-1 mt-1 rounded-full bg-dark-tertiary overflow-hidden">
              <motion.div
                className="absolute inset-y-0 left-0 bg-th-border-h/60 rounded-full"
                initial={false}
                animate={{ width: `${ep_pct}%` }}
                transition={{ duration: 0.4, ease: EASE_OUT }}
              />
            </div>
          </div>
        )}

        {/* Key metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricTile
            icon={<TrendingUp size={11} className="text-accent-green" />}
            label="Best val"
            value={signed(r.best_val_so_far) + '%'}
            tone={r.best_val_so_far !== null && r.best_val_so_far >= 0
              ? 'text-accent-green' : 'text-accent-red'}
            hint="Across all completed trials"
          />
          <MetricTile
            icon={<Zap size={11} className="text-accent-cyan" />}
            label="This trial"
            value={signed(r.current_trial_best) + '%'}
            tone={r.current_trial_best !== null && r.current_trial_best >= 0
              ? 'text-accent-green' : 'text-accent-red'}
          />
          <MetricTile
            label="Completed"
            value={`${r.completed_trials ?? 0}`}
            tone="text-th"
            hint={`${r.pruned_trials ?? 0} pruned`}
          />
          <MetricTile
            label="Trial state"
            value={r.last_trial_state ?? '—'}
            tone="text-th-secondary"
          />
        </div>

        {/* Footer — elapsed + ETA */}
        <div className="flex items-center justify-between pt-2 border-t border-th-border text-[11px] text-th-muted">
          <div className="flex items-center gap-1.5">
            <Clock size={11} />
            <span>
              Elapsed{' '}
              <span className="font-mono text-th-secondary">
                {formatDuration(r.elapsed_total_sec)}
              </span>
            </span>
          </div>
          <div>
            <span>ETA </span>
            <span className="font-mono text-accent-blue font-semibold">
              {formatDuration(r.eta_sec)}
            </span>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
});

function MetricTile({
  icon, label, value, tone = 'text-th', hint,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-th-border bg-dark-surface/40 p-2.5
                    transition-colors hover:border-th-border-h">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-th-dim font-medium">
        {icon}
        <span>{label}</span>
      </div>
      <div className={`mt-1 font-mono text-sm font-semibold tabular-nums ${tone}`}>
        {value}
      </div>
      {hint && <div className="text-[9px] text-th-dim mt-0.5">{hint}</div>}
    </div>
  );
}
