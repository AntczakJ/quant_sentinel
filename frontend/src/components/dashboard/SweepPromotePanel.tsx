/**
 * components/dashboard/SweepPromotePanel.tsx
 *
 * Side-by-side view of the current production RL model vs. the latest
 * sweep winner, with a confirmed "Promote" action. The backend endpoint
 * backs up production before copying, so promotion is reversible by
 * restoring from the backup path shown in the success state.
 *
 * The Promote button is deliberately gated by TWO steps: (1) the panel
 * only lights up when winner_available=true on the server, and (2) the
 * modal requires checking "I have verified the winner is better" before
 * the POST fires. Operators should run `eval_rl.py --compare` manually
 * before promoting — the panel links the command for convenience.
 */

import { memo, useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  ArrowRight, CheckCircle2, AlertTriangle, Archive, Cpu, RefreshCw, XCircle,
} from 'lucide-react';
import { sweepAPI } from '../../api/client';
import { EASE_OUT } from '../../lib/motion';

type Info = Awaited<ReturnType<typeof sweepAPI.winnerInfo>>;
type PromoteResp = Awaited<ReturnType<typeof sweepAPI.promote>>;

function fmtMB(bytes?: number): string {
  if (!bytes) {return '—';}
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
function fmtAge(hours?: number): string {
  if (hours === undefined || hours === null) {return '—';}
  if (hours < 1) {return `${Math.round(hours * 60)}m ago`;}
  if (hours < 48) {return `${hours.toFixed(1)}h ago`;}
  return `${Math.floor(hours / 24)}d ago`;
}

export const SweepPromotePanel = memo(function SweepPromotePanel() {
  const [info, setInfo] = useState<Info | null>(null);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PromoteResp | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await sweepAPI.winnerInfo();
      setInfo(r);
    } catch {
      setInfo(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const doPromote = useCallback(async () => {
    if (!confirmed) {return;}
    setBusy(true);
    setResult(null);
    try {
      const r = await sweepAPI.promote(true);
      setResult(r);
      // On success, refresh the info panel so mtimes update.
      if (r.status === 'ok') { await refresh(); }
    } catch (e) {
      setResult({
        status: 'error',
        reason: e instanceof Error ? e.message : 'Unknown error',
      });
    } finally {
      setBusy(false);
    }
  }, [confirmed, refresh]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-dim py-4 justify-center">
        <RefreshCw size={12} className="animate-spin" />
        Reading model slots...
      </div>
    );
  }

  if (!info) {
    return (
      <div className="flex items-center gap-2 text-xs text-accent-red py-4 justify-center">
        <XCircle size={12} />
        Could not load winner info.
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: EASE_OUT }}
      className="space-y-4"
    >
      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] items-stretch gap-4">
        <SlotCard
          label="Production"
          tone="accent-blue"
          icon={<Cpu size={13} className="text-accent-blue" />}
          info={info.production}
        />
        <div className="flex flex-col items-center justify-center gap-3 md:px-2">
          <ArrowRight size={22} className={info.winner_available
            ? 'text-accent-green' : 'text-th-dim'} />
          <button
            type="button"
            onClick={() => {
              setConfirmed(false);
              setResult(null);
              setModal(true);
            }}
            disabled={!info.winner_available}
            className={`px-4 py-2 rounded-lg text-[12px] font-semibold border transition-all
              ${info.winner_available
                ? 'bg-accent-green/10 text-accent-green border-accent-green/40 hover:bg-accent-green/20'
                : 'bg-dark-bg text-th-dim border-th-border cursor-not-allowed'}`}
          >
            Promote winner
          </button>
          {!info.winner_available && (
            <span className="text-[10px] text-th-dim text-center max-w-[160px]">
              No winner file yet — run{' '}
              <code className="text-accent-blue">tune_rl.py --apply-winner</code>
            </span>
          )}
        </div>
        <SlotCard
          label="Sweep winner"
          tone="accent-green"
          icon={<CheckCircle2 size={13} className={info.winner_available
            ? 'text-accent-green' : 'text-th-dim'} />}
          info={info.winner}
          missing={!info.winner_available}
        />
      </div>

      {info.last_promote_ts && (
        <div className="flex items-center gap-2 text-[10px] text-th-muted">
          <Archive size={11} />
          <span>
            Last promote{' '}
            <span className="font-mono text-th-secondary">{info.last_promote_ts}</span>
            {info.last_promote_backup && (
              <>
                {' '}· backup{' '}
                <code className="text-[9px] bg-dark-bg px-1 py-0.5 rounded border border-th-border">
                  {info.last_promote_backup}
                </code>
              </>
            )}
          </span>
        </div>
      )}

      {/* Confirmation modal */}
      <AnimatePresence>
        {modal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
            onClick={() => !busy && setModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.2, ease: EASE_OUT }}
              className="w-full max-w-md bg-dark-surface border border-th-border rounded-xl p-5 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-2">
                <AlertTriangle size={16} className="text-accent-amber" />
                <h3 className="text-sm font-semibold text-th">
                  Confirm production model replace
                </h3>
              </div>

              <div className="text-[12px] text-th-secondary leading-relaxed space-y-2">
                <p>
                  This replaces{' '}
                  <code className="text-accent-blue">models/rl_agent.keras</code> with the
                  latest sweep winner. A timestamped backup is created first:
                  recovery is possible but manual.
                </p>
                <p className="text-th-muted text-[11px]">
                  Verify with{' '}
                  <code className="bg-dark-bg px-1 py-0.5 rounded border border-th-border">
                    python eval_rl.py --compare models/rl_agent.keras models/rl_sweep_winner.keras
                  </code>
                  {' '}before clicking.
                </p>
              </div>

              <label className="flex items-start gap-2 text-[12px] text-th select-none cursor-pointer">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  I have run <code className="text-accent-cyan">eval_rl.py --compare</code>
                  {' '}and verified the winner is an improvement.
                </span>
              </label>

              {result && (
                <div className={`p-3 rounded-lg border text-[11px] leading-relaxed
                  ${result.status === 'ok'
                    ? 'bg-accent-green/5 border-accent-green/30 text-accent-green'
                    : 'bg-accent-red/5 border-accent-red/30 text-accent-red'}`}
                >
                  {result.status === 'ok' ? (
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 font-semibold">
                        <CheckCircle2 size={13} />
                        Promote complete — timestamp {result.timestamp}
                      </div>
                      {result.backup && (
                        <div className="text-th-muted text-[10px]">
                          Backup: <code>{result.backup}</code>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-start gap-2">
                      <XCircle size={13} className="mt-0.5" />
                      <span>{result.reason}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setModal(false)}
                  disabled={busy}
                  className="px-3 py-1.5 text-[12px] rounded-lg border border-th-border
                             text-th-secondary hover:bg-dark-bg disabled:opacity-50"
                >
                  {result?.status === 'ok' ? 'Close' : 'Cancel'}
                </button>
                {(!result || result.status !== 'ok') && (
                  <button
                    type="button"
                    onClick={doPromote}
                    disabled={!confirmed || busy}
                    className="px-3 py-1.5 text-[12px] rounded-lg font-semibold
                               bg-accent-green/15 text-accent-green border border-accent-green/40
                               hover:bg-accent-green/25 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {busy ? 'Promoting…' : 'Promote'}
                  </button>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

function SlotCard({
  label, tone, icon, info, missing = false,
}: {
  label: string;
  tone: string;
  icon: React.ReactNode;
  info: { model: { exists: boolean; path: string; size_bytes?: number; mtime_iso?: string; age_hours?: number } };
  missing?: boolean;
}) {
  const m = info.model;
  return (
    <div className={`rounded-lg border p-3 space-y-2 transition-opacity
      ${missing ? 'opacity-50 border-th-border bg-dark-bg'
                : `border-th-border bg-dark-surface/40 hover:border-${tone}/40`}`}
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-th-dim font-medium">
        {icon}
        <span>{label}</span>
      </div>
      {m.exists ? (
        <div className="space-y-1 text-[11px] text-th-secondary font-mono">
          <div className="truncate" title={m.path}>{m.path}</div>
          <div className="flex items-center justify-between text-[10px] text-th-muted">
            <span>{fmtMB(m.size_bytes)}</span>
            <span>{fmtAge(m.age_hours)}</span>
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-th-dim italic">file not found</div>
      )}
    </div>
  );
}
