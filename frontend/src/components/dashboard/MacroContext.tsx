/**
 * MacroContext.tsx — Live macro context for XAU/USD.
 *
 * Shows the USD-strength signal (USDJPY z-score), XAU/USDJPY inverse
 * correlation (-1 is healthy inverse, +1 is broken regime), and current
 * macro_regime tag. Tiny strip — sits in Chart page overview area.
 *
 * Gold's dominant driver is USD strength; when USDJPY-XAU correlation
 * flips from negative to positive, mean-reversion strategies typically
 * break. This widget lets you see regime health at a glance.
 */

import { useEffect, useState, memo } from 'react';
import { TrendingUp, TrendingDown, Link, Unlink } from 'lucide-react';
import client from '../../api/client';

interface MacroData {
  usdjpy: number | null;
  usdjpy_zscore: number | null;
  xau_usdjpy_corr: number | null;
  macro_regime: 'zielony' | 'czerwony' | 'neutralny' | null;
  uup: number | null;
  tlt: number | null;
  vixy: number | null;
}

function regimeLabel(regime: string | null) {
  switch (regime) {
    case 'zielony':
      return { text: 'BULLISH', tone: 'good' as const };
    case 'czerwony':
      return { text: 'BEARISH', tone: 'bad' as const };
    case 'neutralny':
      return { text: 'NEUTRAL', tone: 'neutral' as const };
    default:
      return { text: '—', tone: 'neutral' as const };
  }
}

function MacroContextInner() {
  const [data, setData] = useState<MacroData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const res = await client.get<MacroData>('/macro/context');
        if (alive) {
          setData(res.data);
        }
      } catch {
        // Silent — macro widget shouldn't noisily fail
      } finally {
        if (alive) {
          setLoading(false);
        }
      }
    };
    void load();
    const id = window.setInterval(load, 60000); // 60s refresh
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-4 px-3 py-1.5 text-xs text-th-muted animate-pulse">
        Loading macro…
      </div>
    );
  }
  if (!data) {
    return null;
  }

  const regime = regimeLabel(data.macro_regime);
  const zscore = data.usdjpy_zscore;
  const corr = data.xau_usdjpy_corr;
  const usdStrong = zscore !== null && zscore > 0.5;
  const usdWeak = zscore !== null && zscore < -0.5;
  const corrHealthy = corr !== null && corr < -0.2;
  const corrBroken = corr !== null && corr > 0.2;

  return (
    <div className="flex items-center gap-4 px-3 py-1.5 text-xs bg-dark-bg-soft rounded-lg border border-dark-secondary">
      <span className="text-[10px] text-th-muted uppercase tracking-wider">Macro</span>

      {/* USDJPY z-score */}
      <div className="flex items-center gap-1">
        {usdStrong ? (
          <TrendingUp size={12} className="text-accent-red" />
        ) : usdWeak ? (
          <TrendingDown size={12} className="text-accent-green" />
        ) : (
          <span className="w-3" />
        )}
        <span className="text-th-muted">USD</span>
        <span
          className={`font-mono font-medium ${
            usdStrong
              ? 'text-accent-red'
              : usdWeak
                ? 'text-accent-green'
                : 'text-th-primary'
          }`}
        >
          {zscore !== null ? `z ${zscore > 0 ? '+' : ''}${zscore.toFixed(2)}` : '—'}
        </span>
        <span className="text-[10px] text-th-muted">
          {usdStrong ? '(strong → bearish XAU)' : usdWeak ? '(weak → bullish XAU)' : ''}
        </span>
      </div>

      <span className="text-dark-secondary">|</span>

      {/* XAU-USDJPY correlation */}
      <div className="flex items-center gap-1">
        {corrHealthy ? (
          <Link size={12} className="text-accent-green" />
        ) : corrBroken ? (
          <Unlink size={12} className="text-accent-orange" />
        ) : (
          <span className="w-3" />
        )}
        <span className="text-th-muted">corr</span>
        <span
          className={`font-mono font-medium ${
            corrHealthy
              ? 'text-accent-green'
              : corrBroken
                ? 'text-accent-orange'
                : 'text-th-primary'
          }`}
        >
          {corr !== null ? corr.toFixed(2) : '—'}
        </span>
        <span className="text-[10px] text-th-muted">
          {corrHealthy
            ? '(healthy inverse)'
            : corrBroken
              ? '(broken regime)'
              : ''}
        </span>
      </div>

      <span className="text-dark-secondary">|</span>

      {/* Regime */}
      <div className="flex items-center gap-1">
        <span className="text-th-muted">regime</span>
        <span
          className={`font-mono font-semibold text-[11px] px-1.5 py-0.5 rounded ${
            regime.tone === 'good'
              ? 'bg-accent-green/15 text-accent-green'
              : regime.tone === 'bad'
                ? 'bg-accent-red/15 text-accent-red'
                : 'bg-dark-secondary text-th-primary'
          }`}
        >
          {regime.text}
        </span>
      </div>
    </div>
  );
}

export const MacroContext = memo(MacroContextInner);
