/**
 * src/components/charts/CandlestickChart.tsx - Candlestick chart for XAU/USD
 */

import { useEffect, useState } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { marketAPI } from '../../api/client';
import type { Candle, Indicators } from '../../types/trading';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { AlertCircle } from 'lucide-react';

interface CandleChartData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  rsi?: number;
}

export function CandlestickChart() {
  const { selectedInterval } = useTradingStore();
  const [candles, setCandles] = useState<CandleChartData[]>([]);
  const [indicators, setIndicators] = useState<Indicators | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastPrice, setLastPrice] = useState<number | null>(null);

  useEffect(() => {
    const fetchChartData = async () => {
      try {
        setLoading(true);
        setError(null);

        // Fetch candles with 120 second cache
        const candleData = await marketAPI.getCandles('XAU/USD', selectedInterval, 200);

        // Fetch indicators with 120 second cache
        const indicatorData = await marketAPI.getIndicators('XAU/USD', selectedInterval);

        // Check if price changed
        const currentPrice = candleData?.[candleData.length - 1]?.close || lastPrice;

        // Format candles with indicators
        const formatted: CandleChartData[] = candleData.map((candle: Candle) => ({
          time: new Date(candle.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
          volume: candle.volume,
          rsi: indicatorData?.rsi,
        }));

        setCandles(formatted);
        setIndicators(indicatorData);
        setLastPrice(currentPrice);
      } catch (err) {
        console.error('Error fetching chart data:', err);
        setError('Failed to load chart data');
      } finally {
        setLoading(false);
      }
    };

    void fetchChartData();

    // Refresh every 30 seconds for real-time updates during trading hours
    // Will retry faster if market is open and price is changing
    const interval = setInterval(() => {
      void fetchChartData();
    }, 30000);
    return () => clearInterval(interval);
  }, [selectedInterval, lastPrice]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 text-gray-400">
        <span>Loading chart...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96 bg-red-900/10 border border-red-500/30 rounded-lg">
        <div className="flex items-center gap-2 text-red-400">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  const priceData = candles.slice(-50); // Last 50 candles for readability


  return (
    <div className="space-y-4">
      {/* Price Chart */}
      <div className="bg-dark-bg rounded border border-dark-secondary p-3">
        <div className="text-xs text-gray-400 mb-2">Price Action</div>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={priceData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a3a42" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: '#6b7280' }}
              interval={Math.floor(priceData.length / 6)}
            />
            <YAxis
              domain={['dataMin - 5', 'dataMax + 5']}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              width={60}
              tickFormatter={(value: number) => value.toFixed(2)}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #3a4a52', borderRadius: '4px' }}
              formatter={(value: number) => value.toFixed(2)}
              labelStyle={{ color: '#10b981' }}
            />
            <Line
              type="monotone"
              dataKey="close"
              stroke="#10b981"
              dot={false}
              strokeWidth={2}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="high"
              stroke="#3b82f6"
              dot={false}
              strokeWidth={1}
              strokeDasharray="3 3"
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="low"
              stroke="#ef4444"
              dot={false}
              strokeWidth={1}
              strokeDasharray="3 3"
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Volume Chart */}
      <div className="bg-dark-bg rounded border border-dark-secondary p-3">
        <div className="text-xs text-gray-400 mb-2">Volume</div>
        <ResponsiveContainer width="100%" height={100}>
          <BarChart data={priceData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#2a3a42" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: '#6b7280' }}
              interval={Math.floor(priceData.length / 6)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#6b7280' }}
              width={60}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1a2332', border: '1px solid #3a4a52', borderRadius: '4px' }}
              formatter={(value: number) => value.toFixed(0)}
            />
            <Bar
              dataKey="volume"
              fill="#3b82f6"
              opacity={0.6}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

       {/* RSI Indicator */}
       {indicators?.rsi !== undefined && indicators?.rsi !== null && typeof indicators.rsi === 'number' && (
         <div className="bg-dark-bg rounded border border-dark-secondary p-3">
           <div className="text-xs text-gray-400 mb-2">RSI (Relative Strength Index)</div>
           <div className="flex items-center justify-between">
             <div className="flex items-center gap-4">
               <div>
                 <span className={`text-2xl font-bold ${
                   indicators.rsi! > 70 ? 'text-accent-red' :
                   indicators.rsi! < 30 ? 'text-accent-green' :
                   'text-accent-blue'
                 }`}>
                   {indicators.rsi!.toFixed(1)}
                 </span>
               </div>
               <div className="text-xs text-gray-400">
                 <div>{indicators.rsi! > 70 ? '🔴 Overbought' : indicators.rsi! < 30 ? '🟢 Oversold' : '🔵 Neutral'}</div>
               </div>
             </div>
             {/* RSI Progress Bar */}
             <div className="flex-1 ml-4">
               <div className="bg-dark-secondary rounded-full h-2 overflow-hidden">
                 <div
                   className={`h-full transition-all ${
                     indicators.rsi! > 70 ? 'bg-accent-red' :
                     indicators.rsi! < 30 ? 'bg-accent-green' :
                     'bg-accent-blue'
                   }`}
                   style={{ width: `${indicators.rsi!}%` }}
                 />
               </div>
               <div className="flex justify-between text-xs text-gray-500 mt-1">
                 <span>0</span>
                 <span>30</span>
                 <span>70</span>
                 <span>100</span>
               </div>
             </div>
           </div>
         </div>
       )}

      {/* Bolinger Bands */}
      {indicators?.bb_upper && indicators?.bb_middle && indicators?.bb_lower && (
        <div className="bg-dark-bg rounded border border-dark-secondary p-3">
          <div className="text-xs text-gray-400 mb-2">Bollinger Bands</div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-dark-surface rounded p-2">
              <span className="text-gray-400">Upper</span>
              <div className="text-accent-red font-bold">${indicators.bb_upper.toFixed(2)}</div>
            </div>
            <div className="bg-dark-surface rounded p-2">
              <span className="text-gray-400">Middle</span>
              <div className="text-accent-blue font-bold">${indicators.bb_middle.toFixed(2)}</div>
            </div>
            <div className="bg-dark-surface rounded p-2">
              <span className="text-gray-400">Lower</span>
              <div className="text-accent-green font-bold">${indicators.bb_lower.toFixed(2)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

