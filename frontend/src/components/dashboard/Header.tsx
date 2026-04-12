/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price + navigation
 */

import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { TrendingUp, TrendingDown, BarChart3, LineChart, Repeat, Brain, Bot, Sun, Moon, Monitor, Newspaper, Volume2, VolumeX, Settings, Menu, X } from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
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




const NAV_ITEMS = [
  { to: '/',         label: 'Chart',    icon: BarChart3 },
  { to: '/analysis', label: 'Analysis', icon: LineChart },
  { to: '/trades',   label: 'Trades',   icon: Repeat },
  { to: '/models',   label: 'Models',   icon: Brain },
  { to: '/news',     label: 'News',     icon: Newspaper },
  { to: '/agent',    label: 'Agent',    icon: Bot },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const;

export function Header() {
  const { toggle: toggleTheme, isDark, pref: themePref } = useTheme();
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts();
  const scrollDir = useScrollDirection();
  const { ticker, apiConnected, priceHistory, addPriceHistory } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  // Track price history for sparkline
  useEffect(() => {
    if (ticker?.price) {addPriceHistory(new Date().toISOString(), ticker.price);}
  }, [ticker?.price]); // eslint-disable-line react-hooks/exhaustive-deps

  const sparklineData = priceHistory.slice(-30).map(p => p.price);

  // Poll session info every 60s — only when API is up, staggered to avoid burst
  useEffect(() => {
    if (!apiConnected) {return;}
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
    <>
    <header className={`sticky top-0 z-50 transition-transform duration-300 ${scrollDir === 'down' ? '-translate-y-full' : 'translate-y-0'}`} style={{ background: 'var(--glass-bg)', backdropFilter: `blur(${('var(--glass-blur)')})`, WebkitBackdropFilter: `blur(var(--glass-blur))`, borderBottom: '1px solid var(--glass-border)' }}>
      <div className="px-5 lg:px-8 py-2.5 flex items-center gap-4">
        {/* Burger + Logo */}
        <button
          onClick={() => setMenuOpen(v => !v)}
          className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-secondary)]"
          style={{ color: 'var(--color-text-muted)' }}
          aria-label="Menu"
          aria-expanded={menuOpen}
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>

        <div className="flex items-center gap-1 min-w-max">
          <span className="text-sm font-bold tracking-wider" style={{ color: 'rgb(var(--c-accent))' }}>QS</span>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Price — compact */}
        <div className={`flex items-center gap-2 transition-colors duration-200 ${priceFlash === 'up' ? 'text-accent-green' : priceFlash === 'down' ? 'text-accent-red' : ''}`}>
          {sparklineData.length >= 3 && (
            <Sparkline data={sparklineData} width={40} height={18} strokeWidth={1} fill={false} className="hidden lg:block opacity-50" />
          )}
          <div className="text-right">
            <AnimatedNumber value={ticker.price} decimals={2} prefix="$" duration={300}
              className="text-base font-bold font-mono leading-tight" />
            <div className={`flex items-center justify-end gap-1 text-[9px] font-medium leading-tight ${isPositive ? 'text-accent-green' : 'text-accent-red'}`}>
              {isPositive ? <TrendingUp size={8} /> : <TrendingDown size={8} />}
              <span>{isPositive ? '+' : ''}{(ticker.change_pct ?? 0).toFixed(2)}%</span>
            </div>
          </div>
        </div>

        {/* Session — minimal dot only */}
        {sessionInfo && (
          <div className="hidden md:flex items-center gap-1.5 text-[10px] font-medium" style={{ color: 'var(--color-text-muted)' }}>
            <span className={`w-1.5 h-1.5 rounded-full ${
              sessionInfo.is_killzone ? 'bg-accent-green animate-pulse'
              : sessionInfo.volatility_expected === 'high' ? 'bg-accent-red'
              : 'bg-th-muted'
            }`} />
            {sessionInfo.session === 'weekend' ? 'Closed' : sessionInfo.session}
          </div>
        )}

        {/* Compact controls */}
        <div className="flex items-center gap-0.5">
          <NotificationCenter />
          <RiskKillSwitch />
          <button onClick={toggleSound} className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-secondary)]"
            style={{ color: soundEnabled ? 'var(--color-accent-green)' : 'var(--color-text-dim)' }}
            aria-label={soundEnabled ? 'Mute' : 'Unmute'}>
            {soundEnabled ? <Volume2 size={13} /> : <VolumeX size={13} />}
          </button>
          <button onClick={toggleTheme} className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-secondary)]"
            style={{ color: 'var(--color-text-dim)' }}
            aria-label="Theme">
            {themePref === 'system' ? <Monitor size={13} /> : isDark ? <Sun size={13} /> : <Moon size={13} />}
          </button>
          <ConnectionStatus />
        </div>
      </div>
      <ScrollProgressBar />
    </header>

    {/* Animated slide-out navigation drawer */}
    <AnimatePresence>
    {menuOpen && (
      <>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          onClick={() => setMenuOpen(false)}
        />
        <motion.nav
          initial={{ x: '-100%' }}
          animate={{ x: 0 }}
          exit={{ x: '-100%' }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          className="fixed left-0 top-0 z-50 h-full w-64 py-6 px-4 space-y-0.5"
          style={{ background: 'var(--glass-bg)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', borderRight: '1px solid var(--glass-border)', boxShadow: '8px 0 40px rgba(0,0,0,0.3)' }}
          aria-label="Main navigation"
        >
          <div className="flex items-center justify-between px-2 mb-5">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-bold tracking-wider" style={{ color: 'var(--color-text-primary)' }}>QUANT</span>
              <span className="text-sm font-bold tracking-wider" style={{ color: 'rgb(var(--c-accent))' }}>SENTINEL</span>
            </div>
            <button onClick={() => setMenuOpen(false)} className="p-1.5 rounded-lg hover:bg-[var(--color-secondary)] transition-colors" style={{ color: 'var(--color-text-muted)' }}>
              <X size={16} />
            </button>
          </div>
          {NAV_ITEMS.map(({ to, label, icon: Icon }, i) => (
            <motion.div
              key={to}
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.05 + i * 0.03, duration: 0.2 }}
            >
              <NavLink
                to={to}
                end={to === '/'}
                onClick={() => setMenuOpen(false)}
                onMouseEnter={() => prefetchRoute(to)}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                    isActive ? 'font-semibold' : 'opacity-60 hover:opacity-100'
                  }`
                }
                style={({ isActive }) => ({
                  color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                  background: isActive ? 'rgba(168,85,247,0.1)' : 'transparent',
                  borderLeft: isActive ? '2px solid rgb(var(--c-accent))' : '2px solid transparent',
                })}
              >
                <Icon size={16} />
                {label}
              </NavLink>
            </motion.div>
          ))}

          {/* Bottom accent line */}
          <div className="absolute bottom-4 left-3 right-3">
            <div className="h-px w-full" style={{ background: 'linear-gradient(90deg, transparent, rgb(var(--c-accent) / 0.3), transparent)' }} />
          </div>
        </motion.nav>
      </>
    )}
    </AnimatePresence>
    </>
  );
}
