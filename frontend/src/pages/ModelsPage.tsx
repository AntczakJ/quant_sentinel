/**
 * pages/ModelsPage.tsx — ML Models performance + training controls + Ensemble
 */

import { useState } from 'react';
import { ModelStats, RiskMetrics } from '../components/dashboard';
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
        className="w-full py-2.5 bg-purple-600 hover:bg-purple-500 disabled:bg-purple-800 disabled:opacity-50 text-white text-sm font-medium rounded transition-colors flex items-center justify-center gap-2"
      >
        {training ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
        {training ? 'Trenowanie...' : 'Start Training (100 episodes)'}
      </button>

      {result && (
        <div className={`p-2 rounded text-xs flex items-center gap-1.5 ${
          result.ok
            ? 'bg-green-900/20 border border-green-600/30 text-green-400'
            : 'bg-red-900/20 border border-red-600/30 text-red-400'
        }`}>
          {result.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
          {result.msg}
        </div>
      )}

      <div className="space-y-3 text-sm text-gray-400">
        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Jak trenować</div>
          <div className="space-y-1.5 text-xs">
            <p><code className="bg-dark-secondary px-1.5 py-0.5 rounded text-green-400">python train_all.py --rl-episodes 200</code></p>
            <p className="text-gray-500">Trenuje XGBoost → LSTM → DQN → Bayesian Opt → Backtest</p>
          </div>
        </div>

        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Pipeline</div>
          <div className="space-y-1 text-xs text-gray-500">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-orange-500" />
              <span>XGBoost — feature importance + walk-forward</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-purple-500" />
              <span>LSTM — sequence prediction + validation</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-blue-500" />
              <span>DQN RL Agent — reward-based episodes</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-amber-500" />
              <span>Bayesian Optimization — risk param tuning</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-500" />
              <span>Backtest — full equity simulation</span>
            </div>
          </div>
        </div>

        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Self-Learning</div>
          <p className="text-xs text-gray-500">
            System automatycznie uczy się z wyników transakcji — aktualizuje wagi wzorców,
            czynników i parametrów ryzyka co 15 min przez scheduled jobs.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function ModelsPage() {
  return (
    <div className="space-y-4">
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

      {/* Risk metrics row */}
      <div className="card">
        <h2 className="section-title mb-3">
          Trading Performance
          <span className="text-xs text-gray-500 font-normal ml-2">— ML-enhanced metrics</span>
        </h2>
        <RiskMetrics />
      </div>
    </div>
  );
}


