/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price + navigation
 */

import { useEffect, useState, memo } from 'react';
import { NavLink } from 'react-router-dom';
import { TrendingUp, TrendingDown, Zap, BarChart3, LineChart, Repeat, Brain, Bot, Sun, Moon, Newspaper } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';
import { useTradingStore } from '../../store/tradingStore';
import { ScrollProgressBar } from './ScrollProgressBar';
import { ConnectionStatus } from '../ui/ConnectionStatus';
import { RiskKillSwitch } from './RiskKillSwitch';
import { analysisAPI } from '../../api/client';
import { prefetchRoute } from '../../hooks/usePrefetch';

interface SessionInfo {
  session: string;
  is_killzone: boolean;
  utc_hour: number;
  cet_hour?: number;
  weekday?: number;
  market_open?: boolean;
  volatility_expected: string;
}

const SESSION_COLORS: Record<string, string> = {
  london:    'text-accent-blue border-accent-blue/40 bg-accent-blue/10',
  overlap:   'text-accent-purple border-accent-purple/40 bg-accent-purple/10',
  new_york:  'text-accent-green border-accent-green/40 bg-accent-green/10',
  asian:     'text-accent-orange border-accent-orange/40 bg-accent-orange/10',
  off_hours: 'text-th-muted border-th-muted/40 bg-th-muted/10',
  weekend:   'text-accent-red/60 border-accent-red/20 bg-accent-red/5',
};

const SESSION_LABELS: Record<string, string> = {
  london:    'London',
  overlap:   'London+NY',
  new_york:  'New York',
  asian:     'Asian',
  off_hours: 'Off-Hours',
  weekend:   'Weekend',
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
  { to: '/news',     label: 'News',     icon: Newspaper },
  { to: '/agent',    label: 'Agent',    icon: Bot },
] as const;

export function Header() {
  const { toggle: toggleTheme, isDark } = useTheme();
  const { ticker, apiConnected } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);

  // Poll session info every 60s — only when API is up, staggered to avoid burst
  useEffect(() => {
    if (!apiConnected) return;
    const fetchSession = () => {
      analysisAPI.getSession().then(setSessionInfo).catch(() => {});
    };
    const initTimer = setTimeout(fetchSession, 1500);
    const t = setInterval(fetchSession, 30_000);
    return () => { clearTimeout(initTimer); clearInterval(t); };
  }, [apiConnected]);

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
      <header className="sticky top-0 z-50 backdrop-blur-md border-b" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div className="px-6 py-3 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
      </header>
    );
  }

  const isPositive = ticker.change >= 0;

  return (
    <header className="sticky top-0 z-50 backdrop-blur-md border-b" style={{ background: `color-mix(in srgb, var(--color-surface) 95%, transparent)`, borderColor: 'var(--color-border)' }}>
      {/* Single row: logo + nav + price + session + status */}
      <div className="px-4 lg:px-6 py-0 flex items-center gap-2 lg:gap-4">
        {/* Logo */}
        <div className="flex items-center gap-1.5 min-w-max py-2.5">
          <span className="text-sm font-bold tracking-wider" style={{ color: 'var(--color-text-primary)' }}>QUANT</span>
          <span className="text-sm font-bold tracking-wider" style={{ color: 'var(--color-accent-green)' }}>SENTINEL</span>
        </div>

        {/* Subtle separator */}
        <div className="hidden md:block w-px h-6" style={{ background: 'var(--color-border)' }} />

        {/* Navigation — inline with header, hidden on mobile (bottom nav takes over) */}
        <nav aria-label="Main navigation" className="hidden md:flex items-center gap-0.5 overflow-x-auto scrollbar-none">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onMouseEnter={() => prefetchRoute(to)}
              onFocus={() => prefetchRoute(to)}
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium rounded-md transition-all duration-150 whitespace-nowrap ${
                  isActive
                    ? 'font-semibold'
                    : 'opacity-50 hover:opacity-80'
                }`
              }
              style={({ isActive }) => ({
                color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                background: isActive ? 'var(--color-secondary)' : 'transparent',
              })}
            >
              <Icon size={12} />
              <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Price — compact, right-aligned */}
        <div className={`flex items-center gap-3 transition-colors duration-200 ${priceFlash === 'up' ? 'text-accent-green' : priceFlash === 'down' ? 'text-accent-red' : ''}`}>
          <div className="text-right">
            <div className="text-lg font-bold font-mono leading-tight" style={{ color: 'var(--color-text-primary)' }}>
              ${ticker.price.toFixed(2)}
            </div>
            <div className={`flex items-center justify-end gap-1 text-[10px] font-medium leading-tight ${isPositive ? 'text-accent-green' : 'text-accent-red'}`}>
              {isPositive ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
              <span>
                {isPositive ? '+' : ''}{ticker.change.toFixed(2)} ({isPositive ? '+' : ''}{ticker.change_pct.toFixed(2)}%)
              </span>
            </div>
          </div>
        </div>

        {/* Session badge */}
        {sessionInfo && <SessionBadge session={sessionInfo} />}

        {/* Risk Kill Switch */}
        <RiskKillSwitch />

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="p-1.5 rounded-md transition-colors hover:bg-dark-secondary"
          style={{ color: 'var(--color-text-muted)' }}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDark ? <Sun size={14} /> : <Moon size={14} />}
        </button>

        {/* Status */}
        <div className="min-w-max">
          <ConnectionStatus />
        </div>
      </div>

      <ScrollProgressBar />
    </header>
  );
}
