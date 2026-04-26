/**
 * src/components/dashboard/ModelStats.tsx - Machine learning models performance
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { modelsAPI } from '../../api/client';
import type { AllModelsStats } from '../../types/trading';
import { Brain } from 'lucide-react';
import { useToast } from '../ui/Toast';

interface StatRowProps {
  label: string;
  value: number | string | undefined;
  format?: 'percent' | 'number' | 'text';
  color?: string;
}

function StatRow({ label, value, format = 'text', color }: StatRowProps) {
  let displayValue = '-';

  if (value !== undefined && value !== null) {
    if (format === 'percent') {
      displayValue = `${(value as number * 100).toFixed(1)}%`;
    } else if (format === 'number') {
      displayValue = (value as number).toFixed(3);
    } else {
      displayValue = String(value);
    }
  }

  return (
    <div className="flex justify-between items-center text-xs">
      <span className="text-th-secondary">{label}</span>
      <span className={color || 'text-accent-blue'}>{displayValue}</span>
    </div>
  );
}

export const ModelStats = memo(function ModelStats() {
  const toast = useToast();
  const { setModelsStats, apiConnected } = useTradingStore();
  const [stats, setStatsState] = useState<AllModelsStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiConnected) {return;}
    const fetchStats = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await modelsAPI.getStats();
        setStatsState(data);
        setModelsStats(data);
      } catch {
        toast.error('Failed to load model stats');
        setError('Failed to load model stats');
      } finally {
        setLoading(false);
      }
    };

    void fetchStats();

    const interval = setInterval(fetchStats, 90000);
    return () => clearInterval(interval);
  }, [setModelsStats, apiConnected]);

  if (loading && !stats) {
    return (
      <div className="space-y-3">
        {[1,2,3].map(i => <div key={i} className="skeleton-shimmer h-20 rounded-lg" />)}
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="text-center text-accent-red text-xs">{error}</div>
    );
  }

  if (!stats) { return null; }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="text-xs text-th-secondary font-bold flex items-center gap-2">
        <Brain size={14} />
        ML MODELS PERFORMANCE
      </div>

      {/* Ensemble Accuracy */}
      {stats.ensemble_accuracy !== undefined && (
        <div className="bg-dark-bg border border-accent-purple/20 rounded p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-th-secondary">Ensemble Accuracy</span>
            <span className="text-xl font-bold text-accent-purple">
              {(stats.ensemble_accuracy * 100).toFixed(1)}%
            </span>
          </div>
          <div className="bg-dark-secondary rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full bg-accent-purple transition-all"
              style={{ width: `${Math.min(stats.ensemble_accuracy * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* RL Agent Stats */}
      <div className="bg-dark-bg border border-dark-secondary rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-accent-blue"></div>
            <span className="text-sm font-bold text-th-secondary">RL Agent</span>
          </div>
          {stats.rl_stats?.episodes !== undefined && (
            <span className="text-xs text-th-muted">Episodes: {stats.rl_stats.episodes}</span>
          )}
        </div>

        <div className="space-y-1">
          {stats.rl_stats?.win_rate !== undefined && (
            <StatRow
              label="Win Rate"
              value={stats.rl_stats.win_rate}
              format="percent"
              color={stats.rl_stats.win_rate > 0.5 ? 'text-accent-green' : 'text-accent-red'}
            />
          )}
          {stats.rl_stats?.epsilon !== undefined && (
            <StatRow
              label="Epsilon"
              value={stats.rl_stats.epsilon}
              format="number"
            />
          )}
          {stats.rl_stats?.last_training && (
            <StatRow
              label="Last Training"
              value={new Date(stats.rl_stats.last_training).toLocaleDateString()}
              format="text"
            />
          )}
        </div>
      </div>

      {/* LSTM Stats */}
      <div className="bg-dark-bg border border-dark-secondary rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-accent-purple"></div>
            <span className="text-sm font-bold text-th-secondary">LSTM</span>
          </div>
        </div>

        <div className="space-y-1">
          {stats.lstm_stats.accuracy !== undefined && (
            <StatRow
              label="Accuracy"
              value={stats.lstm_stats.accuracy}
              format="percent"
              color={stats.lstm_stats.accuracy > 0.5 ? 'text-accent-green' : 'text-accent-red'}
            />
          )}
          {stats.lstm_stats.precision !== undefined && (
            <StatRow
              label="Precision"
              value={stats.lstm_stats.precision}
              format="percent"
            />
          )}
          {stats.lstm_stats.recall !== undefined && (
            <StatRow
              label="Recall"
              value={stats.lstm_stats.recall}
              format="percent"
            />
          )}
        </div>
      </div>

      {/* XGBoost Stats */}
      <div className="bg-dark-bg border border-dark-secondary rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-accent-orange"></div>
            <span className="text-sm font-bold text-th-secondary">XGBoost</span>
          </div>
        </div>

        <div className="space-y-1">
          {stats.xgb_stats.accuracy !== undefined && (
            <StatRow
              label="Accuracy"
              value={stats.xgb_stats.accuracy}
              format="percent"
              color={stats.xgb_stats.accuracy > 0.5 ? 'text-accent-green' : 'text-accent-red'}
            />
          )}
          {stats.xgb_stats.precision !== undefined && (
            <StatRow
              label="Precision"
              value={stats.xgb_stats.precision}
              format="percent"
            />
          )}
          {stats.xgb_stats.recall !== undefined && (
            <StatRow
              label="Recall"
              value={stats.xgb_stats.recall}
              format="percent"
            />
          )}
        </div>
      </div>

      {/* Last Update */}
      <div className="text-xs text-th-muted pt-2 border-t border-dark-secondary text-center">
        Updated: {new Date(stats.last_update).toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        })}
      </div>
    </div>
  );
});
