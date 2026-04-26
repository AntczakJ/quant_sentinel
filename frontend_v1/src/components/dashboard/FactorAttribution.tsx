/**
 * FactorAttribution.tsx — observability layer for scoring boosters.
 *
 * Two-panel widget:
 *   1. Factor leaderboard — for each factor that fired in trades over the
 *      window, show n, WR%, total pnl, pnl/trade. Sorted by sample size.
 *      Validates "is asia_orb actually helping?" without manual SQL.
 *   2. Recent trades — last N resolved trades with full factor list,
 *      grade, score, pnl. Inline pill chips for each factor.
 *
 * Built for Monday post-deployment review of all 2026-04-24 changes
 * (Asia ORB, VWAP confluence, post-news second rotation, regime routing).
 */

import { useEffect, useState, memo } from 'react';
import { motion } from 'motion/react';
import {
  TrendingUp, TrendingDown, Activity, ListChecks, Loader2,
} from 'lucide-react';
import {
  scannerAPI,
  type FactorsAttributionResponse,
  type FactorSummaryRow,
  type RecentTradeRow,
} from '../../api/client';

function fmtFactorName(name: string): string {
  // Friendlier display: replace _ with space, title-case
  return name
    .split('_')
    .map((s) => (s.length <= 3 ? s.toUpperCase() : s[0]?.toUpperCase() + s.slice(1)))
    .join(' ');
}

function FactorBar({ row, max }: { row: FactorSummaryRow; max: number }) {
  const widthPct = max > 0 ? (row.n / max) * 100 : 0;
  const wrTone =
    row.win_rate_pct >= 55 ? 'text-accent-green'
      : row.win_rate_pct <= 35 ? 'text-accent-red'
      : 'text-th-secondary';
  const pnlPositive = row.pnl_total > 0;
  return (
    <div className="group">
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="t-mono font-medium" style={{ color: 'var(--color-text-primary)' }}>
          {fmtFactorName(row.factor)}
        </span>
        <div className="flex items-center gap-3 text-[11px]">
          <span style={{ color: 'var(--color-text-muted)' }}>
            n=<span className="t-mono">{row.n}</span>
          </span>
          <span className={`t-mono font-semibold ${wrTone}`}>
            {row.win_rate_pct.toFixed(0)}%
          </span>
          <span
            className={`t-mono font-semibold ${pnlPositive ? 'text-accent-green' : 'text-accent-red'}`}
          >
            {pnlPositive ? '+' : ''}${row.pnl_total.toFixed(0)}
          </span>
        </div>
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden"
        style={{ background: 'var(--color-secondary)' }}
      >
        <div
          className="h-full transition-all duration-500"
          style={{
            width: `${widthPct}%`,
            background:
              row.win_rate_pct >= 50
                ? 'linear-gradient(90deg, rgb(var(--c-green)), rgb(var(--c-green) / 0.6))'
                : 'linear-gradient(90deg, rgb(var(--c-red)), rgb(var(--c-red) / 0.6))',
          }}
        />
      </div>
    </div>
  );
}

function TradeRow({ trade }: { trade: RecentTradeRow }) {
  const isWin = trade.status === 'WIN';
  const pnlTone = isWin ? 'text-accent-green' : 'text-accent-red';
  const factorEntries = Object.entries(trade.factors).filter(([, v]) => v);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="surface p-3 space-y-2"
      style={{ background: 'var(--color-secondary)', borderRadius: 'var(--radius-xl)' }}
    >
      <div className="flex items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`pill ${trade.direction === 'LONG' ? 'pill-good' : 'pill-bad'}`}
          >
            {trade.direction === 'LONG' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {trade.direction}
          </span>
          <span
            className="t-mono text-[11px]"
            style={{ color: 'var(--color-text-muted)' }}
          >
            #{trade.id}
          </span>
          {trade.setup_grade && (
            <span className="pill pill-accent">{trade.setup_grade}</span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {trade.setup_score !== null && (
            <span
              className="t-mono text-[11px]"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {trade.setup_score.toFixed(0)}/100
            </span>
          )}
          <span className={`t-mono text-[12px] font-semibold ${pnlTone}`}>
            {trade.profit > 0 ? '+' : ''}${trade.profit.toFixed(2)}
          </span>
        </div>
      </div>

      {factorEntries.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {factorEntries.map(([name, value]) => {
            const isPenalty = name.endsWith('_penalty');
            return (
              <span
                key={name}
                className={`pill ${isPenalty ? 'pill-warn' : ''}`}
                style={{ fontSize: 10 }}
                title={`${name}: ${value}`}
              >
                {fmtFactorName(name)}
                {typeof value === 'number' && value !== 1 && (
                  <span className="opacity-60">
                    {value > 0 ? '+' : ''}{value}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {trade.pattern && (
        <div
          className="text-[10px]"
          style={{ color: 'var(--color-text-dim)' }}
        >
          {trade.pattern}
          {trade.timestamp && ` · ${trade.timestamp}`}
        </div>
      )}
    </motion.div>
  );
}

function FactorAttributionInner() {
  const [data, setData] = useState<FactorsAttributionResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await scannerAPI.getFactorsAttribution(30, 10);
        if (alive) {
          setData(d);
          setErr(null);
        }
      } catch (e) {
        if (alive) {
          setErr(e instanceof Error ? e.message : 'Failed');
        }
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    };
    void load();
    const id = window.setInterval(load, 60_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (loading && !data) {
    return (
      <div className="card-elevated">
        <div className="flex items-center gap-2 mb-3">
          <ListChecks size={16} style={{ color: 'rgb(var(--c-accent))' }} />
          <h2 className="t-h3">Factor Attribution</h2>
        </div>
        <div
          className="flex items-center gap-2 text-sm"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      </div>
    );
  }

  if (err || !data) {
    return (
      <div className="card-elevated">
        <h2 className="t-h3">Factor Attribution</h2>
        <div className="text-sm text-accent-red mt-2">Error: {err || 'no data'}</div>
      </div>
    );
  }

  const maxN = Math.max(...data.factors_summary.map((r) => r.n), 1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="t-eyebrow mb-1">Observability</div>
          <h2 className="t-h2">Factor Attribution</h2>
          <p
            className="t-caption mt-1"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Which scoring boosters drive WIN vs LOSS · last {data.window_days}d ·{' '}
            {data.total_resolved} resolved trades
          </p>
        </div>
      </div>

      {/* Two-column on desktop */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 lg:gap-8">
        {/* Factor leaderboard */}
        <section className="hero-card">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={14} style={{ color: 'rgb(var(--c-accent))' }} />
            <h3 className="t-h3">Per-factor performance</h3>
          </div>
          {data.factors_summary.length === 0 ? (
            <div
              className="text-sm italic"
              style={{ color: 'var(--color-text-muted)' }}
            >
              No factor data yet — needs resolved trades with factors logged.
              Wait for Monday open.
            </div>
          ) : (
            <div className="space-y-3 reveal-stagger">
              {data.factors_summary.slice(0, 10).map((r) => (
                <FactorBar key={r.factor} row={r} max={maxN} />
              ))}
            </div>
          )}
        </section>

        {/* Recent trades */}
        <section className="hero-card">
          <div className="flex items-center gap-2 mb-4">
            <ListChecks size={14} style={{ color: 'rgb(var(--c-accent))' }} />
            <h3 className="t-h3">Recent trades</h3>
          </div>
          {data.recent_trades.length === 0 ? (
            <div
              className="text-sm italic"
              style={{ color: 'var(--color-text-muted)' }}
            >
              No resolved trades in window.
            </div>
          ) : (
            <div className="space-y-2 reveal-stagger">
              {data.recent_trades.map((t) => (
                <TradeRow key={t.id} trade={t} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export const FactorAttribution = memo(FactorAttributionInner);
