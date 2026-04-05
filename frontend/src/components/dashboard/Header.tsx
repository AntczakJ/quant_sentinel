/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price
 */

import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { ScrollProgressBar } from './ScrollProgressBar';

export function Header() {
  const { ticker, apiConnected } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);

  useEffect(() => {
    if (!ticker) return;
    if (prevPrice !== null) {
      if (ticker.price > prevPrice) setPriceFlash('up');
      else if (ticker.price < prevPrice) setPriceFlash('down');
      setTimeout(() => setPriceFlash(null), 300);
    }
    setPrevPrice(ticker.price);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker?.price]);

  if (!ticker) {
    return (
      <header className="sticky top-0 z-50 bg-dark-surface border-b border-dark-secondary">
        <div className="px-6 py-3 text-center text-gray-500 text-sm">Loading...</div>
      </header>
    );
  }

  const isPositive = ticker.change >= 0;

  return (
    <header className="sticky top-0 z-50 bg-dark-surface/95 backdrop-blur-sm border-b border-dark-secondary">
      <div className="px-4 lg:px-6 py-3 flex items-center justify-between gap-6 max-w-[1600px] mx-auto">

        {/* Logo */}
        <div className="flex items-center gap-3 min-w-max">
          <span className="text-lg font-bold text-white tracking-wide">QUANT</span>
          <span className="text-lg font-bold text-green-400 tracking-wide">SENTINEL</span>
          <span className="text-xs text-gray-500 ml-1 hidden sm:block">{ticker.symbol}</span>
        </div>

        {/* Price */}
        <div className={`flex-1 text-center transition-colors duration-200 ${priceFlash === 'up' ? 'text-green-400' : priceFlash === 'down' ? 'text-red-400' : ''}`}>
          <div className="text-2xl lg:text-3xl font-bold font-mono text-white">
            ${ticker.price.toFixed(2)}
          </div>
          <div className={`flex items-center justify-center gap-1.5 text-xs font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            <span>
              {isPositive ? '+' : ''}{ticker.change.toFixed(2)} ({isPositive ? '+' : ''}{ticker.change_pct.toFixed(2)}%)
            </span>
          </div>
        </div>

        {/* Status */}
        <div className="text-right min-w-max">
          <div className={`flex items-center justify-end gap-1.5 text-xs font-medium ${apiConnected ? 'text-green-400' : 'text-red-400'}`}>
            <div className={`w-1.5 h-1.5 rounded-full ${apiConnected ? 'bg-green-400' : 'bg-red-400'}`} />
            <span>{apiConnected ? 'API' : 'Offline'}</span>
          </div>
        </div>
      </div>
      {/* Pasek postępu scrolla – pod całym headerem */}
      <ScrollProgressBar />
    </header>
  );
}
