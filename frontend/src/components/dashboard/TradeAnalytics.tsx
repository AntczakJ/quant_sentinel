import { useEffect, useState, memo } from 'react';
import { Loader2, BarChart3, Clock } from 'lucide-react';
import { backtestResultsAPI } from '../../api/client';

type TFData = Awaited<ReturnType<typeof backtestResultsAPI.loadPerTF>>;
type SessionData = Awaited<ReturnType<typeof backtestResultsAPI.loadPerSession>>;
type StreakData = Awaited<ReturnType<typeof backtestResultsAPI.loadStreak>>;

function TradeAnalyticsInner() {
  const [tf, setTF] = useState<TFData | null>(null);
  const [sess, setSess] = useState<SessionData | null>(null);
  const [streak, setStreak] = useState<StreakData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [t, s, st] = await Promise.all([
          backtestResultsAPI.loadPerTF(),
          backtestResultsAPI.loadPerSession(),
          backtestResultsAPI.loadStreak(10),
        ]);
        if (alive) { setTF(t); setSess(s); setStreak(st); }
      } catch {} finally {
        if (alive) { setLoading(false); }
      }
    };
    void load();
    const timer = setInterval(() => { void load(); }, 60_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  if (loading && !tf) {
    return <div className="flex items-center justify-center h-20 text-th-muted">
      <Loader2 size={14} className="animate-spin mr-2" /> Loading...
    </div>;
  }

  return (
    <div className="space-y-4">
      {/* Streak bar */}
      {streak && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-th-muted uppercase tracking-wider">Streak:</span>
          <div className="flex gap-[2px]">
            {streak.trades.map((t) => (
              <div
                key={t.id}
                className={`w-5 h-5 rounded-sm flex items-center justify-center text-[9px] font-bold ${
                  t.outcome === 'win'
                    ? 'bg-accent-green/30 text-accent-green'
                    : 'bg-accent-red/30 text-accent-red'
                }`}
                title={`#${t.id} ${t.direction} $${t.profit?.toFixed(0)}`}
              >
                {t.outcome === 'win' ? 'W' : 'L'}
              </div>
            ))}
          </div>
          <span className={`text-xs font-mono font-bold ${
            streak.current_streak > 0 ? 'text-accent-green' : streak.current_streak < 0 ? 'text-accent-red' : 'text-th-muted'
          }`}>
            {streak.streak_label}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Per TF */}
        {tf && (
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-th-muted uppercase tracking-wider mb-2">
              <BarChart3 size={10} /> Per Timeframe
            </div>
            <div className="space-y-1.5">
              {tf.timeframes.map((t) => {
                const good = t.win_rate_pct >= 45;
                return (
                  <div key={t.tf} className="flex items-center gap-2 text-[11px]">
                    <span className="font-mono w-8 font-medium">{t.tf}</span>
                    <div className="flex-1 h-1.5 bg-dark-bg rounded overflow-hidden">
                      <div
                        className={`h-full ${good ? 'bg-accent-green' : 'bg-accent-red'}`}
                        style={{ width: `${Math.min(t.win_rate_pct, 100)}%` }}
                      />
                    </div>
                    <span className={`font-mono w-10 text-right ${good ? 'text-accent-green' : 'text-accent-red'}`}>
                      {t.win_rate_pct.toFixed(0)}%
                    </span>
                    <span className="font-mono w-14 text-right text-th-muted">{t.trades}t</span>
                    <span className={`font-mono w-16 text-right ${t.net_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                      ${t.net_pnl >= 0 ? '+' : ''}{t.net_pnl.toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Per Session */}
        {sess && (
          <div>
            <div className="flex items-center gap-1.5 text-[10px] text-th-muted uppercase tracking-wider mb-2">
              <Clock size={10} /> Per Session
            </div>
            <div className="space-y-1.5">
              {sess.sessions.map((s) => {
                const good = s.win_rate_pct >= 45;
                return (
                  <div key={s.session} className="flex items-center gap-2 text-[11px]">
                    <span className="font-mono w-16 truncate font-medium" title={s.session}>{s.session}</span>
                    <div className="flex-1 h-1.5 bg-dark-bg rounded overflow-hidden">
                      <div
                        className={`h-full ${good ? 'bg-accent-green' : 'bg-accent-red'}`}
                        style={{ width: `${Math.min(s.win_rate_pct, 100)}%` }}
                      />
                    </div>
                    <span className={`font-mono w-10 text-right ${good ? 'text-accent-green' : 'text-accent-red'}`}>
                      {s.win_rate_pct.toFixed(0)}%
                    </span>
                    <span className="font-mono w-14 text-right text-th-muted">{s.trades}t</span>
                    <span className={`font-mono w-16 text-right ${s.net_pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                      ${s.net_pnl >= 0 ? '+' : ''}{s.net_pnl.toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export const TradeAnalytics = memo(TradeAnalyticsInner);
