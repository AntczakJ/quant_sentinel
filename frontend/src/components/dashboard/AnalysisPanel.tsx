/**
 * src/components/dashboard/AnalysisPanel.tsx - QUANT PRO Analysis & Bot Features
 */

import { useEffect, useState } from 'react';
import { AlertCircle, RefreshCw, Zap } from 'lucide-react';
import axios from 'axios';

interface AnalysisData {
  timeframe: string;
  smc_analysis: {
    trend: string;
    structure: string;
    fvg: string;
    rsi: number;
    order_block: number;
    current_price: number;
  };
  ai_assessment: string;
  position: {
    direction: string;
    entry: number;
    stop_loss: number;
    take_profit: number;
    lot_size: number;
    pattern: string;
  };
}

const API_BASE = 'http://localhost:8000/api';

export function AnalysisPanel() {
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTF, setSelectedTF] = useState('15m');

  const fetchAnalysis = async (tf: string) => {
    try {
      setLoading(true);
      setError(null);
      const response = await axios.get(`${API_BASE}/analysis/quant-pro?tf=${tf}`);
      setAnalysis(response.data);
    } catch (err) {
      setError('Failed to fetch analysis');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalysis(selectedTF);
  }, [selectedTF]);

  if (loading) {
    return (
      <div className="card">
        <h2 className="section-title mb-4">🎯 QUANT PRO ANALYSIS</h2>
        <div className="flex items-center justify-center h-64 text-gray-400">
          <RefreshCw className="animate-spin mr-2" />
          <span>Analyzing market...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <h2 className="section-title mb-4">🎯 QUANT PRO ANALYSIS</h2>
        <div className="flex items-center justify-center h-64 bg-red-900/10 border border-red-500/30 rounded-lg">
          <div className="flex items-center gap-2 text-red-400">
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        </div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="card">
        <h2 className="section-title mb-4">🎯 QUANT PRO ANALYSIS</h2>
        <div className="text-center text-gray-400">No data available</div>
      </div>
    );
  }

  const { smc_analysis, position, ai_assessment } = analysis;
  const trendColor = smc_analysis.trend === 'bull' ? 'text-accent-green' : 'text-accent-red';
  const directionIcon = position.direction === 'LONG' ? '📈' : '📉';

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="section-title">🎯 QUANT PRO ANALYSIS</h2>
        <div className="flex gap-2">
          {['5m', '15m', '1h', '4h'].map(tf => (
            <button
              key={tf}
              onClick={() => setSelectedTF(tf)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all ${
                selectedTF === tf
                  ? 'bg-accent-green text-black'
                  : 'bg-dark-secondary text-gray-300 hover:bg-dark-secondary/80'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        {/* SMC Analysis */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-dark-bg rounded p-3">
            <div className="text-xs text-gray-400 mb-1">Trend</div>
            <div className={`text-lg font-bold ${trendColor}`}>
              {smc_analysis.trend.toUpperCase()}
            </div>
          </div>
          <div className="bg-dark-bg rounded p-3">
            <div className="text-xs text-gray-400 mb-1">Structure</div>
            <div className="text-lg font-bold text-accent-blue">
              {smc_analysis.structure}
            </div>
          </div>
          <div className="bg-dark-bg rounded p-3">
            <div className="text-xs text-gray-400 mb-1">RSI</div>
            <div className="text-lg font-bold text-accent-purple">
              {smc_analysis.rsi.toFixed(1)}
            </div>
          </div>
          <div className="bg-dark-bg rounded p-3">
            <div className="text-xs text-gray-400 mb-1">FVG</div>
            <div className="text-sm font-bold text-accent-orange">
              {smc_analysis.fvg}
            </div>
          </div>
        </div>

        {/* Trade Position */}
        <div className="bg-dark-secondary bg-opacity-50 rounded-lg p-4 border border-dark-secondary">
          <div className="text-xs text-gray-400 mb-3 font-semibold uppercase">Trade Position</div>
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-300">Direction:</span>
              <span className={`text-lg font-bold ${position.direction === 'LONG' ? 'text-accent-green' : 'text-accent-red'}`}>
                {directionIcon} {position.direction}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-300">Entry:</span>
              <span className="text-sm font-mono text-accent-blue">${position.entry.toFixed(2)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-300">Stop Loss:</span>
              <span className="text-sm font-mono text-accent-red">${position.stop_loss.toFixed(2)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-300">Take Profit:</span>
              <span className="text-sm font-mono text-accent-green">${position.take_profit.toFixed(2)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-300">Lot Size:</span>
              <span className="text-sm font-mono text-accent-purple">{position.lot_size.toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* AI Assessment */}
        <div className="bg-dark-bg rounded p-3 border border-dark-secondary border-opacity-50">
          <div className="text-xs text-gray-400 mb-2 font-semibold uppercase flex items-center gap-2">
            <Zap size={14} />
            AI Assessment
          </div>
          <p className="text-sm text-gray-300 leading-relaxed">{ai_assessment}</p>
        </div>

        {/* Refresh Button */}
        <button
          onClick={() => fetchAnalysis(selectedTF)}
          disabled={loading}
          className="w-full py-2 px-4 bg-accent-green hover:bg-accent-green-dark text-black font-semibold rounded-lg transition-all disabled:opacity-50"
        >
          <RefreshCw size={16} className="inline mr-2" />
          Refresh Analysis
        </button>
      </div>
    </div>
  );
}


