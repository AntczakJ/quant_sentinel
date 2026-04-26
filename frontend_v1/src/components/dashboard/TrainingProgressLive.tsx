/**
 * components/dashboard/TrainingProgressLive.tsx
 *
 * Live widget for an active RL training run. Polls /api/training/active every
 * 5 seconds and renders progress bar + current metrics + ETA. Self-hides when
 * no training is running (status=idle) so it stays out of the way.
 *
 * Data source: train_rl.py writes data/training_heartbeat.json per episode;
 * the endpoint surfaces it or returns status=idle after 90s staleness.
 *
 * Intended mount point: Models page, above or beside Training History.
 */

import { memo, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Activity, Clock, Brain, TrendingUp } from 'lucide-react';
import { trainingHistoryAPI } from '../../api/client';
import { EASE_OUT } from '../../lib/motion';

type ActiveResp = Awaited<ReturnType<typeof trainingHistoryAPI.active>>;
type Running = Extract<ActiveResp, { status: 'running' }>;

function formatDuration(sec: number | undefined): string {
  if (sec === undefined || isNaN(sec)) {return '—';}
  if (sec < 60) {return `${Math.round(sec)}s`;}
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  if (m < 60) {return `${m}m ${s}s`;}
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export const TrainingProgressLive = memo(function TrainingProgressLive() {
  const [data, setData] = useState<ActiveResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await trainingHistoryAPI.active();
        if (!cancelled) {setData(r);}
      } catch {
        if (!cancelled) {setData({ status: 'idle' });}
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void poll();
    // 5s cadence — lightweight file-read on backend so this is fine.
    const id = setInterval(poll, 5_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Hide widget entirely when no training is active — no point occupying
  // grid real estate if there's nothing to show. Parent can opt to always
  // render a placeholder by wrapping; we keep this component itself silent.
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-4 justify-center">
        <Activity size={12} className="animate-pulse" />
        Checking training status...
      </div>
    );
  }

  if (!data || data.status === 'idle') {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-6 justify-center">
        <Brain size={14} />
        <span>No active training run</span>
        <span className="text-th-muted">·</span>
        <code className="text-[10px] text-accent-blue bg-dark-bg px-1.5 py-0.5 rounded border border-th-border">
          python train_rl.py 300
        </code>
      </div>
    );
  }

  const r = data as Running;
  const pct = r.total_episodes > 0 ? (r.current_episode / r.total_episodes) * 100 : 0;

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="active"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: EASE_OUT }}
        className="space-y-4"
      >
        {/* Live header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inset-0 rounded-full bg-accent-green/40 animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-accent-green" />
            </span>
            <span className="text-[11px] uppercase tracking-wider text-accent-green font-semibold">
              Training live
            </span>
          </div>
          <span className="text-[10px] text-th-dim font-mono tabular-nums">
            updated {Math.round(r.age_sec)}s ago
          </span>
        </div>

        {/* Episode progress bar */}
        <div>
          <div className="flex items-baseline justify-between mb-2">
            <div className="flex items-baseline gap-2">
              <span className="text-[22px] font-display font-semibold text-th tabular-nums leading-none">
                {r.current_episode}
              </span>
              <span className="text-sm text-th-muted tabular-nums">/ {r.total_episodes}</span>
              <span className="text-[11px] text-th-dim ml-1">episodes</span>
            </div>
            <span className="text-sm font-mono text-accent-green tabular-nums font-semibold">
              {pct.toFixed(1)}%
            </span>
          </div>
          <div className="relative h-2 rounded-full bg-dark-tertiary overflow-hidden">
            <motion.div
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-accent-green via-accent-cyan to-accent-blue rounded-full"
              initial={false}
              animate={{ width: `${pct}%` }}
              transition={{ duration: 0.5, ease: EASE_OUT }}
            />
          </div>
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <MetricTile
            icon={<TrendingUp size={11} className="text-accent-green" />}
            label="Last reward"
            value={r.last_reward.toFixed(2)}
            tone={r.last_reward >= 0 ? 'text-accent-green' : 'text-accent-red'}
          />
          <MetricTile
            icon={<Activity size={11} className="text-accent-blue" />}
            label="Avg (20ep)"
            value={r.avg_reward_20.toFixed(2)}
            tone={r.avg_reward_20 >= 0 ? 'text-accent-green' : 'text-accent-red'}
          />
          <MetricTile
            label="Balance"
            value={`$${Math.round(r.balance).toLocaleString()}`}
            tone="text-th"
          />
          <MetricTile
            label="Epsilon"
            value={r.epsilon.toFixed(3)}
            tone="text-th-secondary"
            hint="Exploration rate"
          />
        </div>

        {/* Footer — elapsed + ETA */}
        <div className="flex items-center justify-between pt-2 border-t border-th-border text-[11px] text-th-muted">
          <div className="flex items-center gap-1.5">
            <Clock size={11} />
            <span>Elapsed <span className="font-mono text-th-secondary">{formatDuration(r.elapsed_sec)}</span></span>
          </div>
          <div>
            <span>ETA </span>
            <span className="font-mono text-accent-blue font-semibold">{formatDuration(r.eta_sec)}</span>
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
