/**
 * pages/SettingsPage.tsx — Settings page with tabbed sections
 *
 * Tabs: Account, Risk Management, Display, About
 */

import { useState, useEffect, useCallback } from 'react';
import { Settings, Shield, Palette, Info, RefreshCw, DollarSign, AlertTriangle, CheckCircle, XCircle, Sun, Moon, Monitor, Volume2, VolumeX } from 'lucide-react';
import { useTradingStore } from '../store/tradingStore';
import { portfolioAPI, riskAPI, modelsAPI, healthAPI } from '../api/client';
import { useTheme } from '../hooks/useTheme';
import { useSoundAlerts } from '../hooks/useSoundAlerts';

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

const TABS: { id: Tab; label: string; icon: typeof Settings }[] = [
  { id: 'account', label: 'Konto',         icon: DollarSign },
  { id: 'risk',    label: 'Ryzyko',        icon: Shield },
  { id: 'display', label: 'Wyglad',        icon: Palette },
  { id: 'about',   label: 'Info',          icon: Info },
];

const CURRENCIES = ['PLN', 'USD', 'EUR'] as const;

/* ── Stat Item ─────────────────────────────────────────────────────── */

function StatItem({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="bg-dark-bg rounded-lg border border-dark-secondary p-3">
      <div className="text-[10px] text-th-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-sm font-bold font-mono ${color ?? 'text-th'}`}>{value}</div>
    </div>
  );
}

/* ── Account Tab ───────────────────────────────────────────────────── */

function AccountTab() {
  const portfolio = useTradingStore(s => s.portfolio);
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
      setResult({ ok: false, msg: 'Nieprawidlowa kwota' });
      return;
    }
    setSaving(true);
    setResult(null);
    try {
      await portfolioAPI.updateBalance(val, currency);
      setResult({ ok: true, msg: 'Balans zaktualizowany' });
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : 'Blad aktualizacji' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Current balance */}
      <div className="card">
        <h3 className="section-title mb-3">Aktualny balans</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatItem label="Balans" value={portfolio ? `${portfolio.balance.toFixed(2)} ${portfolio.currency ?? 'PLN'}` : '---'} color="text-accent-green" />
          <StatItem label="Equity" value={portfolio ? portfolio.equity.toFixed(2) : '---'} />
          <StatItem label="PnL" value={portfolio ? `${portfolio.pnl >= 0 ? '+' : ''}${portfolio.pnl.toFixed(2)}` : '---'} color={portfolio && portfolio.pnl >= 0 ? 'text-accent-green' : 'text-accent-red'} />
          <StatItem label="PnL %" value={portfolio ? `${portfolio.pnl_pct >= 0 ? '+' : ''}${portfolio.pnl_pct.toFixed(2)}%` : '---'} color={portfolio && portfolio.pnl_pct >= 0 ? 'text-accent-green' : 'text-accent-red'} />
        </div>
      </div>

      {/* Update balance */}
      <div className="card">
        <h3 className="section-title mb-3">Aktualizuj balans</h3>
        <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3">
          <div className="flex-1 w-full">
            <label className="text-[10px] text-th-muted uppercase tracking-wider block mb-1">Kwota</label>
            <input
              type="number"
              value={balance}
              onChange={e => setBalance(e.target.value)}
              placeholder="10000"
              className="w-full bg-dark-bg border border-dark-secondary rounded-lg px-3 py-2 text-sm font-mono text-th focus:border-accent-green/50 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="text-[10px] text-th-muted uppercase tracking-wider block mb-1">Waluta</label>
            <select
              value={currency}
              onChange={e => setCurrency(e.target.value)}
              className="bg-dark-bg border border-dark-secondary rounded-lg px-3 py-2 text-sm text-th focus:border-accent-green/50 focus:outline-none transition-colors"
            >
              {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <button
            onClick={() => { void handleSave(); }}
            disabled={saving}
            className="px-4 py-2 bg-accent-green/15 text-accent-green border border-accent-green/25 rounded-lg text-sm font-medium hover:bg-accent-green/25 disabled:opacity-50 transition-all"
          >
            {saving ? <RefreshCw size={14} className="animate-spin" /> : 'Zapisz'}
          </button>
        </div>
        {result && (
          <div className={`mt-3 p-2 rounded-lg text-xs flex items-center gap-1.5 ${
            result.ok
              ? 'bg-accent-green/15 border border-accent-green/30 text-accent-green'
              : 'bg-accent-red/15 border border-accent-red/30 text-accent-red'
          }`}>
            {result.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {result.msg}
          </div>
        )}
      </div>
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

  const handleHalt = async () => {
    setActionResult(null);
    try {
      const res = await riskAPI.halt('Manual halt z ustawien');
      setActionResult({ ok: res.success, msg: res.message });
      void fetchRisk();
    } catch (err) {
      setActionResult({ ok: false, msg: err instanceof Error ? err.message : 'Blad' });
    }
  };

  const handleResume = async () => {
    setActionResult(null);
    try {
      const res = await riskAPI.resume();
      setActionResult({ ok: res.success, msg: res.message });
      void fetchRisk();
    } catch (err) {
      setActionResult({ ok: false, msg: err instanceof Error ? err.message : 'Blad' });
    }
  };

  if (loading) {
    return (
      <div className="card flex items-center justify-center py-12 gap-2 text-th-muted text-sm">
        <RefreshCw size={14} className="animate-spin" />
        Ladowanie statusu ryzyka...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="card">
        <h3 className="section-title mb-3">Status ryzyka</h3>

        {/* Halted banner */}
        {risk?.halted && (
          <div className="mb-3 p-3 rounded-lg bg-accent-red/15 border border-accent-red/30 flex items-center gap-2 text-accent-red text-sm font-medium">
            <AlertTriangle size={16} />
            TRADING WSTRZYMANY
            {risk.halt_reason && <span className="text-xs font-normal opacity-75">— {risk.halt_reason}</span>}
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatItem
            label="Status"
            value={risk?.halted ? 'HALTED' : 'ACTIVE'}
            color={risk?.halted ? 'text-accent-red' : 'text-accent-green'}
          />
          <StatItem
            label="Dzienna strata %"
            value={risk ? `${risk.daily_loss_pct.toFixed(2)}%` : '---'}
            color={risk && risk.daily_loss_pct > 2 ? 'text-accent-red' : undefined}
          />
          <StatItem
            label="Hard limit"
            value={risk ? `${risk.daily_loss_hard_limit.toFixed(1)}%` : '---'}
          />
          <StatItem
            label="Straty z rzedu"
            value={risk?.consecutive_losses ?? '---'}
            color={risk && risk.consecutive_losses >= 3 ? 'text-accent-red' : undefined}
          />
          <StatItem
            label="Cooldown"
            value={risk?.cooldown_active ? 'Aktywny' : 'Brak'}
            color={risk?.cooldown_active ? 'text-accent-orange' : undefined}
          />
          <StatItem
            label="Sesja"
            value={risk?.session ?? '---'}
          />
        </div>
      </div>

      {/* Kill switch */}
      <div className="card">
        <h3 className="section-title mb-3">Kill Switch</h3>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { void handleHalt(); }}
            disabled={risk?.halted}
            className="flex-1 py-2.5 bg-accent-red/15 text-accent-red border border-accent-red/25 rounded-lg text-sm font-medium hover:bg-accent-red/25 disabled:opacity-30 transition-all"
          >
            HALT
          </button>
          <button
            onClick={() => { void handleResume(); }}
            disabled={!risk?.halted}
            className="flex-1 py-2.5 bg-accent-green/15 text-accent-green border border-accent-green/25 rounded-lg text-sm font-medium hover:bg-accent-green/25 disabled:opacity-30 transition-all"
          >
            RESUME
          </button>
        </div>
        {actionResult && (
          <div className={`mt-3 p-2 rounded-lg text-xs flex items-center gap-1.5 ${
            actionResult.ok
              ? 'bg-accent-green/15 border border-accent-green/30 text-accent-green'
              : 'bg-accent-red/15 border border-accent-red/30 text-accent-red'
          }`}>
            {actionResult.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {actionResult.msg}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Display Tab ───────────────────────────────────────────────────── */

function DisplayTab() {
  const { pref: themePref, toggle: toggleTheme, isDark } = useTheme();
  const { enabled: soundEnabled, toggle: toggleSound } = useSoundAlerts();

  const themeLabel = themePref === 'dark' ? 'Ciemny' : themePref === 'light' ? 'Jasny' : 'Systemowy';
  const ThemeIcon = themePref === 'system' ? Monitor : isDark ? Moon : Sun;

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="section-title mb-4">Motyw</h3>
        <div className="flex items-center justify-between p-3 bg-dark-bg rounded-lg border border-dark-secondary">
          <div className="flex items-center gap-3">
            <ThemeIcon size={18} className="text-th-muted" />
            <div>
              <div className="text-sm font-medium text-th">{themeLabel}</div>
              <div className="text-[10px] text-th-muted">Kliknij aby przełączyć: dark → light → system</div>
            </div>
          </div>
          <button
            onClick={toggleTheme}
            className="px-4 py-2 bg-accent-blue/12 text-accent-blue border border-accent-blue/25 rounded-lg text-xs font-medium hover:bg-accent-blue/20 transition-all"
          >
            Przelacz
          </button>
        </div>
      </div>

      <div className="card">
        <h3 className="section-title mb-4">Dzwieki</h3>
        <div className="flex items-center justify-between p-3 bg-dark-bg rounded-lg border border-dark-secondary">
          <div className="flex items-center gap-3">
            {soundEnabled ? <Volume2 size={18} className="text-accent-green" /> : <VolumeX size={18} className="text-th-muted" />}
            <div>
              <div className="text-sm font-medium text-th">{soundEnabled ? 'Wlaczone' : 'Wylaczone'}</div>
              <div className="text-[10px] text-th-muted">Alerty dzwiekowe przy nowych sygnalach</div>
            </div>
          </div>
          <button
            onClick={toggleSound}
            className={`px-4 py-2 rounded-lg text-xs font-medium border transition-all ${
              soundEnabled
                ? 'bg-accent-green/12 text-accent-green border-accent-green/25 hover:bg-accent-green/20'
                : 'bg-dark-secondary text-th-muted border-dark-secondary hover:bg-dark-tertiary'
            }`}
          >
            {soundEnabled ? 'Wylacz' : 'Wlacz'}
          </button>
        </div>
      </div>
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
        if (h.status === 'fulfilled') setHealth(h.value);
        if (m.status === 'fulfilled') setModelStats(m.value as unknown as Record<string, unknown>);
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
        Ladowanie informacji...
      </div>
    );
  }

  // Extract model training dates
  const modelNames = ['xgboost', 'lstm', 'attention', 'dqn', 'rl_agent'];
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
    <div className="space-y-4">
      {/* App info */}
      <div className="card">
        <h3 className="section-title mb-3">Aplikacja</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatItem label="Wersja" value={health?.version ?? '1.0.0'} />
          <StatItem label="API Status" value={health?.status ?? 'unknown'} color={health?.status === 'ok' || health?.status === 'healthy' ? 'text-accent-green' : 'text-accent-red'} />
          <StatItem label="Uptime" value={health?.uptime ?? '---'} />
        </div>
      </div>

      {/* Models info */}
      {modelInfos.length > 0 && (
        <div className="card">
          <h3 className="section-title mb-3">Modele ML</h3>
          <div className="space-y-2">
            {modelInfos.map(m => (
              <div key={m.name} className="flex items-center justify-between p-2.5 bg-dark-bg rounded-lg border border-dark-secondary">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-accent-purple" />
                  <span className="text-xs font-medium text-th uppercase">{m.name}</span>
                </div>
                <div className="flex items-center gap-4 text-[10px]">
                  {m.accuracy != null && (
                    <span className="text-th-secondary font-mono">
                      Accuracy: <span className="text-accent-green font-bold">{(m.accuracy * 100).toFixed(1)}%</span>
                    </span>
                  )}
                  {m.lastTrained && (
                    <span className="text-th-muted">
                      Trening: {new Date(m.lastTrained).toLocaleDateString('pl-PL')}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Credits */}
      <div className="card">
        <h3 className="section-title mb-3">O aplikacji</h3>
        <div className="text-xs text-th-muted space-y-1">
          <p>Quant Sentinel — system tradingowy na zloto (XAU/USD)</p>
          <p>ML ensemble: XGBoost + LSTM + Attention + DQN RL Agent</p>
          <p>Frontend: React + TypeScript + Tailwind CSS</p>
          <p>Backend: FastAPI + Python</p>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('account');

  return (
    <div className="space-y-4 max-w-[1200px] mx-auto">
      {/* Tab bar */}
      <div className="flex items-center gap-2">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === id
                ? 'bg-accent-blue/12 text-accent-blue border border-accent-blue/25'
                : 'text-th-muted hover:text-th-secondary border border-transparent'
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'account' && <AccountTab />}
      {tab === 'risk'    && <RiskTab />}
      {tab === 'display' && <DisplayTab />}
      {tab === 'about'   && <AboutTab />}
    </div>
  );
}
