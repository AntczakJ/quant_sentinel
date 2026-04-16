import { useEffect, useState, memo } from 'react';
import {
  Loader2, CheckCircle, AlertTriangle, Activity, Briefcase,
  TrendingUp, TrendingDown, Clock, Zap,
} from 'lucide-react';
import { backtestResultsAPI, type SystemHealthResponse } from '../../api/client';

function fmtAge(sec: number | null): string {
  if (sec === null || sec === undefined) { return '—'; }
  if (sec < 60) { return `${Math.round(sec)}s`; }
  if (sec < 3600) { return `${Math.round(sec / 60)}m`; }
  if (sec < 86400) { return `${Math.round(sec / 3600)}h`; }
  return `${Math.round(sec / 86400)}d`;
}

function fmtMoney(n: number): string {
  const s = Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
  return `${n > 0 ? '+' : ''}$${s}`;
}

function Card({ icon: Icon, label, value, tone = 'neutral', hint }: {
  icon: typeof Activity;
  label: string;
  value: string;
  tone?: 'good' | 'warn' | 'bad' | 'neutral';
  hint?: string;
}) {
  const toneCls = {
    good: 'text-accent-green',
    warn: 'text-accent-orange',
    bad: 'text-accent-red',
    neutral: 'text-th-primary',
  }[tone];
  return (
    <div className="bg-dark-bg rounded p-2 border border-dark-secondary">
      <div className="flex items-center gap-1.5 text-[10px] text-th-muted uppercase tracking-wider mb-1">
        <Icon size={10} />
        <span>{label}</span>
      </div>
      <div className={`font-mono text-lg font-medium ${toneCls}`}>{value}</div>
      {hint && <div className="text-[10px] text-th-muted mt-0.5">{hint}</div>}
    </div>
  );
}

function SystemHealthInner() {
  const [data, setData] = useState<SystemHealthResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await backtestResultsAPI.loadSystemHealth();
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) { setErr(e instanceof Error ? e.message : 'Failed'); }
      } finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const t = setInterval(() => { void load(); }, 20_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-20 text-th-muted">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }
  if (err) { return <div className="text-xs text-accent-red">Error: {err}</div>; }
  if (!data) { return null; }

  const overallStyle = data.overall === 'healthy'
    ? { icon: CheckCircle, cls: 'bg-accent-green/15 border-accent-green/30 text-accent-green', label: 'All systems healthy' }
    : { icon: AlertTriangle, cls: 'bg-accent-orange/15 border-accent-orange/30 text-accent-orange', label: `Issues: ${data.issues.join(', ')}` };
  const OIcon = overallStyle.icon;

  const lstmTone = data.lstm.verdict === 'degenerate' ? 'bad'
    : data.lstm.verdict === 'concerning' ? 'warn'
    : data.lstm.verdict === 'healthy' ? 'good' : 'neutral';

  const heatTone = data.trades.heat_pct > 6 ? 'bad'
    : data.trades.heat_pct > 3 ? 'warn' : 'good';

  const pnl24Tone = data.trades.pnl_24h > 0 ? 'good'
    : data.trades.pnl_24h < 0 ? 'bad' : 'neutral';

  const pnl7Tone = data.trades.pnl_7d > 0 ? 'good'
    : data.trades.pnl_7d < 0 ? 'bad' : 'neutral';

  const driftTone = data.drift_alerts.alert > 10 ? 'bad'
    : data.drift_alerts.alert > 3 ? 'warn' : 'good';

  const scannerTone = !data.scanner.last_rejection_age_sec || data.scanner.last_rejection_age_sec > 3600
    ? 'bad' : 'good';

  return (
    <div className="space-y-2">
      <div className={`p-2 rounded border text-xs flex items-center gap-2 ${overallStyle.cls}`}>
        <OIcon size={14} />
        <span className="font-medium">{overallStyle.label}</span>
        <span className="text-th-muted ml-auto text-[10px]">balance ${data.portfolio_balance.toFixed(0)}</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Card
          icon={Activity}
          label="LSTM verdict"
          value={data.lstm.verdict}
          tone={lstmTone}
          hint={data.lstm.n_predictions != null ? `n=${data.lstm.n_predictions}, mid=${((data.lstm.middle_frac ?? 0) * 100).toFixed(0)}%` : undefined}
        />
        <Card
          icon={AlertTriangle}
          label="Drift alerts"
          value={`${data.drift_alerts.alert}+${data.drift_alerts.warn}`}
          tone={driftTone}
          hint={`${data.drift_alerts.total} unresolved`}
        />
        <Card
          icon={Briefcase}
          label="Open / heat"
          value={`${data.trades.open} · ${data.trades.heat_pct.toFixed(1)}%`}
          tone={heatTone}
          hint={`risk $${data.trades.total_risk_usd.toFixed(0)}`}
        />
        <Card
          icon={Zap}
          label="Scanner"
          value={data.scanner.last_rejection_age_sec != null
            ? fmtAge(data.scanner.last_rejection_age_sec) + ' ago'
            : 'silent'}
          tone={scannerTone}
          hint={`signal ${fmtAge(data.scanner.last_signal_age_sec)} ago`}
        />
        <Card
          icon={data.trades.pnl_24h >= 0 ? TrendingUp : TrendingDown}
          label="PnL 24h"
          value={fmtMoney(data.trades.pnl_24h)}
          tone={pnl24Tone}
          hint={`${data.trades.trades_24h} trades`}
        />
        <Card
          icon={data.trades.pnl_7d >= 0 ? TrendingUp : TrendingDown}
          label="PnL 7d"
          value={fmtMoney(data.trades.pnl_7d)}
          tone={pnl7Tone}
          hint={`${data.trades.trades_7d} trades`}
        />
        <Card
          icon={Clock}
          label="Last sig"
          value={fmtAge(data.scanner.last_signal_age_sec)}
          tone="neutral"
          hint="since confirmed"
        />
        <Card
          icon={CheckCircle}
          label="Issues"
          value={data.issues.length === 0 ? 'none' : String(data.issues.length)}
          tone={data.issues.length === 0 ? 'good' : 'warn'}
          hint={data.issues[0] || 'all clear'}
        />
      </div>
      {data.trades.open_detail.length > 0 && (
        <div className="mt-1 bg-dark-bg rounded p-2 border border-dark-secondary">
          <div className="text-[10px] text-th-muted uppercase tracking-wider mb-1.5">
            Open positions ({data.trades.open_detail.length})
          </div>
          <div className="space-y-1">
            {data.trades.open_detail.map((t) => (
              <div key={t.id} className="flex items-center gap-3 text-[11px] font-mono">
                <span className="text-th-muted">#{t.id}</span>
                <span className={t.direction === 'LONG' ? 'text-accent-green' : 'text-accent-red'}>
                  {t.direction}
                </span>
                <span>${t.entry.toFixed(2)}</span>
                <span className="text-th-muted">→</span>
                <span className="text-accent-red">SL ${t.sl.toFixed(2)}</span>
                <span className="text-accent-green">TP ${t.tp.toFixed(2)}</span>
                <span className="text-th-muted">lot {t.lot}</span>
                <span className="text-th-muted ml-auto">risk ${t.risk_usd.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="text-[10px] text-th-muted">Auto-refresh 20s</div>
    </div>
  );
}

export const SystemHealth = memo(SystemHealthInner);
