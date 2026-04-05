/**
 * src/components/dashboard/AnalysisPanel.tsx - QUANT PRO Analysis
 */

import { useEffect, useState, useRef } from 'react';
import { AlertCircle, RefreshCw, Zap, Clock } from 'lucide-react';
import { analysisAPI } from '../../api/client';
import { MarkdownText } from '../ui/MarkdownText';

interface AnalysisData {
  timeframe: string;
  smc_analysis: {
    trend: string;
    structure: string;
    fvg: string;
    rsi: number;
    order_block: number | null;
    current_price: number;
  };
  ai_assessment: string;
  position: {
    direction: string;
    entry: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    lot_size: number | null;
    pattern: string;
  };
}

const fmt = (val: number | null | undefined, decimals = 2): string =>
  val != null ? val.toFixed(decimals) : '—';

export function AnalysisPanel() {
  const [analysis, setAnalysis] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTF, setSelectedTF] = useState('15m');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const isFirstLoad = useRef(true);

  const fetchAnalysis = async (tf: string, forceRefresh = false) => {
    try {
      if (isFirstLoad.current) setLoading(true);
      else setRefreshing(true);
      setError(null);
      const response = await analysisAPI.getQuantPro(tf, forceRefresh);
      setAnalysis(response);
      setLastUpdated(new Date());
      isFirstLoad.current = false;
    } catch (err: unknown) {
      const msg =
        err instanceof Error && err.message?.includes('timeout')
          ? 'Analysis timeout — backend is processing. Try again in a moment.'
          : 'Failed to fetch analysis';
      if (isFirstLoad.current) setError(msg);
      console.error(err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void fetchAnalysis(selectedTF);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTF]);

  if (loading && !analysis) {
    return (
      <div className="card">
        <h2 className="section-title mb-3">Analysis</h2>
        <div className="flex items-center justify-center h-48 text-gray-500 text-sm gap-2">
          <RefreshCw className="animate-spin" size={14} />
          Analyzing market...
        </div>
      </div>
    );
  }

  if (error && !analysis) {
    return (
      <div className="card">
        <h2 className="section-title mb-3">Analysis</h2>
        <div className="flex items-center justify-center h-48 text-red-400 text-xs gap-2">
          <AlertCircle size={16} /> {error}
        </div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="card">
        <h2 className="section-title mb-3">Analysis</h2>
        <div className="text-center text-gray-500 text-sm">No data</div>
      </div>
    );
  }

  const { smc_analysis, position, ai_assessment } = analysis;
  const trendColor = smc_analysis.trend === 'bull' ? 'text-green-400' : 'text-red-400';

  return (
    <div className="card relative">
      {refreshing && (
        <div className="absolute top-3 right-3 flex items-center gap-1 text-xs text-gray-500 z-10">
          <RefreshCw size={10} className="animate-spin" /> updating…
        </div>
      )}

      <div className="flex items-center justify-between mb-3">
        <h2 className="section-title">Analysis</h2>
        <div className="flex gap-1.5">
          {['5m', '15m', '1h', '4h'].map(tf => (
            <button
              key={tf}
              onClick={() => setSelectedTF(tf)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                selectedTF === tf
                  ? 'bg-green-600 text-white'
                  : 'bg-dark-secondary text-gray-400 hover:text-gray-300'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {/* SMC Grid */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
            <div className="text-xs text-gray-500 mb-0.5">Trend</div>
            <div className={`text-sm font-bold ${trendColor}`}>{smc_analysis.trend.toUpperCase()}</div>
          </div>
          <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
            <div className="text-xs text-gray-500 mb-0.5">Structure</div>
            <div className="text-sm font-bold text-blue-400">{smc_analysis.structure}</div>
          </div>
          <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
            <div className="text-xs text-gray-500 mb-0.5">RSI</div>
            <div className="text-sm font-bold text-purple-400">{fmt(smc_analysis.rsi, 1)}</div>
          </div>
          <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
            <div className="text-xs text-gray-500 mb-0.5">FVG</div>
            <div className="text-xs font-bold text-amber-400">{smc_analysis.fvg}</div>
          </div>
        </div>

        {/* Position */}
        <div className="bg-dark-bg rounded-lg p-3 border border-dark-secondary">
          <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">Position</div>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-400">Direction</span>
              <span className={`font-bold ${position.direction === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>{position.direction}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Entry</span>
              <span className="font-mono text-blue-400">${fmt(position.entry)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">SL</span>
              <span className="font-mono text-red-400">${fmt(position.stop_loss)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">TP</span>
              <span className="font-mono text-green-400">${fmt(position.take_profit)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Lot</span>
              <span className="font-mono text-purple-400">{fmt(position.lot_size)}</span>
            </div>
          </div>
        </div>

        {/* AI Assessment */}
        <div className="bg-dark-bg rounded p-3 border border-dark-secondary">
          <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider flex items-center gap-1.5">
            <Zap size={12} /> AI Assessment
          </div>
          <div className="text-sm text-gray-300">
            <MarkdownText text={ai_assessment} />
          </div>
        </div>

        {/* Refresh */}
        <button
          onClick={() => { void fetchAnalysis(selectedTF, true); }}
          disabled={loading || refreshing}
          className="w-full py-2 bg-green-600 hover:bg-green-500 text-white text-sm font-medium rounded transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={`inline mr-1.5 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? 'Analyzing...' : 'Refresh Analysis'}
        </button>

        {lastUpdated && !refreshing && (
          <div className="flex items-center gap-1 text-xs text-gray-600 justify-center">
            <Clock size={10} />
            {lastUpdated.toLocaleTimeString('pl-PL')}
            <span className="text-gray-700 ml-1">(cache 5min)</span>
          </div>
        )}
      </div>
    </div>
  );
}
