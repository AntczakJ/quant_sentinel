/**
 * src/components/dashboard/MtfConfluence.tsx — Multi-Timeframe Confluence Panel
 *
 * Professional heatmap showing bull/bear alignment across 4 timeframes (5m/15m/1h/4h).
 * Uses /api/analysis/mtf-confluence endpoint with polling.
 */

import { memo } from 'react';
import { BarChart2, Zap, Clock } from 'lucide-react';
import { usePollingQuery } from '../../hooks/usePollingQuery';
import { analysisAPI } from '../../api/client';

interface MtfData {
  confluence_score: number;
  direction: string;
  bull_pct: number;
  bear_pct: number;
  bull_tf_count: number;
  bear_tf_count: number;
  timeframes: Record<string, { trend: string; rsi: number; weight: number }>;
  session?: { session: string; is_killzone: boolean; volatility_expected: string };
}

const TF_ORDER = ['5m', '15m', '1h', '4h'] as const;
const TF_LABELS: Record<string, string> = { '5m': 'M5', '15m': 'M15', '1h': 'H1', '4h': 'H4' };

const SESSION_LABELS: Record<string, string> = {
  london: 'London', overlap: 'London+NY', new_york: 'New York',
  asian: 'Asian', off_hours: 'Off-Hours', weekend: 'Weekend',
};
const SESSION_COLORS: Record<string, string> = {
  london: 'text-accent-blue', overlap: 'text-accent-purple', new_york: 'text-accent-green',
  asian: 'text-accent-orange', off_hours: 'text-th-muted', weekend: 'text-accent-red',
};

function isBullish(trend: string): boolean {
  return trend === 'bull' || trend === 'bullish';
}

/** Circular gauge for confluence score 0-10 */
function ScoreGauge({ score, direction }: { score: number; direction: string }) {
  const pct = Math.min(score / 10, 1);
  const radius = 36;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);

  const isBull = direction.includes('BULL');
  const isBear = direction.includes('BEAR');
  const strokeColor = isBull ? 'rgb(var(--c-green))' : isBear ? 'rgb(var(--c-red))' : 'rgb(var(--c-orange))';
  const textColor = isBull ? 'text-accent-green' : isBear ? 'text-accent-red' : 'text-accent-orange';

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="88" height="88" viewBox="0 0 88 88" className="drop-shadow-sm">
        {/* Track */}
        <circle cx="44" cy="44" r={radius} fill="none"
          stroke="rgb(var(--c-border))" strokeWidth="5" />
        {/* Value arc */}
        <circle cx="44" cy="44" r={radius} fill="none"
          stroke={strokeColor} strokeWidth="5" strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={offset}
          transform="rotate(-90 44 44)"
          className="transition-all duration-700 ease-out" />
        {/* Score text */}
        <text x="44" y="40" textAnchor="middle" dominantBaseline="central"
          className={`text-xl font-bold font-mono ${textColor}`}
          fill="currentColor" style={{ fontSize: '22px', fontWeight: 700 }}>
          {score.toFixed(0)}
        </text>
        <text x="44" y="56" textAnchor="middle" dominantBaseline="central"
          fill="rgb(var(--c-text-3))" style={{ fontSize: '9px', fontWeight: 500 }}>
          /10
        </text>
      </svg>
      <span className={`text-xs font-bold ${textColor}`}>{direction}</span>
    </div>
  );
}

/** Single timeframe row with trend, RSI bar, and weight indicator */
function TfRow({ tf, trend, rsi, weight }: { tf: string; trend: string; rsi: number; weight: number }) {
  const bull = isBullish(trend);
  const rsiColor = rsi > 70 ? 'text-accent-red' : rsi < 30 ? 'text-accent-green' : 'text-accent-blue';
  const rsiBarColor = rsi > 70 ? 'bg-accent-red' : rsi < 30 ? 'bg-accent-green' : 'bg-accent-blue';
  const trendBg = bull ? 'bg-accent-green/12' : 'bg-accent-red/12';
  const trendText = bull ? 'text-accent-green' : 'text-accent-red';
  const trendIcon = bull ? '▲' : '▼';

  return (
    <div className="flex items-center gap-3 py-1.5">
      {/* TF label */}
      <span className="text-xs font-bold font-mono text-th-secondary w-8">{TF_LABELS[tf] ?? tf}</span>

      {/* Trend badge */}
      <span className={`${trendBg} ${trendText} text-[10px] font-bold px-2 py-0.5 rounded w-14 text-center`}>
        {trendIcon} {bull ? 'BULL' : 'BEAR'}
      </span>

      {/* RSI bar */}
      <div className="flex-1 flex items-center gap-2">
        <div className="flex-1 h-1.5 bg-dark-secondary rounded-full overflow-hidden">
          <div className={`h-full ${rsiBarColor} rounded-full transition-all duration-500`}
            style={{ width: `${Math.min(rsi, 100)}%` }} />
        </div>
        <span className={`text-[10px] font-mono font-bold w-8 text-right ${rsiColor}`}>
          {rsi.toFixed(0)}
        </span>
      </div>

      {/* Weight dots */}
      <div className="flex gap-0.5">
        {[1, 2, 3].map(i => (
          <div key={i} className={`w-1.5 h-1.5 rounded-full transition-colors ${
            i <= Math.round(weight * 3) ? (bull ? 'bg-accent-green' : 'bg-accent-red') : 'bg-dark-secondary'
          }`} />
        ))}
      </div>
    </div>
  );
}

export const MtfConfluence = memo(function MtfConfluence() {
  const { data, isLoading } = usePollingQuery<MtfData>(
    'mtf-confluence',
    () => analysisAPI.getMtfConfluence(),
    45_000,
  );

  if (isLoading && !data) {
    return (
      <div className="text-xs text-th-muted text-center py-6">Ladowanie konfluencji MTF...</div>
    );
  }

  if (!data || !data.timeframes) {
    return (
      <div className="text-xs text-th-muted text-center py-6">Brak danych MTF</div>
    );
  }

  const session = data.session;

  return (
    <div className="space-y-3">
      {/* Top: Score gauge + Bull/Bear bar */}
      <div className="flex items-center gap-4">
        <ScoreGauge score={data.confluence_score ?? 0} direction={data.direction ?? 'WAIT'} />

        <div className="flex-1 space-y-2">
          {/* Bull vs Bear proportion */}
          <div className="space-y-1">
            <div className="flex justify-between text-[10px] font-medium">
              <span className="text-accent-green">BULL {data.bull_pct?.toFixed(0) ?? 0}%</span>
              <span className="text-accent-red">BEAR {data.bear_pct?.toFixed(0) ?? 0}%</span>
            </div>
            <div className="relative h-2 rounded-full overflow-hidden bg-accent-red/25">
              <div className="absolute inset-y-0 left-0 bg-accent-green/70 rounded-full transition-all duration-500"
                style={{ width: `${data.bull_pct ?? 50}%` }} />
            </div>
          </div>

          {/* TF count */}
          <div className="flex items-center gap-2 text-[10px] text-th-muted">
            <BarChart2 size={10} />
            <span className="text-accent-green font-bold">{data.bull_tf_count ?? 0}</span> bull
            <span className="mx-1">·</span>
            <span className="text-accent-red font-bold">{data.bear_tf_count ?? 0}</span> bear
          </div>

          {/* Session info */}
          {session && (
            <div className="flex items-center gap-1.5 text-[10px]">
              <Clock size={9} className="text-th-muted" />
              <span className={`font-medium ${SESSION_COLORS[session.session] ?? 'text-th-muted'}`}>
                {SESSION_LABELS[session.session] ?? session.session}
              </span>
              {session.is_killzone && (
                <span className="flex items-center gap-0.5 text-accent-orange font-bold">
                  <Zap size={8} /> KZ
                </span>
              )}
              <span className="text-th-dim ml-1">
                Vol: {session.volatility_expected}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Timeframe breakdown rows */}
      <div className="border-t border-dark-secondary pt-2">
        <div className="flex items-center gap-2 mb-1.5 text-[9px] text-th-dim uppercase tracking-wider font-medium">
          <span className="w-8">TF</span>
          <span className="w-14 text-center">Trend</span>
          <span className="flex-1 pl-1">RSI</span>
          <span>Waga</span>
        </div>
        {TF_ORDER.map(tf => {
          const t = data.timeframes[tf];
          if (!t) return null;
          return <TfRow key={tf} tf={tf} trend={t.trend} rsi={t.rsi} weight={t.weight} />;
        })}
      </div>
    </div>
  );
});
