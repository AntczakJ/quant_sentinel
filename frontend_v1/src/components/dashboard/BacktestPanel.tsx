/**
 * src/components/dashboard/BacktestPanel.tsx — Backtesting UI
 *
 * Form to select model/period/interval, run backtest, and display results
 * including classification metrics, equity metrics, and Monte Carlo VaR.
 */

import { memo, useState, useCallback } from 'react';
import {
  Play, Loader2, BarChart3, TrendingUp, TrendingDown,
  Shield, AlertTriangle, Activity,
} from 'lucide-react';
import { Tooltip } from '../ui/Tooltip';
import { backtestAPI } from '../../api/client';
import { useToast } from '../ui/Toast';

/* ── Types ─────────────────────────────────────────────────────────── */

interface ModelResult {
  accuracy?: number;
  MCC?: number;
  F1?: number;
  Sharpe?: number;
  Sortino?: number;
  Calmar?: number;
  VaR?: number;
  max_drawdown?: number;
  total_return?: number;
  n_trades?: number;
  win_rate?: number;
  error?: string;
}

interface MonteCarloResult {
  VaR_95?: number;
  CVaR_95?: number;
  risk_distribution?: number[];
  error?: string;
}

interface BacktestResult {
  data_bars: number;
  period: string;
  interval: string;
  xgb?: ModelResult;
  lstm?: ModelResult;
  dqn?: ModelResult;
  ensemble?: ModelResult;
  monte_carlo?: MonteCarloResult;
}

/* ── Constants ─────────────────────────────────────────────────────── */

const MODELS = [
  { value: 'all', label: 'All Models' },
  { value: 'xgb', label: 'XGBoost' },
  { value: 'lstm', label: 'LSTM' },
  { value: 'dqn', label: 'DQN' },
  { value: 'ensemble', label: 'Ensemble' },
] as const;

const PERIODS = [
  { value: '1mo', label: '1 Month' },
  { value: '3mo', label: '3 Months' },
  { value: '6mo', label: '6 Months' },
  { value: '1y', label: '1 Year' },
] as const;

const INTERVALS = [
  { value: '15m', label: '15min' },
  { value: '1h', label: '1H' },
  { value: '4h', label: '4H' },
  { value: '1d', label: '1D' },
] as const;

const MODEL_COLORS: Record<string, string> = {
  xgb: 'text-accent-orange',
  lstm: 'text-accent-purple',
  dqn: 'text-accent-blue',
  ensemble: 'text-accent-cyan',
};

const MODEL_LABELS: Record<string, string> = {
  xgb: 'XGBoost', lstm: 'LSTM', dqn: 'DQN', ensemble: 'Ensemble',
};

/* ── Metric helpers ────────────────────────────────────────────────── */

const METRIC_TOOLTIPS: Record<string, string> = {
  'Accuracy': 'Procent poprawnych predykcji kierunku',
  'MCC': 'Matthews Correlation Coefficient — lepsza metryka niz accuracy dla niezbalansowanych danych (-1 do +1)',
  'F1': 'Srednia harmoniczna precision i recall (0-1)',
  'Sharpe': 'Zwrot skorygowany o ryzyko. Sharpe > 1 = dobry, > 2 = swietny',
  'Sortino': 'Jak Sharpe ale penalizuje tylko downside volatility',
  'Calmar': 'Roczny zwrot / max drawdown. Calmar > 1 = dobry',
};

function MetricCell({ label, value, color, suffix }: {
  label: string; value: number | undefined; color?: string; suffix?: string;
}) {
  if (value === undefined) {return <div className="text-center text-th-dim text-[10px]">—</div>;}
  const displayColor = color ?? (value >= 0 ? 'text-accent-green' : 'text-accent-red');
  const tip = METRIC_TOOLTIPS[label];
  const labelEl = <div className={`text-[9px] text-th-muted uppercase tracking-wider ${tip ? 'cursor-help' : ''}`}>{label}</div>;
  return (
    <div className="text-center">
      {tip ? <Tooltip content={tip}>{labelEl}</Tooltip> : labelEl}
      <div className={`text-xs font-bold font-mono ${displayColor}`}>
        {value.toFixed(label === 'MCC' || label === 'F1' ? 3 : 2)}{suffix ?? ''}
      </div>
    </div>
  );
}

/* ── Model Result Card ─────────────────────────────────────────────── */

const ModelCard = memo(function ModelCard({ name, result }: { name: string; result: ModelResult }) {
  if (result.error) {
    return (
      <div className="stat-item border-accent-red/20">
        <div className="flex items-center gap-1.5 mb-1">
          <AlertTriangle size={10} className="text-accent-red" />
          <span className={`text-xs font-bold ${MODEL_COLORS[name] ?? 'text-th'}`}>{MODEL_LABELS[name] ?? name}</span>
        </div>
        <div className="text-[10px] text-accent-red truncate">{result.error}</div>
      </div>
    );
  }

  const wrColor = (result.win_rate ?? 0) >= 0.5 ? 'text-accent-green' : 'text-accent-red';
  const retColor = (result.total_return ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red';

  return (
    <div className="stat-item space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className={`text-sm font-bold ${MODEL_COLORS[name] ?? 'text-th'}`}>
          {MODEL_LABELS[name] ?? name}
        </span>
        <div className="flex items-center gap-2">
          {result.n_trades !== undefined && (
            <span className="text-[10px] text-th-muted">{result.n_trades} trades</span>
          )}
          {result.win_rate !== undefined && (
            <span className={`text-xs font-bold font-mono ${wrColor}`}>
              {(result.win_rate * 100).toFixed(1)}% WR
            </span>
          )}
        </div>
      </div>

      {/* Return + Drawdown hero */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1">
          {(result.total_return ?? 0) >= 0 ? <TrendingUp size={14} className="text-accent-green" /> : <TrendingDown size={14} className="text-accent-red" />}
          <span className={`text-lg font-bold font-mono ${retColor}`}>
            {(result.total_return ?? 0) >= 0 ? '+' : ''}{((result.total_return ?? 0) * 100).toFixed(2)}%
          </span>
        </div>
        {result.max_drawdown !== undefined && (
          <div className="flex items-center gap-1">
            <Shield size={10} className="text-accent-red" />
            <span className="text-xs font-mono text-accent-red">DD: {(result.max_drawdown * 100).toFixed(2)}%</span>
          </div>
        )}
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-2 pt-1 border-t border-dark-secondary">
        <MetricCell label="Accuracy" value={result.accuracy !== undefined ? result.accuracy * 100 : undefined} color="text-accent-blue" suffix="%" />
        <MetricCell label="MCC" value={result.MCC} color={result.MCC !== undefined && result.MCC > 0 ? 'text-accent-green' : 'text-accent-red'} />
        <MetricCell label="F1" value={result.F1} color="text-accent-blue" />
        <MetricCell label="Sharpe" value={result.Sharpe} />
        <MetricCell label="Sortino" value={result.Sortino} />
        <MetricCell label="Calmar" value={result.Calmar} />
      </div>
    </div>
  );
});

/* ── Monte Carlo Card ──────────────────────────────────────────────── */

const MonteCarloCard = memo(function MonteCarloCard({ mc }: { mc: MonteCarloResult }) {
  if (mc.error) {
    return (
      <div className="stat-item border-accent-orange/20">
        <div className="text-[10px] text-accent-orange">Monte Carlo error: {mc.error}</div>
      </div>
    );
  }

  return (
    <div className="stat-item space-y-2">
      <div className="flex items-center gap-1.5">
        <BarChart3 size={12} className="text-accent-purple" />
        <span className="text-xs font-bold text-accent-purple">Monte Carlo (5000 sim.)</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {mc.VaR_95 !== undefined && (
          <div>
            <div className="text-[9px] text-th-muted uppercase tracking-wider">VaR 95%</div>
            <div className="text-sm font-bold font-mono text-accent-red">
              {(mc.VaR_95 * 100).toFixed(3)}%
            </div>
          </div>
        )}
        {mc.CVaR_95 !== undefined && (
          <div>
            <div className="text-[9px] text-th-muted uppercase tracking-wider">CVaR 95%</div>
            <div className="text-sm font-bold font-mono text-accent-red">
              {(mc.CVaR_95 * 100).toFixed(3)}%
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

/* ── Main Component ────────────────────────────────────────────────── */

export const BacktestPanel = memo(function BacktestPanel() {
  const toast = useToast();
  const [model, setModel] = useState('all');
  const [period, setPeriod] = useState('3mo');
  const [interval, setInterval_] = useState('15m');
  const [monteCarlo, setMonteCarlo] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await backtestAPI.run({
        model,
        period,
        interval,
        include_monte_carlo: monteCarlo,
      });
      setResult(res);
      toast.success(`Backtest done — ${res.data_bars} bars, ${res.period}/${res.interval}`);
    } catch (err: unknown) {
      toast.error(`Backtest failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setRunning(false);
    }
  }, [model, period, interval, monteCarlo, toast]);

  // Extract model results from result
  const modelResults = result
    ? (['xgb', 'lstm', 'dqn', 'ensemble'] as const)
        .filter(m => result[m] && !result[m].error)
        .map(m => ({ name: m, data: result[m]! }))
    : [];

  const modelErrors = result
    ? (['xgb', 'lstm', 'dqn', 'ensemble'] as const)
        .filter(m => result[m]?.error)
        .map(m => ({ name: m, data: result[m]! }))
    : [];

  return (
    <div className="space-y-4">
      {/* Config form */}
      <div className="flex items-end gap-3 flex-wrap">
        {/* Model */}
        <div>
          <label className="text-[10px] text-th-muted uppercase tracking-wider block mb-1">Model</label>
          <select value={model} onChange={e => setModel(e.target.value)} disabled={running}
            className="bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs text-th-secondary outline-none focus:border-accent-blue/50 transition-colors">
            {MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </div>

        {/* Period */}
        <div>
          <label className="text-[10px] text-th-muted uppercase tracking-wider block mb-1">Period</label>
          <select value={period} onChange={e => setPeriod(e.target.value)} disabled={running}
            className="bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs text-th-secondary outline-none focus:border-accent-blue/50 transition-colors">
            {PERIODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>

        {/* Interval */}
        <div>
          <label className="text-[10px] text-th-muted uppercase tracking-wider block mb-1">Interval</label>
          <select value={interval} onChange={e => setInterval_(e.target.value)} disabled={running}
            className="bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs text-th-secondary outline-none focus:border-accent-blue/50 transition-colors">
            {INTERVALS.map(i => <option key={i.value} value={i.value}>{i.label}</option>)}
          </select>
        </div>

        {/* Monte Carlo toggle */}
        <label className="flex items-center gap-1.5 text-xs text-th-secondary cursor-pointer select-none">
          <input type="checkbox" checked={monteCarlo} onChange={e => setMonteCarlo(e.target.checked)}
            disabled={running}
            className="rounded border-dark-secondary accent-accent-purple" />
          Monte Carlo
        </label>

        {/* Run button */}
        <button
          onClick={() => void handleRun()}
          disabled={running}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium transition-all bg-accent-green/12 text-accent-green border border-accent-green/25 hover:bg-accent-green/20 disabled:opacity-50"
        >
          {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          {running ? 'Running...' : 'Run Backtest'}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="space-y-3">
          {/* Summary bar */}
          <div className="flex items-center gap-3 text-[10px] text-th-muted">
            <Activity size={10} />
            <span>{result.data_bars} bars</span>
            <span className="text-th-dim">|</span>
            <span>{result.period} / {result.interval}</span>
            <span className="text-th-dim">|</span>
            <span>{modelResults.length} model{modelResults.length !== 1 ? 's' : ''}</span>
          </div>

          {/* Model cards */}
          {modelResults.map(({ name, data }) => (
            <ModelCard key={name} name={name} result={data} />
          ))}

          {/* Errors */}
          {modelErrors.map(({ name, data }) => (
            <ModelCard key={name} name={name} result={data} />
          ))}

          {/* Monte Carlo */}
          {result.monte_carlo && <MonteCarloCard mc={result.monte_carlo} />}
        </div>
      )}
    </div>
  );
});
