/**
 * src/components/dashboard/ModelsStalenessBadge.tsx
 *
 * Compact alert on ModelsPage header showing if any model file is >14 days old.
 * Reads /api/health/models. Non-blocking (just visual) — users can trigger
 * retraining via CLI when they see stale warnings.
 */
import { useState, useEffect, memo } from 'react';
import { AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';
import { healthAPI } from '../../api/client';

type ModelsHealth = Awaited<ReturnType<typeof healthAPI.models>>;

export const ModelsStalenessBadge = memo(function ModelsStalenessBadge() {
  const [data, setData] = useState<ModelsHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      try {
        const r = await healthAPI.models();
        if (!cancelled) {setData(r);}
      } catch {
        if (!cancelled) {setData(null);}
      } finally {
        if (!cancelled) {setLoading(false);}
      }
    };
    void fetch();
    const id = setInterval(fetch, 120_000); // 2 min
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-th-muted">
        <Loader2 size={12} className="animate-spin" /> Models...
      </div>
    );
  }

  if (!data) {return null;}

  const staleList = Object.entries(data.models)
    .filter(([, m]) => m.status === 'stale')
    .map(([name, m]) => ({ name, age_days: m.age_days ?? 0 }));

  const missingList = Object.entries(data.models)
    .filter(([, m]) => m.status === 'missing')
    .map(([name]) => name);

  if (data.status === 'fresh') {
    return (
      <div className="flex items-center gap-1.5 text-xs text-accent-green">
        <CheckCircle size={12} /> All models fresh
      </div>
    );
  }

  return (
    <div
      className={`flex items-center gap-2 text-xs px-2 py-1 rounded ${
        data.status === 'degraded'
          ? 'bg-accent-red/15 border border-accent-red/30 text-accent-red'
          : 'bg-accent-orange/15 border border-accent-orange/30 text-accent-orange'
      }`}
      title={
        staleList.length
          ? `Stale models: ${staleList.map(m => `${m.name} (${m.age_days.toFixed(0)}d)`).join(', ')}` +
            (missingList.length ? ` | Missing: ${missingList.join(', ')}` : '')
          : `Missing: ${missingList.join(', ')}`
      }
    >
      <AlertTriangle size={12} />
      <span>
        {staleList.length > 0 && `${staleList.length} model${staleList.length === 1 ? '' : 's'} stale`}
        {staleList.length > 0 && missingList.length > 0 && ' · '}
        {missingList.length > 0 && `${missingList.length} missing`}
      </span>
      <span className="text-[10px] opacity-70">
        (retrain: <code>python train_all.py</code>)
      </span>
    </div>
  );
});
