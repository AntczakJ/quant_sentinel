import { useEffect, useState, memo } from 'react';
import { Loader2, Search, ThumbsUp, ThumbsDown, HelpCircle } from 'lucide-react';
import { backtestResultsAPI, type ReplayAnalyzerResponse, type ReplayFilterEntry } from '../../api/client';

const VERDICT_STYLE = {
  should_accept: { cls: 'bg-accent-red/15 text-accent-red', icon: ThumbsDown, label: 'RELAX FILTER' },
  correct_reject: { cls: 'bg-accent-green/15 text-accent-green', icon: ThumbsUp, label: 'OK' },
  borderline: { cls: 'bg-accent-orange/15 text-accent-orange', icon: HelpCircle, label: 'BORDERLINE' },
  insufficient: { cls: 'bg-dark-bg text-th-muted', icon: HelpCircle, label: 'N/A' },
} as const;

function Row({ f }: { f: ReplayFilterEntry }) {
  const s = VERDICT_STYLE[f.verdict];
  const Icon = s.icon;
  return (
    <tr>
      <td className="py-1.5 px-2 font-medium">{f.name}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px]">
        {f.rejected} <span className="text-th-muted">({f.share_pct}%)</span>
      </td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px]">
        {f.hypothetical_wr_pct !== null ? `${f.hypothetical_wr_pct}%` : '—'}
      </td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px]">
        {f.expectancy_pct !== null
          ? <span className={f.expectancy_pct > 0 ? 'text-accent-green' : 'text-accent-red'}>
              {f.expectancy_pct > 0 ? '+' : ''}{f.expectancy_pct.toFixed(3)}%
            </span>
          : '—'}
      </td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px] text-th-muted">{f.sample_size}</td>
      <td className={`py-1.5 px-2 text-right text-[10px] ${s.cls} rounded`}>
        <Icon size={10} className="inline mr-0.5" />
        {s.label}
      </td>
    </tr>
  );
}

function ReplayAnalyzerInner() {
  const [data, setData] = useState<ReplayAnalyzerResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hours, setHours] = useState(24);
  const horizon = 24;  // fixed 2h horizon for now; add selector later if needed

  useEffect(() => {
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const d = await backtestResultsAPI.loadReplayAnalyzer(hours, horizon);
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) { setErr(e instanceof Error ? e.message : 'Failed'); }
      } finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const t = setInterval(() => { void load(); }, 60_000);
    return () => { alive = false; clearInterval(t); };
  }, [hours, horizon]);

  if (loading && !data) {
    return <div className="flex items-center justify-center h-20 text-th-muted">
      <Loader2 size={14} className="animate-spin mr-2" /> Running what-if...
    </div>;
  }
  if (err) { return <div className="text-xs text-accent-red">Error: {err}</div>; }
  if (!data) { return null; }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs text-th-muted">
          <Search size={12} />
          <span>{data.total_rejected} rejects over {data.hours}h · horizon {data.horizon_label}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-th-muted mr-1">window:</span>
          {[6, 24, 72, 168].map(h => (
            <button key={h} onClick={() => setHours(h)}
              className={`text-[10px] px-2 py-0.5 rounded ${hours === h ? 'bg-accent-cyan text-black' : 'bg-dark-bg text-th-muted'}`}>
              {h < 24 ? `${h}h` : h < 168 ? `${h/24}d` : `${h/24}d`}
            </button>
          ))}
          <span className="text-[10px] text-th-muted ml-2">{data.cached ? `cached ${data.cache_age_sec.toFixed(0)}s` : 'fresh'}</span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] text-th-muted uppercase tracking-wider border-b border-dark-secondary">
            <tr>
              <th className="py-1.5 px-2 text-left">Filter</th>
              <th className="py-1.5 px-2 text-right">Rejected</th>
              <th className="py-1.5 px-2 text-right">Hyp. WR</th>
              <th className="py-1.5 px-2 text-right">Expectancy</th>
              <th className="py-1.5 px-2 text-right">Samples</th>
              <th className="py-1.5 px-2 text-right">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {data.filters.map(f => <Row key={f.name} f={f} />)}
          </tbody>
        </table>
      </div>

      <div className="text-[10px] text-th-muted">
        Hypothetical: if we'd taken the trade at rejection, would it have hit ±{data.target_pct}% within {data.horizon_label}?
        Verdict RELAX FILTER = hypothetical WR&gt;55% AND positive expectancy.
      </div>
    </div>
  );
}

export const ReplayAnalyzer = memo(ReplayAnalyzerInner);
