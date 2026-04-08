/**
 * src/components/dashboard/ModelStats.tsx - Machine learning models performance
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { modelsAPI } from '../../api/client';
import type { AllModelsStats } from '../../types/trading';
import { Brain } from 'lucide-react';

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
      <span className="text-gray-400">{label}</span>
      <span className={color || 'text-accent-blue'}>{displayValue}</span>
    </div>
  );
}

export const ModelStats = memo(function ModelStats() {
  const { setModelsStats, apiConnected } = useTradingStore();
  const [stats, setStatsState] = useState<AllModelsStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!apiConnected) return;
    const fetchStats = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await modelsAPI.getStats();
        setStatsState(data);
        setModelsStats(data);
      } catch (err) {
        console.error('Error fetching model stats:', err);
        setError('Failed to load model stats');
      } finally {
        setLoading(false);
      }
    };

    void fetchStats();

    // Refresh every 90 seconds (model stats barely change)
    const interval = setInterval(fetchStats, 90000);
    return () => clearInterval(interval);
  }, [setModelsStats, apiConnected]);

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading models...</span>
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="text-center text-red-400 text-xs">{error}</div>
    );
  }

  if (!stats) { return null; }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="text-xs text-gray-400 font-bold flex items-center gap-2">
        <Brain size={14} />
        ML MODELS PERFORMANCE
      </div>

      {/* Ensemble Accuracy */}
      {stats.ensemble_accuracy !== undefined && (
        <div className="bg-dark-bg border border-purple-600/20 rounded p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-gray-400">Ensemble Accuracy</span>
            <span className="text-xl font-bold text-purple-400">
              {(stats.ensemble_accuracy * 100).toFixed(1)}%
            </span>
          </div>
          <div className="bg-dark-secondary rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full bg-purple-500 transition-all"
              style={{ width: `${Math.min(stats.ensemble_accuracy * 100, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* RL Agent Stats */}
      <div className="bg-dark-bg border border-dark-secondary rounded p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-blue-500"></div>
            <span className="text-sm font-bold text-gray-300">RL Agent</span>
          </div>
          {stats.rl_stats.episodes !== undefined && (
            <span className="text-xs text-gray-500">Episodes: {stats.rl_stats.episodes}</span>
          )}
        </div>

        <div className="space-y-1">
          {stats.rl_stats.win_rate !== undefined && (
            <StatRow
              label="Win Rate"
              value={stats.rl_stats.win_rate}
              format="percent"
              color={stats.rl_stats.win_rate > 0.5 ? 'text-accent-green' : 'text-accent-red'}
            />
          )}
          {stats.rl_stats.epsilon !== undefined && (
            <StatRow
              label="Epsilon"
              value={stats.rl_stats.epsilon}
              format="number"
            />
          )}
          {stats.rl_stats.last_training && (
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
            <div className="w-2 h-2 rounded-full bg-purple-500"></div>
            <span className="text-sm font-bold text-gray-300">LSTM</span>
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
            <div className="w-2 h-2 rounded-full bg-orange-500"></div>
            <span className="text-sm font-bold text-gray-300">XGBoost</span>
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
      <div className="text-xs text-gray-500 pt-2 border-t border-dark-secondary text-center">
        Updated: {new Date(stats.last_update).toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit'
        })}
      </div>
    </div>
  );
});

