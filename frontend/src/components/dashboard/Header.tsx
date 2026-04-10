/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price + navigation
 */

import { useEffect, useState, memo } from 'react';
import { NavLink } from 'react-router-dom';
import { TrendingUp, TrendingDown, Zap, BarChart3, LineChart, Repeat, Brain, Bot, Sun, Moon, Monitor, Newspaper, Volume2, VolumeX } from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';
import { useTradingStore } from '../../store/tradingStore';
import { ScrollProgressBar } from './ScrollProgressBar';
import { ConnectionStatus } from '../ui/ConnectionStatus';
import { RiskKillSwitch } from './RiskKillSwitch';
import { NotificationCenter } from './NotificationCenter';
import { useSoundAlerts } from '../../hooks/useSoundAlerts';
import { analysisAPI } from '../../api/client';
import { Sparkline } from '../ui/Sparkline';
import { AnimatedNumber } from '../ui/AnimatedNumber';
import { prefetchRoute } from '../../hooks/usePrefetch';
import { useScrollDirection } from '../../hooks/useScrollDirection';

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

/** Session end hours (UTC) */
const SESSION_END_H: Record<string, number> = {
  asian: 8, london: 16, overlap: 16, new_york: 22, off_hours: 0, weekend: 0,
};

function useSessionCountdown(session: string, _utcHour: number): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick(v => v + 1), 30_000);
    return () => clearInterval(t);
  }, []);

  const endH = SESSION_END_H[session];
  if (!endH || session === 'off_hours' || session === 'weekend') return '';

  const now = new Date();
  const end = new Date(now);
  end.setUTCHours(endH, 0, 0, 0);
  if (end.getTime() <= now.getTime()) end.setUTCDate(end.getUTCDate() + 1);

  const diffMin = Math.floor((end.getTime() - now.getTime()) / 60000);
  if (diffMin <= 0) return '';
  if (diffMin < 60) return `${diffMin}m`;
  return `${Math.floor(diffMin / 60)}h${diffMin % 60 > 0 ? ` ${diffMin % 60}m` : ''}`;
}

const SessionBadge = memo(function SessionBadge({ session }: { session: SessionInfo }) {
  const colors = SESSION_COLORS[session.session] ?? SESSION_COLORS['off_hours'];
  const label = SESSION_LABELS[session.session] ?? session.session;
  const countdown = useSessionCountdown(session.session, session.utc_hour);

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
      {countdown && <span className="opacity-60 text-[9px] font-mono">{countdown}</span>}
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
  const { toggle: toggleTheme, isDark, pref: themePref } = useTheme();
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts();
  const scrollDir = useScrollDirection();
  const { ticker, apiConnected, priceHistory, addPriceHistory } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);

  // Track price history for sparkline
  useEffect(() => {
    if (ticker?.price) addPriceHistory(new Date().toISOString(), ticker.price);
  }, [ticker?.price]); // eslint-disable-line react-hooks/exhaustive-deps

  const sparklineData = priceHistory.slice(-30).map(p => p.price);

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
    <header className={`sticky top-0 z-50 backdrop-blur-md border-b transition-transform duration-300 ${scrollDir === 'down' ? '-translate-y-full' : 'translate-y-0'}`} style={{ background: `color-mix(in srgb, var(--color-surface) 95%, transparent)`, borderColor: 'var(--color-border)' }}>
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

        {/* Price — compact, right-aligned + sparkline */}
        <div className={`flex items-center gap-2 transition-colors duration-200 ${priceFlash === 'up' ? 'text-accent-green' : priceFlash === 'down' ? 'text-accent-red' : ''}`}>
          {sparklineData.length >= 3 && (
            <Sparkline data={sparklineData} width={48} height={20} strokeWidth={1.2} fill={false} className="hidden lg:block opacity-70" />
          )}
          <div className="text-right">
            <AnimatedNumber value={ticker.price} decimals={2} prefix="$" duration={300}
              className="text-lg font-bold font-mono leading-tight" />
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

        {/* Volatility regime badge */}
        {sessionInfo?.volatility_expected && (
          <div className={`hidden lg:flex items-center gap-1 px-2 py-1 rounded border text-[10px] font-medium ${
            sessionInfo.volatility_expected === 'high'
              ? 'text-accent-red border-accent-red/30 bg-accent-red/8'
              : sessionInfo.volatility_expected === 'medium'
              ? 'text-accent-orange border-accent-orange/30 bg-accent-orange/8'
              : 'text-th-muted border-th-muted/20 bg-th-muted/5'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              sessionInfo.volatility_expected === 'high' ? 'bg-accent-red animate-pulse'
              : sessionInfo.volatility_expected === 'medium' ? 'bg-accent-orange'
              : 'bg-th-muted'
            }`} />
            Vol: {sessionInfo.volatility_expected}
          </div>
        )}

        {/* Notification center */}
        <NotificationCenter />

        {/* Risk Kill Switch */}
        <RiskKillSwitch />

        {/* Sound toggle */}
        <button
          onClick={toggleSound}
          className="p-1.5 rounded-md transition-colors hover:bg-dark-secondary"
          style={{ color: soundEnabled ? 'var(--color-accent-green)' : 'var(--color-text-muted)' }}
          title={soundEnabled ? 'Wylacz dzwieki' : 'Wlacz dzwieki alertow'}
        >
          {soundEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
        </button>

        {/* Theme toggle (dark → light → system → dark) */}
        <button
          onClick={toggleTheme}
          className="p-1.5 rounded-md transition-colors hover:bg-dark-secondary"
          style={{ color: themePref === 'system' ? 'var(--color-accent-blue)' : 'var(--color-text-muted)' }}
          title={themePref === 'dark' ? 'Light mode' : themePref === 'light' ? 'System mode' : 'Dark mode'}
        >
          {themePref === 'system' ? <Monitor size={14} /> : isDark ? <Sun size={14} /> : <Moon size={14} />}
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
