/**
 * pages/ModelsPage.tsx — ML Models performance + training controls + Ensemble
 */

import { useState } from 'react';
import { ModelStats, RiskMetrics, ModelDriftAlert, BacktestPanel } from '../components/dashboard';
import { trainingAPI } from '../api/client';
import { Play, Loader2, CheckCircle, XCircle } from 'lucide-react';

function TrainingControls() {
  const [training, setTraining] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const handleStartTraining = async () => {
    setTraining(true);
    setResult(null);
    try {
      const res = await trainingAPI.start(100, true);
      setResult({ ok: true, msg: res.message ?? 'Training started' });
    } catch (err) {
      setResult({ ok: false, msg: err instanceof Error ? err.message : 'Training failed' });
    } finally {
      setTraining(false);
    }
  };

  return (
    <div className="space-y-3">
      <button
        onClick={() => { void handleStartTraining(); }}
        disabled={training}
        className="w-full py-2.5 bg-accent-purple hover:brightness-110 disabled:opacity-50 text-white text-sm font-medium rounded transition-all flex items-center justify-center gap-2"
      >
        {training ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        {training ? 'Trenowanie...' : 'Start Training (100 episodes)'}
      </button>

      {result && (
        <div className={`p-2 rounded text-xs flex items-center gap-1.5 ${
          result.ok
            ? 'bg-accent-green/15 border border-accent-green/30 text-accent-green'
            : 'bg-accent-red/15 border border-accent-red/30 text-accent-red'
        }`}>
          {result.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {result.msg}
        </div>
      )}

      <div className="space-y-3 text-sm text-th-secondary">
        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-th-muted mb-2 font-medium uppercase tracking-wider">Jak trenowac</div>
          <div className="space-y-1.5 text-xs">
            <p><code>python train_all.py --rl-episodes 200</code></p>
            <p className="text-th-muted">Trenuje XGBoost &rarr; LSTM &rarr; DQN &rarr; Bayesian Opt &rarr; Backtest</p>
          </div>
        </div>

        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-th-muted mb-2 font-medium uppercase tracking-wider">Pipeline</div>
          <div className="space-y-1 text-xs text-th-muted">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-orange" />
              <span>XGBoost — feature importance + walk-forward</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-purple" />
              <span>LSTM — sequence prediction + validation</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-blue" />
              <span>DQN RL Agent — reward-based episodes</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-orange" />
              <span>Bayesian Optimization — risk param tuning</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-accent-green" />
              <span>Backtest — full equity simulation</span>
            </div>
          </div>
        </div>

        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-th-muted mb-2 font-medium uppercase tracking-wider">Self-Learning</div>
          <p className="text-xs text-th-muted">
            System automatycznie uczy sie z wynikow transakcji — aktualizuje wagi wzorcow,
            czynnikow i parametrow ryzyka co 15 min przez scheduled jobs.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ModelsPage() {
  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      {/* Model Health Alert — full width banner */}
      <div className="card">
        <h2 className="section-title mb-3">
          Model Health Monitor
          <span className="text-xs text-th-muted font-normal ml-2">— drift, accuracy, calibration</span>
        </h2>
        <ModelDriftAlert />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <h2 className="section-title mb-3">ML Models</h2>
          <ModelStats />
        </div>

        <div className="card">
          <h2 className="section-title mb-3">Training</h2>
          <TrainingControls />
        </div>
      </div>

      {/* Backtesting */}
      <div className="card">
        <h2 className="section-title mb-3">
          Backtesting
          <span className="text-xs text-th-muted font-normal ml-2">— model performance on historical data</span>
        </h2>
        <BacktestPanel />
      </div>

      {/* Risk metrics row */}
      <div className="card">
        <h2 className="section-title mb-3">
          Trading Performance
          <span className="text-xs text-th-muted font-normal ml-2">— ML-enhanced metrics</span>
        </h2>
        <RiskMetrics />
      </div>
    </div>
  );
}
