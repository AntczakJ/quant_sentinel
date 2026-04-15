import { useEffect, useState, memo } from 'react';
import { Loader2, AlertTriangle, CheckCircle, AlertCircle } from 'lucide-react';
import { modelsAPI, type LSTMDistributionResponse, type LSTMHistogramStats } from '../../api/client';

const VERDICT_STYLES = {
  healthy: {
    icon: CheckCircle,
    label: 'Healthy distribution',
    cls: 'bg-accent-green/15 border-accent-green/30 text-accent-green',
  },
  concerning: {
    icon: AlertCircle,
    label: 'Conviction spike vs. pre-swap',
    cls: 'bg-accent-orange/15 border-accent-orange/30 text-accent-orange',
  },
  degenerate: {
    icon: AlertTriangle,
    label: 'Bimodal / degenerate output',
    cls: 'bg-accent-red/15 border-accent-red/30 text-accent-red',
  },
} as const;

function Bars({ hist, color }: { hist: number[]; color: string }) {
  const max = Math.max(1, ...hist);
  return (
    <div className="flex items-end gap-[1px] h-16">
      {hist.map((count, i) => {
        const pct = (count / max) * 100;
        const v = i / hist.length;
        const extreme = v < 0.1 || v > 0.9;
        return (
          <div
            key={i}
            className="flex-1 relative rounded-t"
            style={{
              height: `${Math.max(pct, 2)}%`,
              backgroundColor: color,
              opacity: extreme ? 1 : 0.55,
            }}
            title={`bin ${v.toFixed(2)}-${((i + 1) / hist.length).toFixed(2)}: ${count}`}
          />
        );
      })}
    </div>
  );
}

function StatBlock({ label, stats, color }: { label: string; stats: LSTMHistogramStats; color: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <div className="text-xs text-th-muted uppercase tracking-wider font-medium">{label}</div>
        <div className="text-[10px] text-th-muted font-mono">n={stats.n}</div>
      </div>
      <Bars hist={stats.histogram} color={color} />
      <div className="flex justify-between text-[10px] text-th-muted font-mono mt-0.5">
        <span>0.0</span>
        <span>0.5</span>
        <span>1.0</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-[11px] mt-2">
        <div>
          <div className="text-th-muted">conviction</div>
          <div className="font-mono text-th-primary">{stats.conviction?.toFixed(3) ?? '—'}</div>
        </div>
        <div>
          <div className="text-th-muted">|p-0.5|&gt;0.4</div>
          <div className="font-mono text-th-primary">
            {stats.extreme_frac != null ? `${(stats.extreme_frac * 100).toFixed(1)}%` : '—'}
          </div>
        </div>
        <div>
          <div className="text-th-muted">middle</div>
          <div className="font-mono text-th-primary">
            {stats.middle_frac != null ? `${(stats.middle_frac * 100).toFixed(1)}%` : '—'}
          </div>
        </div>
      </div>
    </div>
  );
}

function LSTMDistributionInner() {
  const [data, setData] = useState<LSTMDistributionResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await modelsAPI.getLSTMDistribution(48);
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) { setErr(e instanceof Error ? e.message : 'Failed to load'); }
      } finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const t = setInterval(() => { void load(); }, 30_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-32 text-th-muted">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading distribution...
      </div>
    );
  }
  if (err) {
    return <div className="text-xs text-accent-red">Error: {err}</div>;
  }
  if (!data) { return null; }

  const v = VERDICT_STYLES[data.verdict];
  const VIcon = v.icon;

  return (
    <div className="space-y-3">
      <div className={`p-2 rounded border text-xs flex items-center gap-2 ${v.cls}`}>
        <VIcon size={14} />
        <span className="font-medium">{v.label}</span>
        <span className="text-th-muted ml-auto">swap: {data.swap_timestamp.slice(0, 10)}</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <StatBlock
          label="Post-swap (current LSTM)"
          stats={data.post_swap}
          color={data.verdict === 'degenerate' ? '#ef4444' : data.verdict === 'concerning' ? '#f59e0b' : '#22c55e'}
        />
        <StatBlock
          label="Pre-swap reference"
          stats={data.pre_swap_reference}
          color="#64748b"
        />
      </div>
      <div className="text-[10px] text-th-muted">
        Degenerate = extreme&gt;70% AND middle&lt;15%. Concerning = post conviction &gt;3× pre.
      </div>
    </div>
  );
}

export const LSTMDistribution = memo(LSTMDistributionInner);
