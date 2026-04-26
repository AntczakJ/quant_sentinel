import { useEffect, useState, memo } from 'react';
import { Loader2, TrendingUp, TrendingDown, Activity, AlertTriangle, CheckCircle } from 'lucide-react';
import { backtestResultsAPI, type VoterLiveAccuracyResponse } from '../../api/client';

const STATUS_STYLE = {
  good: { color: 'text-accent-green', bg: 'bg-accent-green/10', icon: CheckCircle },
  weak: { color: 'text-accent-orange', bg: 'bg-accent-orange/10', icon: AlertTriangle },
  anti_signal: { color: 'text-accent-red', bg: 'bg-accent-red/10', icon: AlertTriangle },
  insufficient: { color: 'text-th-muted', bg: 'bg-dark-bg', icon: Activity },
} as const;

function fmtPct(n: number | null): string {
  return n === null || n === undefined ? '—' : `${n.toFixed(0)}%`;
}

function VoterAccuracyInner() {
  const [data, setData] = useState<VoterLiveAccuracyResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [horizonCandles, setHorizonCandles] = useState(12); // 1h default

  useEffect(() => {
    let alive = true;
    const load = async () => {
      setLoading(true);
      try {
        const d = await backtestResultsAPI.loadVoterAccuracy(72, horizonCandles);
        if (alive) { setData(d); setErr(null); }
      } catch (e) {
        if (alive) { setErr(e instanceof Error ? e.message : 'Failed'); }
      } finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const t = setInterval(() => { void load(); }, 60_000); // refresh 1m (cache is 10m anyway)
    return () => { alive = false; clearInterval(t); };
  }, [horizonCandles]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-32 text-th-muted">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading voter accuracy...
      </div>
    );
  }
  if (err) { return <div className="text-xs text-accent-red">Error: {err}</div>; }
  if (!data) { return null; }

  const verdictStyle = data.verdict === 'ok' ? 'bg-accent-green/15 border-accent-green/30 text-accent-green'
    : data.verdict === 'warn' ? 'bg-accent-orange/15 border-accent-orange/30 text-accent-orange'
    : 'bg-accent-red/15 border-accent-red/30 text-accent-red';

  const horizons = [
    { val: 3, label: '15m' },
    { val: 6, label: '30m' },
    { val: 12, label: '1h' },
    { val: 24, label: '2h' },
    { val: 48, label: '4h' },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className={`px-2 py-1 rounded border text-xs font-medium ${verdictStyle}`}>
          {data.verdict.toUpperCase()}
        </div>
        {data.alerts.length > 0 && (
          <span className="text-xs text-accent-red">anti-signal: {data.alerts.join(', ')}</span>
        )}
        {data.warnings.length > 0 && (
          <span className="text-xs text-accent-orange">weak: {data.warnings.join(', ')}</span>
        )}
        <div className="ml-auto flex items-center gap-1">
          {horizons.map(h => (
            <button
              key={h.val}
              onClick={() => setHorizonCandles(h.val)}
              className={`text-[10px] px-2 py-0.5 rounded ${horizonCandles === h.val
                ? 'bg-accent-cyan text-black'
                : 'bg-dark-bg text-th-muted hover:text-th-primary'}`}
            >
              {h.label}
            </button>
          ))}
          <span className="text-[10px] text-th-muted ml-2">
            {data.cached ? `cached ${data.cache_age_sec.toFixed(0)}s` : 'fresh'}
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-[10px] text-th-muted uppercase tracking-wider border-b border-dark-secondary">
            <tr>
              <th className="py-1.5 px-2 text-left">Voter</th>
              <th className="py-1.5 px-2 text-right">Samples</th>
              <th className="py-1.5 px-2 text-right">Bull</th>
              <th className="py-1.5 px-2 text-right">Bear</th>
              <th className="py-1.5 px-2 text-right">Combined</th>
              <th className="py-1.5 px-2 text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.voters).map(([name, v]) => {
              const s = STATUS_STYLE[v.status];
              const Icon = s.icon;
              const bullGood = v.bullish_accuracy_pct !== null && v.bullish_accuracy_pct >= 55;
              const bearGood = v.bearish_accuracy_pct !== null && v.bearish_accuracy_pct >= 55;
              const combinedGood = v.combined_accuracy_pct !== null && v.combined_accuracy_pct >= 55;
              return (
                <tr key={name} className={s.bg}>
                  <td className="py-1.5 px-2 font-medium">{name}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-th-muted">{v.decisive_samples}</td>
                  <td className={`py-1.5 px-2 text-right font-mono ${bullGood ? 'text-accent-green' : 'text-th-muted'}`}>
                    <TrendingUp size={10} className="inline mr-0.5" />
                    {fmtPct(v.bullish_accuracy_pct)}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono ${bearGood ? 'text-accent-green' : 'text-th-muted'}`}>
                    <TrendingDown size={10} className="inline mr-0.5" />
                    {fmtPct(v.bearish_accuracy_pct)}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono font-semibold ${combinedGood ? 'text-accent-green' : 'text-th-primary'}`}>
                    {fmtPct(v.combined_accuracy_pct)}
                  </td>
                  <td className={`py-1.5 px-2 text-right text-[10px] ${s.color}`}>
                    <Icon size={10} className="inline mr-0.5" />
                    {v.status}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-[10px] text-th-muted">
        Horizon {data.horizon_label} × window {data.hours_window}h. Decisive = pred&gt;0.7 or &lt;0.3.
        Status: good ≥55%, weak ≥45%, anti-signal &lt;45%.
      </div>
    </div>
  );
}

export const VoterAccuracy = memo(VoterAccuracyInner);
