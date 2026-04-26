/**
 * usePriceAlerts.ts — Price alert system with localStorage persistence
 *
 * Stores alerts as price levels. When the ticker price crosses an alert level,
 * triggers a toast notification and marks the alert as triggered.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTradingStore } from '../store/tradingStore';

export interface PriceAlert {
  id: string;
  price: number;
  direction: 'above' | 'below';
  createdAt: number;
  triggered: boolean;
}

const STORAGE_KEY = 'qs:price-alerts';

function loadAlerts(): PriceAlert[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveAlerts(alerts: PriceAlert[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(alerts));
  } catch { /* quota exceeded */ }
}

export function usePriceAlerts(onTrigger?: (alert: PriceAlert) => void) {
  const [alerts, setAlerts] = useState<PriceAlert[]>(loadAlerts);
  const prevPrice = useRef<number | null>(null);
  const ticker = useTradingStore(s => s.ticker);

  // Persist on change
  useEffect(() => { saveAlerts(alerts); }, [alerts]);

  // Check price crossings
  useEffect(() => {
    if (!ticker?.price) {return;}
    const price = ticker.price;
    const prev = prevPrice.current;
    prevPrice.current = price;
    if (prev === null) {return;}

    setAlerts(current => {
      let changed = false;
      const updated = current.map(a => {
        if (a.triggered) {return a;}
        const crossed =
          (a.direction === 'above' && prev < a.price && price >= a.price) ||
          (a.direction === 'below' && prev > a.price && price <= a.price);
        if (crossed) {
          changed = true;
          onTrigger?.({ ...a, triggered: true });
          return { ...a, triggered: true };
        }
        return a;
      });
      return changed ? updated : current;
    });
  }, [ticker?.price, onTrigger]);

  const addAlert = useCallback((price: number, currentPrice: number) => {
    const direction = price > currentPrice ? 'above' : 'below';
    const alert: PriceAlert = {
      id: `alert-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      price,
      direction,
      createdAt: Date.now(),
      triggered: false,
    };
    setAlerts(prev => [...prev, alert]);
    return alert;
  }, []);

  const removeAlert = useCallback((id: string) => {
    setAlerts(prev => prev.filter(a => a.id !== id));
  }, []);

  const clearTriggered = useCallback(() => {
    setAlerts(prev => prev.filter(a => !a.triggered));
  }, []);

  const activeAlerts = alerts.filter(a => !a.triggered);

  return { alerts, activeAlerts, addAlert, removeAlert, clearTriggered };
}
