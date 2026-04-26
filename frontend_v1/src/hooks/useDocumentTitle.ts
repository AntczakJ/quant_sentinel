/**
 * useDocumentTitle.ts — Updates browser tab title with live XAU/USD price
 *
 * Format: "XAU/USD $3,245.67 (+0.15%) — Quant Sentinel"
 * Reverts to default title when component unmounts.
 */

import { useEffect } from 'react';
import { useTradingStore } from '../store/tradingStore';

const DEFAULT_TITLE = 'Quant Sentinel — AI Trading';

export function useDocumentTitle() {
  const ticker = useTradingStore(s => s.ticker);

  useEffect(() => {
    if (!ticker?.price) {
      document.title = DEFAULT_TITLE;
      return;
    }

    const price = ticker.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const sign = ticker.change_pct >= 0 ? '+' : '';
    const pct = `${sign}${ticker.change_pct.toFixed(2)}%`;
    const arrow = ticker.change_pct >= 0 ? '▲' : '▼';

    document.title = `${arrow} $${price} (${pct}) — Quant Sentinel`;

    return () => { document.title = DEFAULT_TITLE; };
  }, [ticker?.price, ticker?.change_pct]);
}
