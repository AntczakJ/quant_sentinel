/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price + navigation
 */

import { useEffect, useState, memo } from 'react';
import { NavLink } from 'react-router-dom';
import { TrendingUp, TrendingDown, Zap, BarChart3, LineChart, Repeat, Brain, Bot } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { ScrollProgressBar } from './ScrollProgressBar';
import { ConnectionStatus } from '../ui/ConnectionStatus';
import { analysisAPI } from '../../api/client';
import { prefetchRoute } from '../../hooks/usePrefetch';

interface SessionInfo {
  session: string;
  is_killzone: boolean;
  utc_hour: number;
  volatility_expected: string;
}

const SESSION_COLORS: Record<string, string> = {
  london:    'text-blue-400 border-blue-500/40 bg-blue-500/10',
  london_pre:'text-blue-400/60 border-blue-500/20 bg-blue-500/5',
  new_york:  'text-green-400 border-green-500/40 bg-green-500/10',
  new_york_late: 'text-green-400/60 border-green-500/20 bg-green-500/5',
  asian:     'text-amber-400 border-amber-500/40 bg-amber-500/10',
  off_hours: 'text-gray-500 border-gray-600/40 bg-gray-700/10',
};

const SESSION_LABELS: Record<string, string> = {
  london:    'London',
  london_pre:'London Pre',
  new_york:  'New York',
  new_york_late: 'NY Late',
  asian:     'Asian',
  off_hours: 'Off-Hours',
};

const SessionBadge = memo(function SessionBadge({ session }: { session: SessionInfo }) {
  const colors = SESSION_COLORS[session.session] ?? SESSION_COLORS['off_hours'];
  const label = SESSION_LABELS[session.session] ?? session.session;
  return (
    <div className={`hidden md:flex items-center gap-1.5 px-2 py-1 rounded border text-[11px] font-medium ${colors}`}>
      {session.is_killzone && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 bg-current" />
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-current" />
        </span>
      )}
      {session.is_killzone && <Zap size={10} />}
      <span>{label}</span>
      {session.is_killzone && <span className="opacity-75">KZ</span>}
    </div>
  );
});

const NAV_ITEMS = [
  { to: '/',         label: 'Chart',    icon: BarChart3 },
  { to: '/analysis', label: 'Analysis', icon: LineChart },
  { to: '/trades',   label: 'Trades',   icon: Repeat },
  { to: '/models',   label: 'Models',   icon: Brain },
  { to: '/agent',    label: 'Agent',    icon: Bot },
] as const;

export function Header() {
  const { ticker } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);

  // Poll session info every 60s
  useEffect(() => {
    const fetchSession = () => {
      analysisAPI.getSession().then(setSessionInfo).catch(() => {});
    };
    fetchSession();
    const t = setInterval(fetchSession, 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!ticker) { return; }
    if (prevPrice !== null) {
      if (ticker.price > prevPrice) { setPriceFlash('up'); }
      else if (ticker.price < prevPrice) { setPriceFlash('down'); }
      setTimeout(() => setPriceFlash(null), 300);
    }
    setPrevPrice(ticker.price);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker?.price]);

  if (!ticker) {
    return (
      <header className="sticky top-0 z-50 bg-dark-surface border-b border-dark-secondary">
        <div className="px-6 py-3 text-center text-gray-500 text-sm">Loading...</div>
      </header>
    );
  }

  const isPositive = ticker.change >= 0;

  return (
    <header className="sticky top-0 z-50 bg-dark-surface/95 backdrop-blur-sm border-b border-dark-secondary">
      {/* Top row: logo + price + session + status */}
      <div className="px-4 lg:px-6 py-2 flex items-center justify-between gap-4 max-w-[1600px] mx-auto">
        {/* Logo */}
        <div className="flex items-center gap-2 min-w-max">
          <span className="text-base font-bold text-white tracking-wide">QUANT</span>
          <span className="text-base font-bold text-green-400 tracking-wide">SENTINEL</span>
        </div>

        {/* Price */}
        <div className={`flex-1 text-center transition-colors duration-200 ${priceFlash === 'up' ? 'text-green-400' : priceFlash === 'down' ? 'text-red-400' : ''}`}>
          <div className="text-xl lg:text-2xl font-bold font-mono text-white">
            ${ticker.price.toFixed(2)}
          </div>
          <div className={`flex items-center justify-center gap-1 text-[11px] font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
            <span>
              {isPositive ? '+' : ''}{ticker.change.toFixed(2)} ({isPositive ? '+' : ''}{ticker.change_pct.toFixed(2)}%)
            </span>
          </div>
        </div>

        {/* Session badge */}
        {sessionInfo && <SessionBadge session={sessionInfo} />}

        {/* Status */}
        <div className="text-right min-w-max">
          <ConnectionStatus />
        </div>
      </div>

      {/* Navigation bar */}
      <nav className="px-4 lg:px-6 max-w-[1600px] mx-auto">
        <div className="flex items-center gap-0.5 overflow-x-auto scrollbar-none">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onMouseEnter={() => prefetchRoute(to)}
              onFocus={() => prefetchRoute(to)}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t transition-colors whitespace-nowrap border-b-2 ${
                  isActive
                    ? 'border-green-500 text-green-400 bg-green-500/5'
                    : 'border-transparent text-gray-500 hover:text-gray-300 hover:bg-dark-secondary/50'
                }`
              }
            >
              <Icon size={13} />
              <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </div>
      </nav>

      <ScrollProgressBar />
    </header>
  );
}
