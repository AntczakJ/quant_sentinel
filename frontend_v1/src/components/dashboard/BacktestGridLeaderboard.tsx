/**
 * components/dashboard/BacktestGridLeaderboard.tsx
 *
 * Surfaces results from run_backtest_grid.py — systematic parameter sweeps
 * over (min_confidence, sl_atr_mult, target_rr). Each run is a JSON array of
 * {params, stats} entries; this widget loads them and ranks side-by-side so
 * you can eyeball the best-performing config without reading raw JSON.
 *
 * Features:
 *   - Grid file selector when multiple files exist.
 *   - Sort by metric (Sharpe, PF, Win Rate, Return, Trades).
 *   - Top-3 rows highlighted with ordinal badge.
 *   - Median-based outperform delta (+/- vs middle of pack).
 *   - Empty state points users to the CLI command to generate one.
 */

import { memo, useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Trophy, Loader2, FlaskConical } from 'lucide-react';
import { backtestResultsAPI } from '../../api/client';
import { staggerContainer, staggerItem } from '../../lib/motion';

type GridMeta = Awaited<ReturnType<typeof backtestResultsAPI.listGrids>>['grids'][number];
type GridPayload = Awaited<ReturnType<typeof backtestResultsAPI.loadGrid>>;
type Entry = GridPayload['entries'][number];

type SortKey = 'sharpe' | 'profit_factor' | 'win_rate_pct' | 'return_pct' | 'total_trades';

const SORT_OPTIONS: { key: SortKey; label: string; fmt: (v: unknown) => string }[] = [
  { key: 'sharpe',        label: 'Sharpe',   fmt: (v) => (typeof v === 'number' ? v.toFixed(2) : '—') },
  { key: 'profit_factor', label: 'PF',       fmt: (v) => (typeof v === 'number' ? v.toFixed(2) : String(v ?? '—')) },
  { key: 'win_rate_pct',  label: 'Win Rate', fmt: (v) => (typeof v === 'number' ? `${v.toFixed(0)}%` : '—') },
  { key: 'return_pct',    label: 'Return',   fmt: (v) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '—') },
  { key: 'total_trades',  label: 'Trades',   fmt: (v) => (typeof v === 'number' ? String(v) : '—') },
];

function getMetric(e: Entry, key: SortKey): number | null {
  const raw = e.stats?.[key];
  if (typeof raw === 'number') {return raw;}
  if (typeof raw === 'string') {
    const n = parseFloat(raw);
    return isNaN(n) ? null : n;
  }
  return null;
}

function rankOrdinal(i: number): string {
  return ['1st', '2nd', '3rd'][i] ?? `${i + 1}th`;
}

export const BacktestGridLeaderboard = memo(function BacktestGridLeaderboard() {
  const [grids, setGrids] = useState<GridMeta[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [payload, setPayload] = useState<GridPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingGrid, setLoadingGrid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>('sharpe');

  // List available grid files on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await backtestResultsAPI.listGrids();
        if (cancelled) {return;}
        setGrids(r.grids);
        if (r.grids.length > 0) {setSelected(r.grids[0].name);}
      } catch (e) {
        if (!cancelled) {setError(e instanceof Error ? e.message : 'Failed to load grids');}
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Load full payload when selection changes.
  useEffect(() => {
    if (!selected) {return;}
    let cancelled = false;
    setLoadingGrid(true);
    (async () => {
      try {
        const r = await backtestResultsAPI.loadGrid(selected);
        if (!cancelled) {setPayload(r);}
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load grid');
          setPayload(null);
        }
      } finally {
        if (!cancelled) {setLoadingGrid(false);}
      }
    })();
    return () => { cancelled = true; };
  }, [selected]);

  // Sorted entries + median baseline for delta calc.
  const { ranked, median } = useMemo(() => {
    if (!payload) {return { ranked: [] as Entry[], median: null as number | null };}
    const withStats = payload.entries.filter((e) => e.stats);
    const sorted = [...withStats].sort((a, b) => {
      const av = getMetric(a, sortKey) ?? -Infinity;
      const bv = getMetric(b, sortKey) ?? -Infinity;
      return bv - av;
    });
    // Median of the active sort metric — used as baseline for delta coloring.
    const values = withStats.map((e) => getMetric(e, sortKey)).filter((v): v is number => v !== null);
    values.sort((a, b) => a - b);
    const med = values.length ? values[Math.floor(values.length / 2)] : null;
    return { ranked: sorted, median: med };
  }, [payload, sortKey]);

  /* ── Empty / loading / error states ───────────────────────────────── */

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-th-muted py-8 justify-center">
        <Loader2 size={14} className="animate-spin" />
        Loading grid sweeps...
      </div>
    );
  }

  if (error && grids.length === 0) {
    return <div className="text-xs text-accent-red py-4">Error: {error}</div>;
  }

  if (grids.length === 0) {
    return (
      <div className="flex flex-col items-center text-center py-8 gap-3">
        <FlaskConical size={28} className="text-th-dim" />
        <div className="text-sm text-th-secondary font-medium">No parameter sweeps yet</div>
        <p className="text-[11px] text-th-muted max-w-xs leading-relaxed">
          Run a systematic search to identify optimal min_confidence /
          sl_atr_mult / target_rr combos:
        </p>
        <code className="text-[10px] text-accent-blue bg-dark-bg px-2 py-1 rounded border border-th-border font-mono">
          python run_backtest_grid.py --days 14
        </code>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Grid selector + sort control */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {grids.length > 1 ? (
          <select
            value={selected ?? ''}
            onChange={(e) => setSelected(e.target.value)}
            className="h-8 bg-dark-bg border border-th-border rounded-md px-2 text-xs text-th
                       focus:border-accent-blue/50 focus:outline-none"
            aria-label="Select grid sweep file"
          >
            {grids.map((g) => (
              <option key={g.name} value={g.name}>
                {g.name} ({g.combos} combos)
              </option>
            ))}
          </select>
        ) : (
          <div className="text-[11px] text-th-muted font-mono">
            {grids[0].name} · {grids[0].combos} combos
          </div>
        )}

        {/* Sort chips */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] uppercase tracking-wider text-th-dim font-medium mr-1">
            Sort
          </span>
          {SORT_OPTIONS.map((opt) => {
            const active = sortKey === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => setSortKey(opt.key)}
                className={`relative px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors
                            ${active ? 'text-th' : 'text-th-muted hover:text-th-secondary'}`}
              >
                {active && (
                  <motion.span
                    layoutId="grid-sort-pill"
                    className="absolute inset-0 rounded-md bg-dark-tertiary"
                    transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                  />
                )}
                <span className="relative">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Table */}
      <div className="relative">
        <AnimatePresence mode="wait">
          {loadingGrid ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-xs text-th-muted py-8 justify-center"
            >
              <Loader2 size={14} className="animate-spin" /> Loading sweep...
            </motion.div>
          ) : (
            <motion.div
              key={selected}
              variants={staggerContainer(0.02)}
              initial="hidden"
              animate="show"
              className="overflow-x-auto"
            >
              <table className="w-full text-[11px] font-mono tabular-nums">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-th-dim border-b border-th-border">
                    <th className="text-left py-2 px-2 font-medium">#</th>
                    <th className="text-right py-2 px-2 font-medium">min_conf</th>
                    <th className="text-right py-2 px-2 font-medium">sl_mult</th>
                    <th className="text-right py-2 px-2 font-medium">target_rr</th>
                    <th className="text-right py-2 px-2 font-medium">Trades</th>
                    <th className="text-right py-2 px-2 font-medium">WR</th>
                    <th className="text-right py-2 px-2 font-medium">PF</th>
                    <th className="text-right py-2 px-2 font-medium">Sharpe</th>
                    <th className="text-right py-2 px-2 font-medium">Return</th>
                    <th className="text-right py-2 px-2 font-medium">DD</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map((e, i) => {
                    const top = i < 3;
                    const activeMetric = getMetric(e, sortKey);
                    const deltaPositive = median !== null && activeMetric !== null
                      && activeMetric > median;
                    return (
                      <motion.tr
                        key={`${e.params.min_confidence}-${e.params.sl_atr_mult}-${e.params.target_rr}`}
                        variants={staggerItem}
                        className={`border-b border-th-border/50 transition-colors hover:bg-dark-surface/40
                                    ${top ? 'bg-accent-green/[0.03]' : ''}`}
                      >
                        <td className="py-2 px-2">
                          {top ? (
                            <span className="inline-flex items-center gap-1">
                              <Trophy
                                size={11}
                                className={i === 0 ? 'text-accent-orange' : i === 1 ? 'text-th-secondary' : 'text-accent-purple'}
                              />
                              <span className="text-[10px] text-th-dim">{rankOrdinal(i)}</span>
                            </span>
                          ) : (
                            <span className="text-th-dim">{i + 1}</span>
                          )}
                        </td>
                        <td className="text-right py-2 px-2 text-th-secondary">{e.params.min_confidence.toFixed(2)}</td>
                        <td className="text-right py-2 px-2 text-th-secondary">{e.params.sl_atr_mult.toFixed(1)}</td>
                        <td className="text-right py-2 px-2 text-th-secondary">{e.params.target_rr.toFixed(1)}</td>
                        <td className="text-right py-2 px-2 text-th">{e.stats?.total_trades ?? '—'}</td>
                        <td className="text-right py-2 px-2 text-th">
                          {e.stats?.win_rate_pct !== undefined && e.stats?.win_rate_pct !== null
                            ? `${Number(e.stats.win_rate_pct).toFixed(0)}%`
                            : '—'}
                        </td>
                        <td className="text-right py-2 px-2 text-th">
                          {typeof e.stats?.profit_factor === 'number'
                            ? e.stats.profit_factor.toFixed(2)
                            : (e.stats?.profit_factor ?? '—')}
                        </td>
                        <td className={`text-right py-2 px-2 font-semibold
                                        ${sortKey === 'sharpe'
                                          ? (deltaPositive ? 'text-accent-green' : 'text-accent-red')
                                          : 'text-th'}`}>
                          {e.stats?.sharpe !== undefined && e.stats?.sharpe !== null
                            ? Number(e.stats.sharpe).toFixed(2)
                            : '—'}
                        </td>
                        <td className={`text-right py-2 px-2 font-semibold
                                        ${e.stats?.return_pct !== undefined && e.stats?.return_pct !== null
                                          ? (Number(e.stats.return_pct) >= 0 ? 'text-accent-green' : 'text-accent-red')
                                          : 'text-th-dim'}`}>
                          {e.stats?.return_pct !== undefined && e.stats?.return_pct !== null
                            ? `${Number(e.stats.return_pct).toFixed(1)}%`
                            : '—'}
                        </td>
                        <td className="text-right py-2 px-2 text-th-muted">
                          {e.stats?.max_drawdown_pct !== undefined && e.stats?.max_drawdown_pct !== null
                            ? `${Number(e.stats.max_drawdown_pct).toFixed(1)}%`
                            : '—'}
                        </td>
                      </motion.tr>
                    );
                  })}
                </tbody>
              </table>
              {ranked.length === 0 && (
                <div className="text-xs text-th-muted text-center py-6">
                  No completed runs in this sweep.
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Footer hint */}
      {ranked.length > 0 && median !== null && (
        <div className="text-[10px] text-th-dim">
          Median {SORT_OPTIONS.find((o) => o.key === sortKey)?.label} across this sweep:
          <span className="font-mono ml-1 text-th-muted">
            {SORT_OPTIONS.find((o) => o.key === sortKey)?.fmt(median)}
          </span>
        </div>
      )}
    </div>
  );
});
