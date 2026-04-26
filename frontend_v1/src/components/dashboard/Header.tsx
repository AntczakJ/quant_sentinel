/**
 * Header.tsx — redesigned 2026-04-25
 * Quantum Editorial aesthetic. Inline desktop nav, compact mobile drawer,
 * oversized price marquee, pill-style session indicator, gradient logomark.
 */

import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  TrendingUp, TrendingDown, BarChart3, LineChart, Repeat, Brain, Bot,
  Sun, Moon, Monitor, Newspaper, Volume2, VolumeX, Settings, Menu, X,
} from 'lucide-react';
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

/* Gradient logomark — editorial QS monogram. */
function Logomark() {
  return (
    <div className="flex items-center gap-2.5">
      <div
        className="relative w-8 h-8 rounded-xl overflow-hidden magnetic"
        style={{
          background: 'linear-gradient(135deg, rgb(var(--c-accent)), rgb(var(--c-accent-2)))',
          boxShadow: '0 4px 14px rgb(var(--c-accent) / 0.35)',
        }}
      >
        <span
          className="absolute inset-0 flex items-center justify-center text-white font-bold text-[13px] tracking-tight"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          Q
        </span>
      </div>
      <div className="hidden sm:flex flex-col leading-none">
        <span
          className="text-[11px] font-bold uppercase tracking-[0.18em]"
          style={{ color: 'var(--color-text-primary)' }}
        >
          Quant
        </span>
        <span
          className="text-[11px] font-bold uppercase tracking-[0.18em] glow-text"
        >
          Sentinel
        </span>
      </div>
    </div>
  );
}

function SessionPill({ info }: { info: SessionInfo }) {
  const label = info.session === 'weekend' ? 'Closed' : info.session;
  const tone = info.session === 'weekend'
    ? 'pill'
    : info.is_killzone
      ? 'pill pill-accent pulse-live'
      : info.volatility_expected === 'high'
        ? 'pill pill-warn'
        : 'pill';
  return (
    <span className={tone} style={{ textTransform: 'capitalize' }}>
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{
          background: info.is_killzone
            ? 'rgb(var(--c-accent))'
            : info.volatility_expected === 'high'
              ? 'rgb(var(--c-warn))'
              : 'rgb(var(--c-text-3))',
        }}
      />
      {label}
    </span>
  );
}

export function Header() {
  const { toggle: toggleTheme, isDark, pref: themePref } = useTheme();
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts();
  const scrollDir = useScrollDirection();
  const { ticker, apiConnected, priceHistory, addPriceHistory } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (ticker?.price) { addPriceHistory(new Date().toISOString(), ticker.price); }
  }, [ticker?.price]); // eslint-disable-line react-hooks/exhaustive-deps

  const sparklineData = priceHistory.slice(-30).map(p => p.price);

  useEffect(() => {
    if (!apiConnected) { return; }
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
      setTimeout(() => setPriceFlash(null), 320);
    }
    setPrevPrice(ticker.price);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker?.price]);

  if (!ticker) {
    return (
      <header
        className="sticky top-0 z-50"
        style={{
          background: 'var(--glass-bg)',
          backdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
          WebkitBackdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
        }}
      >
        <div className="px-6 py-4 flex items-center gap-4">
          <Logomark />
          <div className="flex-1" />
          <div className="shimmer h-6 w-32 rounded-lg" />
        </div>
      </header>
    );
  }

  const isPositive = ticker.change >= 0;

  return (
    <>
      <header
        className={`sticky top-0 z-50 transition-transform duration-300 ${scrollDir === 'down' ? '-translate-y-full' : 'translate-y-0'}`}
        style={{
          background: 'var(--glass-bg)',
          backdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
          WebkitBackdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
          borderBottom: '1px solid var(--glass-border)',
        }}
      >
        <div className="max-w-[1600px] mx-auto px-4 lg:px-8 py-3 flex items-center gap-5">
          {/* Mobile burger */}
          <button
            onClick={() => setMenuOpen(v => !v)}
            className="lg:hidden p-2 rounded-xl magnetic"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Menu"
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>

          <Logomark />

          {/* Inline nav — desktop only. Pill-style tabs. */}
          <nav className="hidden lg:flex items-center gap-1 ml-4">
            {NAV_ITEMS.slice(0, 6).map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onMouseEnter={() => prefetchRoute(to)}
                className={({ isActive }) =>
                  `relative inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all ${
                    isActive ? '' : 'opacity-55 hover:opacity-100'
                  }`
                }
                style={({ isActive }) => ({
                  color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                  background: isActive ? 'rgb(var(--c-accent) / 0.12)' : 'transparent',
                })}
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="flex-1" />

          {/* Oversized editorial price marquee */}
          <div
            className={`flex items-center gap-3 transition-colors duration-300 ${
              priceFlash === 'up' ? 'text-accent-green' : priceFlash === 'down' ? 'text-accent-red' : ''
            }`}
          >
            {sparklineData.length >= 3 && (
              <Sparkline
                data={sparklineData}
                width={56}
                height={22}
                strokeWidth={1.5}
                fill={false}
                className="hidden md:block opacity-60"
              />
            )}
            <div className="text-right">
              <AnimatedNumber
                value={ticker.price}
                decimals={2}
                prefix="$"
                duration={320}
                className="t-mono text-[19px] font-semibold leading-none tracking-tight"
              />
              <div
                className={`flex items-center justify-end gap-1 text-[10px] font-medium leading-none mt-1 ${
                  isPositive ? 'text-accent-green' : 'text-accent-red'
                }`}
              >
                {isPositive ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
                <span className="t-mono">
                  {isPositive ? '+' : ''}{(ticker.change_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          {/* Session pill */}
          {sessionInfo && (
            <div className="hidden md:block">
              <SessionPill info={sessionInfo} />
            </div>
          )}

          {/* Compact controls — icon-only, magnetic */}
          <div className="flex items-center gap-0.5">
            <NotificationCenter />
            <RiskKillSwitch />
            <button
              onClick={toggleSound}
              className="p-2 rounded-xl magnetic"
              style={{ color: soundEnabled ? 'rgb(var(--c-accent))' : 'var(--color-text-dim)' }}
              aria-label={soundEnabled ? 'Mute' : 'Unmute'}
            >
              {soundEnabled ? <Volume2 size={14} /> : <VolumeX size={14} />}
            </button>
            <button
              onClick={toggleTheme}
              className="p-2 rounded-xl magnetic"
              style={{ color: 'var(--color-text-dim)' }}
              aria-label="Theme"
            >
              {themePref === 'system' ? <Monitor size={14} /> : isDark ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <ConnectionStatus />
          </div>
        </div>
        <ScrollProgressBar />
      </header>

      {/* Mobile drawer */}
      <AnimatePresence>
        {menuOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="fixed inset-0 z-40"
              style={{ background: 'rgba(0,0,0,0.45)', backdropFilter: 'blur(8px)' }}
              onClick={() => setMenuOpen(false)}
            />
            <motion.nav
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', damping: 26, stiffness: 320 }}
              className="fixed left-0 top-0 z-50 h-full w-72 py-6 px-5 space-y-1"
              style={{
                background: 'var(--glass-bg)',
                backdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
                WebkitBackdropFilter: 'blur(var(--glass-blur)) saturate(180%)',
                borderRight: '1px solid var(--glass-border)',
                boxShadow: 'var(--shadow-hero)',
              }}
              aria-label="Main navigation"
            >
              <div className="flex items-center justify-between mb-7">
                <Logomark />
                <button
                  onClick={() => setMenuOpen(false)}
                  className="p-2 rounded-xl magnetic"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  <X size={16} />
                </button>
              </div>
              {NAV_ITEMS.map(({ to, label, icon: Icon }, i) => (
                <motion.div
                  key={to}
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.08 + i * 0.04, duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                >
                  <NavLink
                    to={to}
                    end={to === '/'}
                    onClick={() => setMenuOpen(false)}
                    onMouseEnter={() => prefetchRoute(to)}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-3 rounded-xl text-[14px] font-medium transition-all ${
                        isActive ? 'font-semibold' : 'opacity-65 hover:opacity-100'
                      }`
                    }
                    style={({ isActive }) => ({
                      color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                      background: isActive ? 'rgb(var(--c-accent) / 0.12)' : 'transparent',
                    })}
                  >
                    <Icon size={17} />
                    {label}
                  </NavLink>
                </motion.div>
              ))}
            </motion.nav>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
