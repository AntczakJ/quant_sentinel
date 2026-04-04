/**
 * src/components/dashboard/Header.tsx - Dashboard header with live price
 * Optimized: Uses cached ticker instead of making new requests
 */

import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Radio } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';

export function Header() {
  const { ticker, apiConnected } = useTradingStore();
  const [prevPrice, setPrevPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<'up' | 'down' | null>(null);

  useEffect(() => {
    // Flash animation on price change only
    if (!ticker) return;

    if (prevPrice !== null) {
      if (ticker.price > prevPrice) {
        setPriceFlash('up');
      } else if (ticker.price < prevPrice) {
        setPriceFlash('down');
      }

      setTimeout(() => setPriceFlash(null), 300);
    }
    setPrevPrice(ticker.price);
  }, [ticker?.price]);

  if (!ticker) {
    return (
      <header className="sticky top-0 z-50 backdrop-blur-xl bg-gradient-to-r from-dark-tertiary via-dark-secondary to-dark-tertiary border-b border-dark-secondary border-opacity-20 shadow-2xl">
        <div className="px-6 py-4 text-center text-gray-400">Loading...</div>
      </header>
    );
  }

  const isPositive = ticker.change >= 0;

  return (
    <header className="sticky top-0 z-50 backdrop-blur-xl bg-gradient-to-r from-dark-tertiary via-dark-secondary to-dark-tertiary border-b border-dark-secondary border-opacity-20 shadow-2xl">
      <div className="px-6 py-4 flex items-center justify-between gap-8">

        {/* Logo and Symbol */}
        <div className="flex items-center gap-4 min-w-max">
          <div className="flex items-center gap-2">
            <div className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-accent-cyan via-accent-green to-accent-purple font-display">
              QUANT
            </div>
            <div className="text-2xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-accent-purple via-accent-blue to-accent-cyan font-display">
              SENTINEL
            </div>
          </div>
          <div className="h-8 w-px bg-gradient-to-b from-transparent via-accent-green to-transparent opacity-50"></div>
          <div className="text-lg font-bold text-accent-cyan font-display">{ticker.symbol}</div>
        </div>

         {/* Price Info - Center (Flex-grow) */}
         <div className={`flex-1 text-center transition-all duration-300 ${priceFlash === 'up' ? 'animate-pulse-blue' : priceFlash === 'down' ? 'animate-pulse' : ''}`}>
           <div className="text-4xl font-bold font-mono glow-text">
             ${ticker.price.toFixed(2)}
           </div>
           <div className={`flex items-center justify-center gap-2 mt-1 font-semibold text-sm ${isPositive ? 'text-accent-green' : 'text-accent-red'}`}>
             {isPositive ? (
               <>
                 <TrendingUp size={16} className="animate-float" />
                 <span>+${ticker.change.toFixed(2)} (+{ticker.change_pct.toFixed(2)}%)</span>
               </>
             ) : (
               <>
                 <TrendingDown size={16} className="animate-float" />
                 <span>-${Math.abs(ticker.change).toFixed(2)} ({ticker.change_pct.toFixed(2)}%)</span>
               </>
             )}
           </div>
         </div>

        {/* Status - Right */}
        <div className="text-right min-w-max">
          <div className="text-xs font-bold text-gray-400 mb-1 uppercase tracking-widest font-display">API Status</div>
          <div className={`flex items-center justify-end gap-2 font-semibold text-sm ${apiConnected ? 'text-accent-green' : 'text-accent-red'}`}>
            <div className={`w-3 h-3 rounded-full ${apiConnected ? 'bg-accent-green animate-pulse glow' : 'bg-accent-red'}`}></div>
            <span className="font-mono">{apiConnected ? 'CONNECTED' : 'DISCONNECTED'}</span>
            <Radio size={14} className={apiConnected ? 'animate-spin' : ''} />
          </div>
        </div>
      </div>

      {/* Divider line with gradient */}
      <div className="h-px w-full bg-gradient-to-r from-transparent via-accent-green to-transparent opacity-20"></div>
    </header>
  );
}

