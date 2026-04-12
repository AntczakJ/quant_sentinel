/**
 * components/dashboard/VoterAttribution.tsx
 *
 * Per-voter accuracy over the last N days of closed trades. The
 * "correct direction" for a trade is LONG if the trade was a WIN+LONG
 * (or LOSS+SHORT flipped — symmetric); a voter's vote is derived from
 * its stored prediction value (>0.5 ⇒ LONG). Abstains (missing columns,
 * DQN=HOLD) are shown separately and never penalize accuracy.
 *
 * Data source: /api/models/voter-attribution. Matches ml_predictions
 * to trades by timestamp (within 60 min before the trade) — trade_id
 * linkage is historically unset, so a strict join would report zero.
 *
 * Sample size guard: voters with fewer than MIN_VOTES opinions render
 * their accuracy in muted color with a "(n=X)" tag — a 100% accuracy
 * on 2 votes is not a signal.
 */

import { memo, useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { BarChart3, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { voterAttributionAPI } from '../../api/client';
import { EASE_OUT } from '../../lib/motion';

type Resp = Awaited<ReturnType<typeof voterAttributionAPI.get>>;

const MIN_VOTES = 8;

const VOTER_LABEL: Record<string, string> = {
  smc:       'SMC',
  attention: 'Attention',
  dpformer:  'DPformer',
  deeptrans: 'DeepTrans',
  lstm:      'LSTM',
  xgb:       'XGBoost',
  dqn:       'DQN',
};

export const VoterAttribution = memo(function VoterAttribution() {
  const [data, setData] = useState<Resp | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      setLoading(true);
      try {
        const r = await voterAttributionAPI.get(days);
        if (!cancelled) {setData(r);}
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void fetch();
    // Refresh every 5 min — accuracy changes only when new trades close.
    const id = setInterval(fetch, 5 * 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [days]);

  const sorted = useMemo(() => {
    if (!data || data.status !== 'ok') {return [];}
    return Object.entries(data.voters)
      .sort((a, b) => {
        const av = a[1].accuracy ?? -Infinity;
        const bv = b[1].accuracy ?? -Infinity;
        return bv - av;
      });
  }, [data]);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-4 justify-center">
        <BarChart3 size={12} className="animate-pulse" />
        Loading per-voter stats…
      </div>
    );
  }

  if (!data || data.status === 'no_db') {
    return (
      <div className="text-xs text-th-dim py-4 text-center">
        No database available.
      </div>
    );
  }

  if (data.status === 'schema_error') {
    return (
      <div className="text-xs text-accent-amber py-4 text-center">
        Per-voter columns missing — restart the API to apply migrations.
      </div>
    );
  }

  if (data.n_trades === 0) {
    return (
      <div className="text-xs text-th-dim py-6 text-center space-y-1">
        <div>No closed trades in the last {days} days to score voters against.</div>
        <div className="text-[10px] text-th-muted">Check back after trades resolve.</div>
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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 size={14} className="text-accent-blue" />
          <span className="text-[11px] uppercase tracking-wider text-th-secondary font-semibold">
            Voter Attribution
          </span>
          <span className="text-[10px] text-th-dim font-mono">
            · {data.n_trades} closed trades · last {data.days}d
          </span>
        </div>
        <div className="flex items-center gap-1 text-[10px] font-mono">
          {[7, 30, 90].map(d => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              className={`px-2 py-0.5 rounded border transition-colors
                ${days === d
                  ? 'bg-accent-blue/15 text-accent-blue border-accent-blue/40'
                  : 'text-th-dim border-th-border hover:border-th-border-h'}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {sorted.map(([voter, s]) => (
          <VoterRow
            key={voter}
            label={VOTER_LABEL[voter] ?? voter}
            accuracy={s.accuracy}
            correct={s.correct}
            abstain={s.abstain}
            nVoted={s.n_voted}
          />
        ))}
      </div>
    </motion.div>
  );
});

function VoterRow({
  label, accuracy, correct, abstain, nVoted,
}: {
  label: string;
  accuracy: number | null;
  correct: number;
  abstain: number;
  nVoted: number;
}) {
  const underpowered = nVoted < MIN_VOTES;
  const acc = accuracy ?? 0;
  const pct = Math.round(acc * 100);
  const barTone =
    accuracy === null ? 'bg-th-border'
    : acc >= 0.55 ? 'bg-accent-green'
    : acc >= 0.45 ? 'bg-accent-amber'
    : 'bg-accent-red';
  const textTone =
    underpowered ? 'text-th-dim'
    : accuracy === null ? 'text-th-dim'
    : acc >= 0.55 ? 'text-accent-green'
    : acc >= 0.45 ? 'text-accent-amber'
    : 'text-accent-red';
  const icon =
    accuracy === null ? <Minus size={11} className="text-th-dim" />
    : acc >= 0.55 ? <TrendingUp size={11} className="text-accent-green" />
    : acc >= 0.45 ? <Minus size={11} className="text-accent-amber" />
    : <TrendingDown size={11} className="text-accent-red" />;

  return (
    <div className="grid grid-cols-[100px_1fr_auto] items-center gap-3 text-[11px]">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="font-semibold text-th-secondary">{label}</span>
      </div>
      <div className="relative h-5 rounded bg-dark-tertiary overflow-hidden">
        {accuracy !== null && (
          <motion.div
            className={`absolute inset-y-0 left-0 ${barTone} rounded`}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(3, pct)}%` }}
            transition={{ duration: 0.6, ease: EASE_OUT }}
          />
        )}
        <div className={`absolute inset-0 flex items-center px-2 text-[10px] font-mono tabular-nums ${textTone}`}>
          {accuracy === null ? (
            <span className="italic">no data</span>
          ) : (
            <>
              <span className="font-semibold">{pct}%</span>
              <span className="ml-2 text-th-muted">
                {correct}/{nVoted} voted{abstain > 0 && ` · ${abstain} abstain`}
              </span>
            </>
          )}
        </div>
      </div>
      <div className="font-mono text-[10px] text-th-muted tabular-nums w-12 text-right">
        {underpowered ? `n=${nVoted}` : ''}
      </div>
    </div>
  );
}
