/**
 * src/store/tradingStore.ts - Global trading state management with Zustand
 */

import { create } from 'zustand';
import type { Ticker, Signal, Portfolio, AllModelsStats } from '../types/trading';

interface TradingStore {
  // Market data
  ticker: Ticker | null;
  setTicker: (ticker: Ticker) => void;

  // Signals
  currentSignal: Signal | null;
  setCurrentSignal: (signal: Signal) => void;

  // Portfolio
  portfolio: Portfolio | null;
  setPortfolio: (portfolio: Portfolio) => void;

  // Models stats
  modelsStats: AllModelsStats | null;
  setModelsStats: (stats: AllModelsStats) => void;

  // UI state
  selectedInterval: string;
  setSelectedInterval: (interval: string) => void;


  // API status
  apiConnected: boolean;
  setApiConnected: (connected: boolean) => void;

  // Price history for charts
  priceHistory: { time: string; price: number }[];
  addPriceHistory: (time: string, price: number) => void;
  clearPriceHistory: () => void;
}

export const useTradingStore = create<TradingStore>((set) => ({
  // Market data
  ticker: null,
  setTicker: (ticker) => set({ ticker }),

  // Signals
  currentSignal: null,
  setCurrentSignal: (signal) => set({ currentSignal: signal }),

  // Portfolio
  portfolio: null,
  setPortfolio: (portfolio) => set({ portfolio }),

  // Models stats
  modelsStats: null,
  setModelsStats: (stats) => set({ modelsStats: stats }),

  // UI state
  selectedInterval: '15m',
  setSelectedInterval: (interval) => set({ selectedInterval: interval }),


  // API status
  apiConnected: false,
  setApiConnected: (connected) => set({ apiConnected: connected }),

  // Price history
  priceHistory: [],
  addPriceHistory: (time, price) =>
    set((state) => ({
      priceHistory: [...state.priceHistory.slice(-199), { time, price }],
    })),
  clearPriceHistory: () => set({ priceHistory: [] }),
}));

