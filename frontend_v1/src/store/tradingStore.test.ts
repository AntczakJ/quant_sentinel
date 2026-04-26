import { describe, it, expect, beforeEach } from 'vitest';
import { useTradingStore } from './tradingStore';

describe('tradingStore', () => {
  beforeEach(() => {
    useTradingStore.setState({
      ticker: null,
      currentSignal: null,
      portfolio: null,
      modelsStats: null,
      selectedInterval: '15m',
      apiConnected: false,
      priceHistory: [],
    });
  });

  it('initializes with default values', () => {
    const state = useTradingStore.getState();
    expect(state.ticker).toBeNull();
    expect(state.selectedInterval).toBe('15m');
    expect(state.apiConnected).toBe(false);
    expect(state.priceHistory).toEqual([]);
  });

  it('setTicker updates ticker', () => {
    const ticker = { symbol: 'XAU/USD', price: 3200, change: 5, change_pct: 0.15, high_24h: 3210, low_24h: 3180, timestamp: '2026-04-10T12:00:00Z' };
    useTradingStore.getState().setTicker(ticker as any);
    expect(useTradingStore.getState().ticker).toEqual(ticker);
  });

  it('setSelectedInterval updates interval', () => {
    useTradingStore.getState().setSelectedInterval('1h');
    expect(useTradingStore.getState().selectedInterval).toBe('1h');
  });

  it('setApiConnected updates connection status', () => {
    useTradingStore.getState().setApiConnected(true);
    expect(useTradingStore.getState().apiConnected).toBe(true);
  });

  it('addPriceHistory appends and caps at 200', () => {
    const store = useTradingStore.getState();
    for (let i = 0; i < 210; i++) {
      store.addPriceHistory(`2026-04-10T${String(i).padStart(2, '0')}:00:00Z`, 3000 + i);
    }
    const history = useTradingStore.getState().priceHistory;
    expect(history.length).toBeLessThanOrEqual(200);
    expect(history[history.length - 1].price).toBe(3209);
  });

  it('clearPriceHistory empties the array', () => {
    useTradingStore.getState().addPriceHistory('t1', 3000);
    useTradingStore.getState().clearPriceHistory();
    expect(useTradingStore.getState().priceHistory).toEqual([]);
  });

  it('setPortfolio updates portfolio', () => {
    const portfolio = { balance: 10000, equity: 10500, pnl: 500, initial_balance: 10000 };
    useTradingStore.getState().setPortfolio(portfolio as any);
    expect(useTradingStore.getState().portfolio?.balance).toBe(10000);
  });
});
