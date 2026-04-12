/**
 * pages/SettingsPage.tsx — Account, Risk, Display, About.
 *
 * Architecture:
 *   - Premium Tabs primitive (sliding indicator, keyboard-navigable).
 *   - Each tab is its own component so we can lazy-render (prevents all API
 *     calls firing the moment Settings opens).
 *   - AnimatePresence handles panel crossfade.
 *
 * Design:
 *   - PageHeader at top sets tone.
 *   - Setting "tiles" replace raw StatItem grids: clearer label hierarchy,
 *     optional status glow, hover lift for interactive ones.
 *   - Toggle switches replace text buttons for boolean prefs — more obvious
 *     state, more premium feel.
 */

import { useState, useEffect, useCallback, memo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Shield, Palette, Info, RefreshCw, DollarSign,
  AlertTriangle, CheckCircle, XCircle,
  Sun, Moon, Monitor, Volume2, VolumeX,
} from 'lucide-react';
import { useTradingStore } from '../store/tradingStore';
import { portfolioAPI, riskAPI, modelsAPI, healthAPI } from '../api/client';
import { useTheme } from '../hooks/useTheme';
import { useSoundAlerts } from '../hooks/useSoundAlerts';
import { PageHeader, Tabs, type TabItem } from '../components/ui';
import { pageTransition } from '../lib/motion';

/* ── Types ─────────────────────────────────────────────────────────── */

interface RiskStatus {
  halted: boolean;
  halt_reason?: string;
  daily_loss_pct: number;
  daily_loss_soft_limit: number;
  daily_loss_hard_limit: number;
  consecutive_losses: number;
  cooldown_active?: boolean;
  cooldown_until?: string | null;
  max_portfolio_heat_pct?: number;
  kelly_risk_pct?: number;
  session?: string;
  spread_buffer?: number;
}

interface HealthData {
  status?: string;
  uptime?: string;
  uptime_seconds?: number;
  version?: string;
  [key: string]: unknown;
}

type Tab = 'account' | 'risk' | 'display' | 'about';

const CURRENCIES = ['PLN', 'USD', 'EUR'] as const;

/* ── Reusable UI bits ──────────────────────────────────────────────── */

/**
 * Stat tile — more polished than the original StatItem.
 * Emphasizes value with display typography; label sits above in a muted caps style.
 */
const StatTile = memo(function StatTile({
  label, value, color, hint,
}: {
  label: string;
  value: string | number;
  color?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-th-border bg-dark-surface/40 p-3.5
                    transition-colors hover:border-th-border-h">
      <div className="text-[10px] uppercase tracking-[0.14em] text-th-dim font-medium">
        {label}
      </div>
      <div className={`mt-1.5 font-mono text-[15px] font-semibold tabular-nums ${color ?? 'text-th'}`}>
        {value}
      </div>
      {hint && <div className="mt-0.5 text-[10px] text-th-muted">{hint}</div>}
    </div>
  );
});

/**
 * Premium toggle switch — replaces ad-hoc text buttons for boolean preferences.
 * The knob animates across via Motion layout; background crossfades.
 */
const ToggleSwitch = memo(function ToggleSwitch({
  checked, onChange, ariaLabel,
}: {
  checked: boolean;
  onChange: () => void;
  ariaLabel: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={onChange}
      className={`relative inline-flex items-center w-11 h-6 rounded-full transition-colors duration-200
                  ${checked ? 'bg-accent-green' : 'bg-dark-tertiary'}`}
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 500, damping: 32 }}
        className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-md
                    ${checked ? 'left-[1.375rem]' : 'left-0.5'}`}
      />
    </button>
  );
});

/**
 * Result banner — used after save/halt/resume actions.
 * Auto-dismisses visually via AnimatePresence at call site.
 */
const ResultBanner = memo(function ResultBanner({
  result,
}: {
  result: { ok: boolean; msg: string } | null;
}) {
  return (
    <AnimatePresence initial={false}>
      {result && (
        <motion.div
          initial={{ opacity: 0, height: 0, marginTop: 0 }}
          animate={{ opacity: 1, height: 'auto', marginTop: 12 }}
          exit={{ opacity: 0, height: 0, marginTop: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className={`p-2.5 rounded-lg text-xs flex items-center gap-2 ${
            result.ok
              ? 'bg-accent-green/[0.08] border border-accent-green/25 text-accent-green'
              : 'bg-accent-red/[0.08] border border-accent-red/25 text-accent-red'
          }`}>
            {result.ok ? <CheckCircle size={13} /> : <XCircle size={13} />}
            {result.msg}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
});

/* ── Account Tab ───────────────────────────────────────────────────── */

function AccountTab() {
  const portfolio = useTradingStore((s) => s.portfolio);
  const [balance, setBalance] = useState('');
  const [currency, setCurrency] = useState<string>('PLN');
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    if (portfolio) {
      setBalance(String(portfolio.balance ?? ''));
      setCurrency(portfolio.currency ?? 'PLN');
    }
  }, [portfolio]);

  const handleSave = async () => {
    const val = parseFloat(balance);
    if (isNaN(val) || val <= 0) {
      setResult({ ok: false, msg: 'Invalid amount' });
      return;
    }
    setSaving(true);
    setResult(null);
    try {
      await portfolioAPI.updateBalance(val, currency);
      setResult({ ok: true, msg: 'Balance updated' });
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : 'Update failed' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Current balance snapshot */}
      <section className="card space-y-4">
        <div className="flex items-center gap-2">
          <DollarSign size={14} className="text-accent-green" />
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Current balance
          </h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatTile
            label="Balance"
            value={portfolio ? `${portfolio.balance.toFixed(2)} ${portfolio.currency ?? 'PLN'}` : '—'}
            color="text-accent-green"
          />
          <StatTile
            label="Equity"
            value={portfolio ? portfolio.equity.toFixed(2) : '—'}
          />
          <StatTile
            label="P&L"
            value={portfolio ? `${portfolio.pnl >= 0 ? '+' : ''}${portfolio.pnl.toFixed(2)}` : '—'}
            color={portfolio && portfolio.pnl >= 0 ? 'text-accent-green' : 'text-accent-red'}
          />
          <StatTile
            label="P&L %"
            value={portfolio ? `${portfolio.pnl_pct >= 0 ? '+' : ''}${portfolio.pnl_pct.toFixed(2)}%` : '—'}
            color={portfolio && portfolio.pnl_pct >= 0 ? 'text-accent-green' : 'text-accent-red'}
          />
        </div>
      </section>

      {/* Update balance */}
      <section className="card space-y-4">
        <div>
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Adjust balance
          </h3>
          <p className="mt-1 text-xs text-th-muted">
            Overrides the broker-reported equity. Use to reset simulated balance or align with real account.
          </p>
        </div>
        <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3">
          <div className="flex-1 w-full">
            <label className="text-[10px] uppercase tracking-[0.14em] text-th-dim block mb-1.5 font-medium">
              Amount
            </label>
            <input
              type="number"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              placeholder="10000"
              className="w-full h-10 bg-dark-bg border border-th-border rounded-lg px-3
                         text-sm font-mono text-th
                         focus:border-accent-green/50 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-[0.14em] text-th-dim block mb-1.5 font-medium">
              Currency
            </label>
            <select
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="h-10 bg-dark-bg border border-th-border rounded-lg px-3 text-sm text-th
                         focus:border-accent-green/50 focus:outline-none transition-colors"
            >
              {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <button
            onClick={() => { void handleSave(); }}
            disabled={saving}
            className="h-10 px-5 bg-accent-green/15 text-accent-green border border-accent-green/25 rounded-lg
                       text-sm font-semibold hover:bg-accent-green/25 disabled:opacity-50
                       transition-colors flex items-center gap-2"
          >
            {saving && <RefreshCw size={14} className="animate-spin" />}
            Save
          </button>
        </div>
        <ResultBanner result={result} />
      </section>
    </div>
  );
}

/* ── Risk Tab ──────────────────────────────────────────────────────── */

function RiskTab() {
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionResult, setActionResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const fetchRisk = useCallback(async () => {
    try {
      const data = await riskAPI.getStatus();
      setRisk(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchRisk(); }, [fetchRisk]);

  const handleAction = async (fn: () => Promise<{ success: boolean; message: string }>) => {
    setActionResult(null);
    try {
      const res = await fn();
      setActionResult({ ok: res.success, msg: res.message });
      void fetchRisk();
    } catch (err) {
      setActionResult({ ok: false, msg: err instanceof Error ? err.message : 'Error' });
    }
  };

  if (loading) {
    return (
      <div className="card flex items-center justify-center py-12 gap-2 text-th-muted text-sm">
        <RefreshCw size={14} className="animate-spin" />
        Loading risk status...
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Halted banner (prominent) */}
      <AnimatePresence initial={false}>
        {risk?.halted && (
          <motion.div
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            className="rounded-xl border border-accent-red/30 bg-accent-red/[0.08]
                       p-4 flex items-start gap-3"
            role="alert"
          >
            <AlertTriangle size={18} className="text-accent-red shrink-0 mt-0.5" />
            <div>
              <div className="text-sm font-semibold text-accent-red">Trading halted</div>
              {risk.halt_reason && (
                <div className="mt-0.5 text-xs text-accent-red/80">{risk.halt_reason}</div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Status tiles */}
      <section className="card space-y-4">
        <div className="flex items-center gap-2">
          <Shield size={14} className="text-accent-orange" />
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Risk status
          </h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatTile
            label="State"
            value={risk?.halted ? 'HALTED' : 'ACTIVE'}
            color={risk?.halted ? 'text-accent-red' : 'text-accent-green'}
          />
          <StatTile
            label="Daily loss"
            value={risk ? `${risk.daily_loss_pct.toFixed(2)}%` : '—'}
            hint={risk ? `Hard limit ${risk.daily_loss_hard_limit.toFixed(1)}%` : undefined}
            color={risk && risk.daily_loss_pct > 2 ? 'text-accent-red' : undefined}
          />
          <StatTile
            label="Consecutive losses"
            value={risk?.consecutive_losses ?? '—'}
            color={risk && risk.consecutive_losses >= 3 ? 'text-accent-red' : undefined}
          />
          <StatTile
            label="Cooldown"
            value={risk?.cooldown_active ? 'Active' : 'None'}
            color={risk?.cooldown_active ? 'text-accent-orange' : undefined}
          />
          <StatTile label="Session" value={risk?.session ?? '—'} />
          <StatTile
            label="Portfolio heat"
            value={risk?.max_portfolio_heat_pct !== undefined
              ? `${risk.max_portfolio_heat_pct.toFixed(1)}%` : '—'}
          />
        </div>
      </section>

      {/* Kill switch */}
      <section className="card space-y-3">
        <div>
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Kill switch
          </h3>
          <p className="mt-1 text-xs text-th-muted">
            Emergency halt closes no positions but blocks new orders until resumed.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { void handleAction(() => riskAPI.halt('Manual halt from settings')); }}
            disabled={risk?.halted}
            className="flex-1 h-11 rounded-lg text-sm font-semibold transition-colors
                       bg-accent-red/15 text-accent-red border border-accent-red/25
                       hover:bg-accent-red/25 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            HALT
          </button>
          <button
            onClick={() => { void handleAction(() => riskAPI.resume()); }}
            disabled={!risk?.halted}
            className="flex-1 h-11 rounded-lg text-sm font-semibold transition-colors
                       bg-accent-green/15 text-accent-green border border-accent-green/25
                       hover:bg-accent-green/25 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            RESUME
          </button>
        </div>
        <ResultBanner result={actionResult} />
      </section>
    </div>
  );
}

/* ── Display Tab ───────────────────────────────────────────────────── */

function DisplayTab() {
  const { pref: themePref, toggle: toggleTheme, isDark } = useTheme();
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts();

  const themeLabel = themePref === 'dark' ? 'Dark' : themePref === 'light' ? 'Light' : 'System';
  const ThemeIcon = themePref === 'system' ? Monitor : isDark ? Moon : Sun;

  return (
    <div className="space-y-5">
      <section className="card space-y-4">
        <div className="flex items-center gap-2">
          <Palette size={14} className="text-accent-blue" />
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Appearance
          </h3>
        </div>

        {/* Theme selector — horizontal segmented control */}
        <div>
          <div className="text-xs text-th-muted mb-2">Theme</div>
          <button
            onClick={toggleTheme}
            className="w-full flex items-center justify-between p-3.5
                       rounded-xl bg-dark-bg/60 border border-th-border
                       hover:border-th-border-h hover:bg-dark-bg
                       transition-colors group"
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-accent-blue/[0.08] flex items-center justify-center
                              group-hover:scale-105 transition-transform">
                <ThemeIcon size={16} className="text-accent-blue" />
              </div>
              <div className="text-left">
                <div className="text-sm font-medium text-th">{themeLabel}</div>
                <div className="text-[11px] text-th-muted">Click to cycle: Dark → Light → System</div>
              </div>
            </div>
            <div className="text-[11px] text-th-dim group-hover:text-th-secondary transition-colors">
              Change
            </div>
          </button>
        </div>
      </section>

      <section className="card space-y-4">
        <div className="flex items-center gap-2">
          {soundEnabled
            ? <Volume2 size={14} className="text-accent-green" />
            : <VolumeX  size={14} className="text-th-muted" />}
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            Notifications
          </h3>
        </div>

        <div className="flex items-center justify-between p-3.5 rounded-xl
                        bg-dark-bg/60 border border-th-border">
          <div>
            <div className="text-sm font-medium text-th">Sound alerts</div>
            <div className="mt-0.5 text-[11px] text-th-muted">
              Play a sound cue when a new trading signal arrives.
            </div>
          </div>
          <ToggleSwitch
            checked={soundEnabled}
            onChange={toggleSound}
            ariaLabel={soundEnabled ? 'Disable sound alerts' : 'Enable sound alerts'}
          />
        </div>
      </section>
    </div>
  );
}

/* ── About Tab ─────────────────────────────────────────────────────── */

function AboutTab() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [modelStats, setModelStats] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [h, m] = await Promise.allSettled([healthAPI.check(), modelsAPI.getStats()]);
        if (h.status === 'fulfilled') {setHealth(h.value);}
        if (m.status === 'fulfilled') {setModelStats(m.value as unknown as Record<string, unknown>);}
      } finally {
        setLoading(false);
      }
    };
    void fetchAll();
  }, []);

  if (loading) {
    return (
      <div className="card flex items-center justify-center py-12 gap-2 text-th-muted text-sm">
        <RefreshCw size={14} className="animate-spin" />
        Loading info...
      </div>
    );
  }

  // Full ensemble voter list (keep in sync with default_weights in
  // src/ml/ensemble_models.py::_load_dynamic_weights). `xgboost` and
  // `rl_agent` remain for backward-compat with older /api/model-stats
  // responses that used those keys.
  const modelNames = [
    'smc', 'attention', 'dpformer', 'lstm', 'xgb', 'xgboost',
    'dqn', 'rl_agent', 'deeptrans',
  ];
  const modelInfos: { name: string; lastTrained?: string; accuracy?: number }[] = [];
  if (modelStats) {
    for (const name of modelNames) {
      const m = (modelStats as Record<string, Record<string, unknown>>)[name];
      if (m) {
        modelInfos.push({
          name,
          lastTrained: (m.last_trained ?? m.trained_at ?? m.timestamp) as string | undefined,
          accuracy: (m.accuracy ?? m.rolling_accuracy) as number | undefined,
        });
      }
    }
  }

  return (
    <div className="space-y-5">
      {/* App info */}
      <section className="card space-y-4">
        <div className="flex items-center gap-2">
          <Info size={14} className="text-accent-cyan" />
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            System
          </h3>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatTile label="Version" value={health?.version ?? '1.0.0'} />
          <StatTile
            label="API status"
            value={health?.status ?? 'unknown'}
            color={health?.status === 'ok' || health?.status === 'healthy' ? 'text-accent-green' : 'text-accent-red'}
          />
          <StatTile label="Uptime" value={health?.uptime ?? '—'} />
        </div>
      </section>

      {/* Models */}
      {modelInfos.length > 0 && (
        <section className="card space-y-3">
          <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary">
            ML Models
          </h3>
          <div className="space-y-2">
            {modelInfos.map((m, i) => (
              <motion.div
                key={m.name}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.04, duration: 0.28 }}
                className="flex items-center justify-between p-3 rounded-xl
                           bg-dark-bg/60 border border-th-border hover:border-th-border-h
                           transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-2 h-2 rounded-full bg-accent-purple" />
                  <span className="text-xs font-semibold text-th uppercase tracking-wider">
                    {m.name}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-[11px]">
                  {m.accuracy !== null && m.accuracy !== undefined && (
                    <span className="text-th-secondary font-mono">
                      Acc <span className="text-accent-green font-semibold">
                        {(m.accuracy * 100).toFixed(1)}%
                      </span>
                    </span>
                  )}
                  {m.lastTrained && (
                    <span className="text-th-muted">
                      {new Date(m.lastTrained).toLocaleDateString('pl-PL')}
                    </span>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </section>
      )}

      {/* Credits */}
      <section className="card">
        <h3 className="text-[13px] font-semibold uppercase tracking-wider text-th-secondary mb-3">
          About
        </h3>
        <div className="text-xs text-th-muted space-y-1 leading-relaxed">
          <p><span className="text-th-secondary font-medium">Quant Sentinel</span> — algorithmic trading platform for XAU/USD.</p>
          <p>Ensemble: SMC · LSTM · XGBoost · Attention · DQN RL.</p>
          <p>Stack: React 19 · TypeScript · Tailwind 4 · FastAPI · Python.</p>
        </div>
      </section>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

const TAB_ITEMS: TabItem[] = [
  { id: 'account', label: 'Account', icon: DollarSign, accent: 'green' },
  { id: 'risk',    label: 'Risk',    icon: Shield,     accent: 'orange' },
  { id: 'display', label: 'Display', icon: Palette,    accent: 'blue' },
  { id: 'about',   label: 'About',   icon: Info,       accent: 'purple' },
];

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('account');

  return (
    <div className="max-w-[1200px] mx-auto">
      <PageHeader
        eyebrow="Configuration"
        title="Settings"
        subtitle="Account balance, risk controls, appearance, and system info."
      />

      <div className="mb-5">
        <Tabs
          items={TAB_ITEMS}
          activeId={tab}
          onChange={(id) => setTab(id as Tab)}
          instanceId="settings"
        />
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          {...pageTransition}
          id={`panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab}`}
        >
          {tab === 'account' && <AccountTab />}
          {tab === 'risk'    && <RiskTab />}
          {tab === 'display' && <DisplayTab />}
          {tab === 'about'   && <AboutTab />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
