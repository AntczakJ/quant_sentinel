/**
 * src/api/client.ts - API client for backend communication
 */

import axios from 'axios';
import type { AxiosError } from 'axios';
import type { Candle, Ticker, Indicators, Signal, Portfolio, AllModelsStats, TrainingStatus } from '../types/trading';

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000/api';

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000, // 30s default timeout — prevents infinite hangs
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor na errors
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    console.error('API Error:', error.response?.data ?? error.message);
    return Promise.reject(error);
  }
);

// Market endpoints
export const marketAPI = {
  getCandles: async (symbol: string = 'XAU/USD', interval: string = '15m', limit: number = 200) => {
    const response = await client.get<{ candles: Candle[] }>('/market/candles', {
      params: { symbol, interval, limit }
    });
    return response.data.candles;
  },

  getTicker: async (symbol: string = 'XAU/USD') => {
    const response = await client.get<Ticker>('/market/ticker', {
      params: { symbol }
    });
    return response.data;
  },

  getIndicators: async (symbol: string = 'XAU/USD', interval: string = '15m') => {
    const response = await client.get<Indicators>('/market/indicators', {
      params: { symbol, interval }
    });
    return response.data;
  },

  getStatus: async () => {
    const response = await client.get('/market/status');
    return response.data;
  },
};

// Signals endpoints
export const signalsAPI = {
  getCurrent: async () => {
    const response = await client.get<Signal>('/signals/current');
    return response.data;
  },

  getHistory: async (limit: number = 50) => {
    const response = await client.get<{ signals: Signal[] }>('/signals/history', {
      params: { limit }
    });
    return response.data.signals || [];
  },

  /** Rich SMC scanner history with entry/SL/TP/trend/structure */
  getScannerHistory: async (limit: number = 30) => {
    const response = await client.get<{
      signals: Array<{
        signal_id?: string;
        timestamp: string;
        direction?: string;
        entry_price?: number;
        sl?: number;
        tp?: number;
        rsi?: number;
        structure?: string;
        result?: string;
      }>;
      count: number;
    }>('/signals/scanner', { params: { limit } });
    return response.data.signals || [];
  },

  getConsensus: async () => {
    const response = await client.get('/signals/consensus');
    return response.data;
  },

  getStats: async () => {
    const response = await client.get<{ total: number; wins: number; losses: number; win_rate: number }>('/signals/stats');
    return response.data;
  },
};

// Portfolio endpoints
export const portfolioAPI = {
  getStatus: async () => {
    const response = await client.get<Portfolio>('/portfolio/status');
    return response.data;
  },

  getHistory: async () => {
    const response = await client.get('/portfolio/history');
    return response.data;
  },

  getSummary: async () => {
    const response = await client.get('/portfolio/summary');
    return response.data;
  },

  updateBalance: async (balance: number) => {
    const response = await client.post('/portfolio/update-balance', {
      balance
    });
    return response.data;
  },

  addTrade: async (trade: { direction: string; entry: number; sl: number; tp: number; lot_size: number; logic?: string }) => {
    const response = await client.post('/portfolio/add-trade', trade);
    return response.data;
  },

  /** Fast trade from current SMC analysis — no OpenAI call, instant */
  quickTrade: async () => {
    const response = await client.post('/portfolio/quick-trade');
    return response.data;
  },
};

// Models endpoints
export const modelsAPI = {
  getStats: async () => {
    const response = await client.get<AllModelsStats>('/models/stats');
    return response.data;
  },

  getRLAgent: async () => {
    const response = await client.get('/models/rl-agent');
    return response.data;
  },

  getLSTM: async () => {
    const response = await client.get('/models/lstm');
    return response.data;
  },

  getXGBoost: async () => {
    const response = await client.get('/models/xgboost');
    return response.data;
  },
};

// Training endpoints
export const trainingAPI = {
  start: async (episodes: number = 100, saveModel: boolean = true) => {
    const response = await client.post('/training/start', {
      episodes,
      save_model: saveModel
    });
    return response.data;
  },

  getStatus: async () => {
    const response = await client.get<TrainingStatus>('/training/status');
    return response.data;
  },

  stop: async () => {
    const response = await client.post('/training/stop');
    return response.data;
  },
};

// Health check
export const healthAPI = {
  check: async () => {
    const response = await client.get('/health');
    return response.data;
  },
};

// Analysis endpoints
export const analysisAPI = {
  getQuantPro: async (tf: string = '15m', force: boolean = false) => {
    const response = await client.get('/analysis/quant-pro', {
      params: { tf, force },
      timeout: 60_000, // 60s — this endpoint may wait for AI + ML ensemble
    });
    return response.data;
  },

  getStats: async () => {
    const response = await client.get('/analysis/stats');
    return response.data;
  },

  getRecentTrades: async (limit: number = 20) => {
    const response = await client.get('/analysis/trades', {
      params: { limit }
    });
    return response.data;
  },
};

// AI Agent endpoints
export const agentAPI = {
  /**
   * Wysyła wiadomość do Quant Sentinel Gold Trader Agent.
   * Zwraca odpowiedź agenta oraz thread_id do kontynuacji rozmowy.
   */
  chat: async (message: string, threadId?: string) => {
    const response = await client.post<{
      response: string;
      thread_id: string;
      run_id: string;
      tool_calls: Array<{ name: string; args: Record<string, unknown> }>;
    }>('/agent/chat', { message, thread_id: threadId }, { timeout: 120000 }); // 120s for AI agent
    return response.data;
  },

  /** Tworzy nowy pusty wątek rozmowy. */
  createThread: async () => {
    const response = await client.post<{ thread_id: string }>('/agent/thread');
    return response.data.thread_id;
  },

  /** Pobiera historię wiadomości w wątku. */
  getThreadHistory: async (threadId: string, limit: number = 20) => {
    const response = await client.get<{
      thread_id: string;
      messages: Array<{ role: string; content: string; created_at: number }>;
      count: number;
    }>(`/agent/thread/${threadId}`, { params: { limit } });
    return response.data;
  },

  /** Zwraca informacje o agencie i dostępnych narzędziach. */
  getInfo: async () => {
    const response = await client.get('/agent/info');
    return response.data;
  },

  /** Eksportuje konfigurację agenta dla OpenAI Agent Builder. */
  getConfig: async () => {
    const response = await client.get('/agent/config');
    return response.data;
  },
};

export default client;

