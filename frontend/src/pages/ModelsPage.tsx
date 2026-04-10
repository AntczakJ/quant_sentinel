/**
 * pages/ModelsPage.tsx — ML Models performance + training controls + Ensemble
 * Uses DraggableGrid for customizable panel layout.
 */

import { useState, useMemo } from 'react';
import { ModelStats, RiskMetrics, ModelDriftAlert, BacktestPanel } from '../components/dashboard';
import { DraggableGrid, type GridWidget } from '../components/layout/DraggableGrid';
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
          <div className="text-xs text-th-muted mb-2 font-medium uppercase tracking-wider">Pipeline</div>
          <div className="space-y-1 text-xs text-th-muted">
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-accent-orange" /><span>XGBoost — feature importance</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-accent-purple" /><span>LSTM — sequence prediction</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-accent-blue" /><span>DQN RL Agent — reward-based</span></div>
            <div className="flex items-center gap-2"><div className="w-2 h-2 rounded-full bg-accent-green" /><span>Backtest — equity simulation</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ModelsPage() {
  const widgets: GridWidget[] = useMemo(() => [
    {
      id: 'health-monitor',
      title: 'Model Health Monitor',
      content: <ModelDriftAlert />,
      defaultLayout: { x: 0, y: 0, w: 12, h: 3, minW: 6, minH: 2 },
    },
    {
      id: 'ml-models',
      title: 'ML Models',
      content: <ModelStats />,
      defaultLayout: { x: 0, y: 3, w: 6, h: 5, minW: 4, minH: 3 },
    },
    {
      id: 'training',
      title: 'Training',
      content: <TrainingControls />,
      defaultLayout: { x: 6, y: 3, w: 6, h: 5, minW: 4, minH: 3 },
    },
    {
      id: 'backtesting',
      title: 'Backtesting',
      content: <BacktestPanel />,
      defaultLayout: { x: 0, y: 8, w: 12, h: 5, minW: 6, minH: 3 },
    },
    {
      id: 'performance',
      title: 'Trading Performance',
      content: <RiskMetrics />,
      defaultLayout: { x: 0, y: 13, w: 12, h: 5, minW: 6, minH: 3 },
    },
  ], []);

  return (
    <div className="max-w-[1600px] mx-auto">
      <DraggableGrid pageKey="models" widgets={widgets} rowHeight={70} />
    </div>
  );
}
