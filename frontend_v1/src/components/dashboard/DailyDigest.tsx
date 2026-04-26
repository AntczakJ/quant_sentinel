import { useEffect, useState, memo } from 'react';
import { Loader2, Newspaper } from 'lucide-react';
import { backtestResultsAPI } from '../../api/client';

function DailyDigestInner() {
  const [text, setText] = useState<string>('');
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hours, setHours] = useState(24);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await backtestResultsAPI.loadDailyDigest(hours);
        if (alive) { setText(d.text); setErr(null); }
      } catch (e) {
        if (alive) { setErr(e instanceof Error ? e.message : 'Failed'); }
      } finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const t = setInterval(() => { void load(); }, 60_000);
    return () => { alive = false; clearInterval(t); };
  }, [hours]);

  if (loading && !text) {
    return (
      <div className="flex items-center justify-center h-20 text-th-muted">
        <Loader2 size={14} className="animate-spin mr-2" /> Loading...
      </div>
    );
  }
  if (err) { return <div className="text-xs text-accent-red">Error: {err}</div>; }

  const windows = [
    { val: 6, label: '6h' },
    { val: 24, label: '24h' },
    { val: 72, label: '72h' },
    { val: 168, label: '7d' },
  ];

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-th-muted">
          <Newspaper size={12} />
          <span>Digest — matches Telegram output</span>
        </div>
        <div className="flex items-center gap-1">
          {windows.map(w => (
            <button
              key={w.val}
              onClick={() => setHours(w.val)}
              className={`text-[10px] px-2 py-0.5 rounded ${hours === w.val
                ? 'bg-accent-cyan text-black'
                : 'bg-dark-bg text-th-muted hover:text-th-primary'}`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      <pre className="text-xs font-mono whitespace-pre-wrap bg-dark-bg rounded p-3 border border-dark-secondary text-th-primary leading-relaxed">
        {text}
      </pre>
    </div>
  );
}

export const DailyDigest = memo(DailyDigestInner);
