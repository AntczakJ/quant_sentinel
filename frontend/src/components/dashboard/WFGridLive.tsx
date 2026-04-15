import { useEffect, useState, memo } from 'react';
import { Loader2, FlaskConical, TrendingUp, Trophy } from 'lucide-react';
import { backtestResultsAPI, type WFGridLiveResponse, type WFGridLiveEntry } from '../../api/client';

function fmt(n: number | null | undefined, digits = 2, suffix = ''): string {
  if (n === null || n === undefined || !Number.isFinite(n)) { return '—'; }
  return `${n.toFixed(digits)}${suffix}`;
}

function Row({ entry, rank }: { entry: WFGridLiveEntry; rank: number }) {
  const p = entry.params;
  const isTop3 = rank <= 3;
  return (
    <tr className={isTop3 ? 'bg-accent-green/5' : ''}>
      <td className="py-1.5 px-2 text-center">
        <div className="flex items-center gap-1">
          {isTop3 && <Trophy size={10} className={rank === 1 ? 'text-yellow-400' : rank === 2 ? 'text-gray-300' : 'text-amber-700'} />}
          <span className="font-mono text-[11px]">{rank}</span>
          {entry.on_pareto_front && <span className="text-[8px] bg-accent-purple/30 text-accent-purple px-1 rounded" title="Pareto-optimal">P</span>}
        </div>
      </td>
      <td className="py-1.5 px-2 font-mono text-[10px] text-th-muted">{entry.cell_hash?.slice(0, 8)}</td>
      <td className="py-1.5 px-1 text-center font-mono text-[11px]">{p.min_confidence}</td>
      <td className="py-1.5 px-1 text-center font-mono text-[11px]">{p.sl_atr_mult}</td>
      <td className="py-1.5 px-1 text-center font-mono text-[11px]">{p.target_rr}</td>
      <td className="py-1.5 px-1 text-center font-mono text-[11px]">{p.partial_close ? '✓' : '–'}</td>
      <td className="py-1.5 px-1 text-center font-mono text-[11px]">{p.risk_percent}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px] text-accent-green">{fmt(entry.sharpe)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px]">{fmt(entry.profit_factor)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px]">{fmt(entry.return_pct, 1, '%')}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px] text-accent-red">{fmt(entry.max_drawdown_pct, 1, '%')}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px] text-th-muted">{entry.total_trades != null ? entry.total_trades.toFixed(0) : '—'}</td>
      <td className="py-1.5 px-2 text-right font-mono text-[11px] font-bold">{fmt(entry.composite)}</td>
    </tr>
  );
}

function WFGridLiveInner() {
  const [data, setData] = useState<WFGridLiveResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await backtestResultsAPI.loadWFGridLive('prod_v1', 'A', 5);
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
        <Loader2 size={16} className="animate-spin mr-2" /> Loading live grid...
      </div>
    );
  }
  if (err) { return <div className="text-xs text-accent-red">Error: {err}</div>; }
  if (!data) { return null; }

  const progressPct = data.expected_total ? (data.completed / data.expected_total) * 100 : 0;
  const isRunning = data.expected_total ? data.completed < data.expected_total : false;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FlaskConical size={14} className={isRunning ? 'text-accent-cyan animate-pulse' : 'text-accent-green'} />
          <div>
            <div className="text-xs font-medium">Stage {data.stage}: {data.name}</div>
            <div className="text-[10px] text-th-muted">
              {data.completed}/{data.expected_total ?? '?'} cells · {data.pareto_front_count} on Pareto front
            </div>
          </div>
        </div>
        <div className="text-[10px] text-th-muted">
          {isRunning ? 'live (updates 30s)' : 'stage complete'}
        </div>
      </div>

      {data.expected_total && (
        <div className="h-1.5 bg-dark-bg rounded overflow-hidden">
          <div
            className={`h-full ${isRunning ? 'bg-accent-cyan' : 'bg-accent-green'} transition-all duration-500`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      )}

      {data.top.length === 0 ? (
        <div className="text-xs text-th-muted text-center py-4">
          No cells completed yet. Grid just started or write delay.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] text-th-muted uppercase tracking-wider border-b border-dark-secondary">
              <tr>
                <th className="py-1.5 px-2 text-left">#</th>
                <th className="py-1.5 px-2 text-left">hash</th>
                <th className="py-1.5 px-1 text-center" title="min_confidence">conf</th>
                <th className="py-1.5 px-1 text-center" title="sl_atr_mult">sl</th>
                <th className="py-1.5 px-1 text-center" title="target_rr">rr</th>
                <th className="py-1.5 px-1 text-center" title="partial_close">pc</th>
                <th className="py-1.5 px-1 text-center" title="risk_percent">risk</th>
                <th className="py-1.5 px-2 text-right">Sharpe</th>
                <th className="py-1.5 px-2 text-right">PF</th>
                <th className="py-1.5 px-2 text-right">Ret</th>
                <th className="py-1.5 px-2 text-right">DD</th>
                <th className="py-1.5 px-2 text-right">Trd</th>
                <th className="py-1.5 px-2 text-right">Comp</th>
              </tr>
            </thead>
            <tbody>
              {data.top.map((e, i) => <Row key={e.cell_hash} entry={e} rank={i + 1} />)}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-[10px] text-th-muted flex items-center gap-3">
        <span className="flex items-center gap-1"><TrendingUp size={10} /> Composite = 0.4·Sharpe + 0.3·Calmar + 0.3·PF</span>
        <span>P = Pareto-optimal (Sharpe × −DD)</span>
      </div>
    </div>
  );
}

export const WFGridLive = memo(WFGridLiveInner);
