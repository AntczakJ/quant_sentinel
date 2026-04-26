/**
 * src/components/dashboard/QuickStatsBar.tsx — Thin footer bar with key metrics
 *
 * Shows P&L, win rate, open position, session — always visible on desktop.
 * Hidden on mobile (bottom nav takes the space).
 */

import { memo } from 'react';
import { TrendingUp, TrendingDown, Target, Activity } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';

export const QuickStatsBar = memo(function QuickStatsBar() {
  const portfolio = useTradingStore(s => s.portfolio);
  const ticker = useTradingStore(s => s.ticker);
  const wsConnected = useTradingStore(s => s.wsConnected);

  if (!portfolio && !ticker) {return null;}

  const pnl = portfolio?.pnl ?? 0;
  const pnlPositive = pnl >= 0;
  const hasPosition = portfolio?.has_position;

  return (
    <div className="hidden md:flex fixed bottom-0 left-0 right-0 z-30 border-t px-4 py-1 items-center gap-4 text-[10px] font-medium"
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>

      {/* P&L */}
      {portfolio && (
        <div className="flex items-center gap-1">
          {pnlPositive ? <TrendingUp size={9} className="text-accent-green" /> : <TrendingDown size={9} className="text-accent-red" />}
          <span style={{ color: 'var(--color-text-muted)' }}>P&L:</span>
          <span className={`font-mono font-bold ${pnlPositive ? 'text-accent-green' : 'text-accent-red'}`}>
            {pnlPositive ? '+' : ''}{pnl.toFixed(2)} PLN
          </span>
        </div>
      )}

      {/* Balance */}
      {portfolio && (
        <div className="flex items-center gap-1">
          <span style={{ color: 'var(--color-text-muted)' }}>Bal:</span>
          <span className="font-mono" style={{ color: 'var(--color-text-secondary)' }}>
            {portfolio.balance.toFixed(2)}
          </span>
        </div>
      )}

      {/* Position */}
      {hasPosition && (
        <div className="flex items-center gap-1">
          <Target size={9} className="text-accent-blue" />
          <span className={portfolio?.position_type === 'LONG' ? 'text-accent-green' : 'text-accent-red'}>
            {portfolio?.position_type}
          </span>
          <span className="font-mono" style={{ color: 'var(--color-text-muted)' }}>
            ${portfolio?.position_entry?.toFixed(2)}
          </span>
        </div>
      )}

      <div className="flex-1" />

      {/* WS indicator */}
      <div className="flex items-center gap-1">
        <div className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-accent-green' : 'bg-accent-orange'}`} />
        <span style={{ color: 'var(--color-text-muted)' }}>{wsConnected ? 'WS' : 'HTTP'}</span>
      </div>

      {/* Spread/Change */}
      {ticker && (
        <div className="flex items-center gap-1">
          <Activity size={9} style={{ color: 'var(--color-text-muted)' }} />
          <span className="font-mono" style={{ color: 'var(--color-text-muted)' }}>
            Chg: {ticker.change >= 0 ? '+' : ''}{ticker.change.toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
});
