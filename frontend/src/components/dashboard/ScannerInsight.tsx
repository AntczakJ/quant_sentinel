/**
 * ScannerInsight.tsx — Why is the scanner (not) trading?
 *
 * Single-panel answer to "dlaczego 0 trejdów". Surfaces the four things
 * an operator actually needs to see: rejection breakdown (top filters
 * blocking setups), toxic pattern status (which patterns are in cool-down
 * and when they re-evaluate), consecutive-loss streak (vs auto-pause
 * threshold), and Kelly reset state (is sizing using default or post-reset
 * live data).
 */

import { useEffect, useState, memo } from 'react';
import {
  AlertTriangle, Ban, Activity, Info, Pause,
  TrendingDown, Clock, DollarSign,
} from 'lucide-react';
import { scannerAPI, type ScannerInsightResponse } from '../../api/client';

function Tone({ value, children, tone }: {
  value: string | number;
  children?: React.ReactNode;
  tone: 'good' | 'warn' | 'bad' | 'neutral';
}) {
  const cls = {
    good: 'text-accent-green',
    warn: 'text-accent-orange',
    bad: 'text-accent-red',
    neutral: 'text-th-primary',
  }[tone];
  return (
    <span className={`font-mono font-medium ${cls}`}>
      {value}
      {children}
    </span>
  );
}

function RejectionsSection({ data }: { data: ScannerInsightResponse['rejections'] }) {
  const maxCount = Math.max(...data.top.map((r) => r.count), 1);
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-[10px] text-th-muted uppercase tracking-wider">
          <Ban size={11} />
          <span>Rejections (24h)</span>
        </div>
        <span className="font-mono text-xs text-th-muted">
          total: <Tone value={data.total} tone="neutral" />
        </span>
      </div>
      {data.top.length === 0 ? (
        <div className="text-xs text-th-muted italic">No rejections logged.</div>
      ) : (
        <div className="space-y-1">
          {data.top.slice(0, 6).map((r) => {
            const pct = (r.count / maxCount) * 100;
            return (
              <div key={r.filter} className="group">
                <div className="flex items-center justify-between text-xs mb-0.5">
                  <span className="text-th-primary font-medium">{r.filter}</span>
                  <span className="font-mono text-th-muted">
                    {r.count}{' '}
                    <span className="text-[10px]">
                      ({((r.count / data.total) * 100).toFixed(0)}%)
                    </span>
                  </span>
                </div>
                <div className="h-1.5 bg-dark-bg rounded overflow-hidden">
                  <div
                    className="h-full bg-accent-orange/60 group-hover:bg-accent-orange transition-colors"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToxicPatternsSection({ data }: { data: ScannerInsightResponse['toxic_patterns'] }) {
  // Show only patterns with meaningful data (n >= 5) OR currently blocked
  const visible = data.filter((p) => p.n >= 5 || p.blocked).slice(0, 5);
  if (visible.length === 0) {
    return null;
  }
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[10px] text-th-muted uppercase tracking-wider mb-2">
        <AlertTriangle size={11} />
        <span>Toxic Pattern Watch</span>
      </div>
      <div className="space-y-1.5">
        {visible.map((p) => {
          const wrPct = (p.win_rate * 100).toFixed(0);
          const tone: 'good' | 'warn' | 'bad' | 'neutral' = p.blocked
            ? 'bad'
            : p.win_rate < 0.3 && p.n >= 10
              ? 'warn'
              : 'neutral';
          return (
            <div key={p.pattern} className="text-xs">
              <div className="flex items-center justify-between">
                <span className="text-th-primary truncate" title={p.pattern}>
                  {p.pattern}
                </span>
                <Tone
                  tone={tone}
                  value={`${p.wins}W/${p.losses}L`}
                >
                  {' '}
                  <span className="text-th-muted text-[10px]">
                    {wrPct}%
                  </span>
                </Tone>
              </div>
              <div className="text-[10px] text-th-muted mt-0.5">
                {p.blocked ? (
                  <span className="text-accent-red">BLOCKED (WR &lt; 30%, n≥20)</span>
                ) : p.n >= p.n_threshold ? (
                  <span>
                    sample full (n={p.n}/{p.n_threshold}) — WR above block threshold
                  </span>
                ) : (
                  <span>
                    sample: {p.n}/{p.n_threshold} — {p.until_re_evaluate} more trades to re-evaluate
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StreakSection({ streak }: { streak: ScannerInsightResponse['streak'] }) {
  const lossesDisplay = `${streak.consecutive_losses}/${streak.threshold}`;
  const tone: 'good' | 'warn' | 'bad' = streak.would_auto_pause
    ? 'bad'
    : streak.consecutive_losses >= 3
      ? 'warn'
      : 'good';
  return (
    <div className="flex items-center justify-between bg-dark-bg rounded p-2">
      <div className="flex items-center gap-2">
        <TrendingDown
          size={14}
          className={
            tone === 'bad'
              ? 'text-accent-red'
              : tone === 'warn'
                ? 'text-accent-orange'
                : 'text-accent-green'
          }
        />
        <div>
          <div className="text-[10px] text-th-muted uppercase tracking-wider">
            Consecutive losses
          </div>
          <Tone value={lossesDisplay} tone={tone} />
        </div>
      </div>
      <div className="text-right">
        <div className="text-[10px] text-th-muted uppercase tracking-wider">Oldest age</div>
        <div className="font-mono text-xs text-th-primary">
          {streak.oldest_loss_age_hours !== null
            ? `${streak.oldest_loss_age_hours.toFixed(1)}h`
            : '—'}
          <span className="text-th-muted text-[10px]"> / {streak.recency_hours}h window</span>
        </div>
      </div>
    </div>
  );
}

function KellySection({ kelly }: { kelly: ScannerInsightResponse['kelly'] }) {
  const sampleDisplay = `${kelly.post_reset_trades}/${kelly.min_sample}`;
  const tone = kelly.using_default_risk ? 'warn' : 'good';
  return (
    <div className="flex items-center justify-between bg-dark-bg rounded p-2">
      <div className="flex items-center gap-2">
        <DollarSign
          size={14}
          className={
            tone === 'warn' ? 'text-accent-orange' : 'text-accent-green'
          }
        />
        <div>
          <div className="text-[10px] text-th-muted uppercase tracking-wider">Kelly sample</div>
          <Tone value={sampleDisplay} tone={tone} />
        </div>
      </div>
      <div className="text-right">
        <div className="text-[10px] text-th-muted uppercase tracking-wider">Mode</div>
        <div className="font-mono text-xs text-th-primary">
          {kelly.using_default_risk ? 'DEFAULT risk 1.0%' : 'LIVE sizing'}
        </div>
      </div>
    </div>
  );
}

function ScannerInsightInner() {
  const [data, setData] = useState<ScannerInsightResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await scannerAPI.getInsight(24);
        if (alive) {
          setData(d);
          setErr(null);
        }
      } catch (e) {
        if (alive) {
          setErr(e instanceof Error ? e.message : 'Failed to load insight');
        }
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    };
    void load();
    const id = window.setInterval(load, 30000); // refresh every 30s
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (loading && !data) {
    return (
      <div className="card-elevated">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-1 h-4 rounded-full bg-accent-orange" />
          <h2 className="section-title mb-0">Scanner Insight</h2>
        </div>
        <div className="text-sm text-th-muted animate-pulse">Loading…</div>
      </div>
    );
  }
  if (err || !data) {
    return (
      <div className="card-elevated">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-1 h-4 rounded-full bg-accent-red" />
          <h2 className="section-title mb-0">Scanner Insight</h2>
        </div>
        <div className="text-sm text-accent-red">Error: {err || 'no data'}</div>
      </div>
    );
  }

  return (
    <div className="card-elevated">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className={`w-1 h-4 rounded-full ${
              data.paused ? 'bg-accent-red' : 'bg-accent-orange'
            }`}
          />
          <h2 className="section-title mb-0">Why scanner is (not) trading</h2>
        </div>
        {data.paused && (
          <span className="flex items-center gap-1 text-[11px] font-medium text-accent-red">
            <Pause size={11} /> PAUSED
          </span>
        )}
      </div>

      {data.paused && data.pause_reason && (
        <div className="mb-3 p-2 bg-accent-red/10 rounded border border-accent-red/30 text-[11px] text-accent-red">
          <div className="flex items-center gap-1.5 mb-0.5">
            <Info size={11} />
            <span className="font-medium">Pause reason</span>
          </div>
          <div className="font-mono break-words">{data.pause_reason}</div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="bg-dark-bg-soft rounded p-3">
          <RejectionsSection data={data.rejections} />
        </div>
        <div className="bg-dark-bg-soft rounded p-3">
          <ToxicPatternsSection data={data.toxic_patterns} />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">
        <StreakSection streak={data.streak} />
        <KellySection kelly={data.kelly} />
      </div>

      <div className="flex items-center justify-between mt-3 text-[10px] text-th-muted">
        <div className="flex items-center gap-1">
          <Clock size={10} />
          <span>Auto-refresh every 30s</span>
        </div>
        <div className="flex items-center gap-1">
          <Activity size={10} />
          <span>
            Window: last {data.hours_window}h
          </span>
        </div>
      </div>
    </div>
  );
}

export const ScannerInsight = memo(ScannerInsightInner);
