/**
 * src/api/client.ts - API client for backend communication
 *
 * Includes circuit breaker to avoid request storms when the backend is down,
 * ETag caching for 304 responses, and GET request deduplication.
 */

import axios from 'axios';
import type { AxiosError, AxiosResponse } from 'axios';
import type { Candle, Ticker, Indicators, Signal, Portfolio, AllModelsStats, TrainingStatus } from '../types/trading';

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000/api';

/* ══════════════════════════════════════════════════════════════════════
   Circuit Breaker — stops request flood when backend is unreachable.
   States: CLOSED (normal) → OPEN (reject fast) → HALF_OPEN (probe once)
   ══════════════════════════════════════════════════════════════════════ */
type CBState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

const circuitBreaker = {
  state: 'CLOSED' as CBState,
  failures: 0,
  lastFailure: 0,
  /** After this many consecutive failures, open the circuit */
  threshold: 8,
  /** How long (ms) to wait before allowing a probe request */
  cooldown: 20_000,
  /** Suppress console noise: log only every Nth failure while open */
  logEvery: 10,
  _suppressCount: 0,

  recordSuccess() {
    this.failures = 0;
    this.state = 'CLOSED';
    this._suppressCount = 0;
  },

  recordFailure() {
    this.failures++;
    this.lastFailure = Date.now();
    if (this.failures >= this.threshold) {
      this.state = 'OPEN';
    }
  },

  /** Returns true if request should be allowed through */
  canRequest(): boolean {
    if (this.state === 'CLOSED') {return true;}
    if (this.state === 'OPEN') {
      // Allow a probe after cooldown
      if (Date.now() - this.lastFailure >= this.cooldown) {
        this.state = 'HALF_OPEN';
        return true;
      }
      return false;
    }
    // HALF_OPEN — allow the probe request through
    return true;
  },

  /** Whether to suppress a console.error for this failure */
  shouldSuppressLog(): boolean {
    if (this.state !== 'OPEN') {return false;}
    this._suppressCount++;
    return this._suppressCount % this.logEvery !== 0;
  },
};

/** Exported so components/hooks can check connectivity cheaply */
export function isCircuitOpen(): boolean {
  return circuitBreaker.state === 'OPEN';
}

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000, // 15s — fails faster; previous 30s caused long queues
  headers: {
    'Content-Type': 'application/json',
  },
});

/* ── ETag cache — send If-None-Match to leverage backend 304 responses ── */
const etagCache = new Map<string, { etag: string; data: unknown }>();

/* ── Request deduplication — prevents identical GET requests from firing simultaneously ── */
const inflightRequests = new Map<string, Promise<AxiosResponse>>();

client.interceptors.request.use((config) => {
  // Circuit breaker gate — reject immediately when backend is known-down
  if (!circuitBreaker.canRequest()) {
    return Promise.reject(new Error('Circuit breaker OPEN — backend unreachable'));
  }

  if (config.method === 'get') {
    const key = `${config.baseURL ?? ''}${config.url ?? ''}`;
    const cached = etagCache.get(key);
    if (cached) {
      config.headers = config.headers ?? {};
      config.headers['If-None-Match'] = cached.etag;
    }
  }
  return config;
});

client.interceptors.response.use(
  (response) => {
    // Backend responded — circuit is healthy
    circuitBreaker.recordSuccess();

    // Store ETag from response
    const etag = response.headers['etag'] as string | undefined;
    if (etag && response.config.method === 'get') {
      const key = `${response.config.baseURL ?? ''}${response.config.url ?? ''}`;
      etagCache.set(key, { etag, data: response.data });
    }
    return response;
  },
  async (error: AxiosError) => {
    // Handle 304 Not Modified — return cached data (still a "success")
    if (error.response?.status === 304 && error.config) {
      circuitBreaker.recordSuccess();
      const key = `${error.config.baseURL ?? ''}${error.config.url ?? ''}`;
      const cached = etagCache.get(key);
      if (cached) {
        return { ...error.response, status: 200, data: cached.data };
      }
    }

    // Custom fields on config we attach for dedup/retry tracking
    type ExtConfig = { __dedupKey?: string; __dedupPromise?: Promise<AxiosResponse>; __isRetry?: boolean };
    const extCfg = error.config as (typeof error.config & ExtConfig) | undefined;
    const dedupKey = extCfg?.__dedupKey;
    if (dedupKey) {inflightRequests.delete(dedupKey);}

    // If this was a deduped request that got cancelled, return the original promise
    const dedupPromise = extCfg?.__dedupPromise;
    if (dedupPromise && axios.isCancel(error)) {return dedupPromise;}

    // Record network / timeout failures for circuit breaker
    // Only count failures on /market/ endpoints (those hit external Twelve Data API).
    // Local DB endpoints (/signals, /portfolio, /analysis, etc.) failing shouldn't
    // trip the circuit breaker — they don't indicate backend unreachability.
    const reqUrl = error.config?.url ?? '';
    const isExternalEndpoint = reqUrl.includes('/market/') || reqUrl === '/health';
    const isNetworkFailure = !error.response || error.code === 'ECONNABORTED' ||
      error.code === 'ERR_NETWORK' || error.message?.includes('timeout');
    if (isNetworkFailure && isExternalEndpoint) {
      circuitBreaker.recordFailure();
    }

    // Auto-retry once for idempotent GET requests on timeout/network errors
    // Skip /market/ endpoints — they have mock fallback, retry wastes API credits
    // Only retry if circuit is still CLOSED and this isn't already a retry
    if (
      isNetworkFailure &&
      error.config &&
      error.config.method === 'get' &&
      !reqUrl.includes('/market/') &&
      !extCfg?.__isRetry &&
      circuitBreaker.state === 'CLOSED'
    ) {
      const retryConfig = { ...error.config, __isRetry: true };
      await new Promise(resolve => setTimeout(resolve, 2000));
      return client.request(retryConfig);
    }

    // Suppress console noise when circuit is open
    if (!circuitBreaker.shouldSuppressLog()) {
      console.error('API Error:', error.response?.data ?? error.message);
    }
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  }
);

// Wrap client.get to leverage dedup map
const originalGet = client.get.bind(client);
client.get = function dedupGet<T = unknown>(...args: Parameters<typeof originalGet>): Promise<AxiosResponse<T>> {
  const config = args[1] ?? {};
  const key = `get:${API_BASE_URL}${args[0]}:${config.params ? JSON.stringify(config.params) : ''}`;
  const existing = inflightRequests.get(key);
  if (existing) {return existing as Promise<AxiosResponse<T>>;}
  const promise = originalGet<T>(...args);
  inflightRequests.set(key, promise);
  void promise.finally(() => inflightRequests.delete(key));
  return promise;
} as typeof client.get;

// Market endpoints
export const marketAPI = {
  getCandles: async (symbol: string = 'XAU/USD', interval: string = '15m', limit: number = 200) => {
    const response = await client.get<{ candles: Candle[] }>('/market/candles', {
      params: { symbol, interval, limit },
      timeout: 20_000, // 20s — backend has 12s external API timeout + processing
    });
    return response.data.candles;
  },

  /**
   * Fetch candles AND the market-closed flag. Chart uses this variant so it
   * can render a "Market closed" overlay when the response is a replayed
   * last-session snapshot (frozen over the weekend) rather than live data.
   */
  getCandlesWithStatus: async (symbol: string = 'XAU/USD', interval: string = '15m', limit: number = 200) => {
    const response = await client.get<{ candles: Candle[]; market_closed?: boolean }>('/market/candles', {
      params: { symbol, interval, limit },
      timeout: 20_000,
    });
    return {
      candles: response.data.candles,
      marketClosed: Boolean(response.data.market_closed),
    };
  },

  getTicker: async (symbol: string = 'XAU/USD') => {
    const response = await client.get<Ticker>('/market/ticker', {
      params: { symbol },
      timeout: 20_000,
    });
    return response.data;
  },

  getIndicators: async (symbol: string = 'XAU/USD', interval: string = '15m') => {
    const response = await client.get<Indicators>('/market/indicators', {
      params: { symbol, interval },
      timeout: 20_000,
    });
    return response.data;
  },

  getStatus: async () => {
    const response = await client.get('/market/status');
    return response.data;
  },

  /** Get Volume Profile data (POC, VAH, VAL, histogram) */
  getVolumeProfile: async (symbol: string = 'XAU/USD', interval: string = '15m', limit: number = 100) => {
    const response = await client.get<{
      poc: number;
      vah: number;
      val: number;
      histogram: Array<{ price: number; volume: number; pct: number }>;
    }>('/market/volume-profile', {
      params: { symbol, interval, limit },
      timeout: 20_000,
    });
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

  updateBalance: async (balance: number, currency: string = 'PLN') => {
    const response = await client.post('/portfolio/update-balance', {
      balance,
      currency,
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
  scanner: async (): Promise<{
    status: 'healthy' | 'stale' | 'degraded' | 'no_data';
    scans_total: number;
    errors_total: number;
    error_rate: number;
    avg_duration_ms: number;
    p95_duration_ms: number;
    last_run_seconds_ago: number | null;
    data_fetch_failures: number;
  }> => {
    const response = await client.get('/health/scanner');
    return response.data;
  },
  models: async () => {
    const response = await client.get('/health/models');
    return response.data as {
      status: 'fresh' | 'stale' | 'degraded';
      models: Record<string, {
        status: 'fresh' | 'stale' | 'missing';
        path: string;
        size_kb?: number;
        age_days?: number;
        mtime?: string;
      }>;
      threshold_days: number;
    };
  },
};

export const backtestResultsAPI = {
  listRuns: async (limit = 20) => {
    const response = await client.get('/backtest/runs', { params: { limit } });
    return response.data as {
      count: number;
      runs: Array<{
        path: string;
        name: string;
        mtime: number;
        trades: number;
        wins: number;
        losses: number;
        breakevens: number;
        win_rate_pct: number;
        profit_factor: number | string;
        return_pct: number;
        max_drawdown_pct: number;
        max_consec_losses: number;
        cycles_total: number;
        alpha_vs_bh_pct: number | null;
        sharpe: number | null;
        sortino: number | null;
        expectancy: number | null;
      }>;
    };
  },
  latest: async () => {
    const response = await client.get('/backtest/latest');
    return response.data as {
      path: string;
      mtime: number;
      data: Record<string, unknown>;
    };
  },
  loadByName: async (name: string) => {
    const response = await client.get('/backtest/run', { params: { name } });
    return response.data as {
      path: string;
      mtime: number;
      data: {
        total_trades?: number;
        wins?: number;
        losses?: number;
        breakevens?: number;
        win_rate_pct?: number;
        profit_factor?: number | string;
        return_pct?: number;
        max_drawdown_pct?: number;
        max_consec_losses?: number;
        alpha_vs_bh_pct?: number | null;
        cycles_total?: number;
        top_rejections?: Array<[string, string, number]>;
        monte_carlo?: {
          n_simulations?: number;
          n_trades?: number;
          return_p5?: number;
          return_p50?: number;
          return_p95?: number;
          return_mean?: number;
          return_stdev?: number;
          prob_profitable?: number;
          max_dd_p5?: number;
          max_dd_p50?: number;
        };
        analytics?: {
          risk_adjusted?: { sharpe?: number; sortino?: number; calmar?: number | string };
          expectancy?: { expectancy_per_trade_usd?: number; payoff_ratio?: number };
          pnl_distribution?: { skewness?: number; excess_kurtosis?: number };
        };
      };
    };
  },
  chartUrl: (name: string) => {
    // Returns URL that React <img> can load directly (FastAPI serves PNG)
    const base = (client.defaults.baseURL ?? '').replace(/\/$/, '');
    // base already ends in /api (from API_BASE_URL), so only /backtest/chart
    return `${base}/backtest/chart?name=${encodeURIComponent(name)}`;
  },
};

export const trainingHistoryAPI = {
  list: async (limit = 20, modelType?: string) => {
    const response = await client.get('/training/history', {
      params: { limit, ...(modelType ? { model_type: modelType } : {}) },
    });
    return response.data as {
      count: number;
      runs: Array<{
        model_type: string;
        timestamp: string;
        git_commit?: string;
        git_dirty?: boolean;
        metrics: Record<string, unknown>;
        notes?: string | null;
        artifact_size_kb?: number | null;
      }>;
      error?: string;
    };
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

  /** Multi-timeframe confluence: bull/bear score across M5/M15/H1/H4 */
  getMtfConfluence: async () => {
    const response = await client.get<{
      confluence_score: number;
      direction: string;
      bull_pct: number;
      bear_pct: number;
      bull_tf_count: number;
      bear_tf_count: number;
      timeframes: Record<string, { trend: string; rsi: number; weight: number }>;
      session: { session: string; is_killzone: boolean; volatility_expected: string };
    }>('/analysis/mtf-confluence');
    return response.data;
  },

  /** Get current trading session info */
  getSession: async () => {
    const response = await client.get<{
      session: string;
      is_killzone: boolean;
      utc_hour: number;
      volatility_expected: string;
    }>('/analysis/session');
    return response.data;
  },

  /** Advanced risk & performance metrics: drawdown, profit factor, expectancy */
  getRiskMetrics: async () => {
    const response = await client.get<{
      total: number;
      wins: number;
      losses: number;
      win_rate: number;
      avg_win: number;
      avg_loss: number;
      profit_factor: number;
      expectancy: number;
      max_consecutive_wins: number;
      max_consecutive_losses: number;
      max_drawdown: number;
      total_profit: number;
    }>('/analysis/risk-metrics');
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

// Export & Download endpoints
export const exportAPI = {
  /** Download trades as CSV or JSON */
  downloadTrades: async (format: 'csv' | 'json' = 'csv', status: string = 'all') => {
    const response = await client.get(`/export/trades`, {
      params: { format, status },
      responseType: format === 'csv' ? 'blob' : 'json',
    });
    return response;
  },

  /** Download equity curve */
  downloadEquity: async (format: 'csv' | 'json' = 'csv') => {
    const response = await client.get(`/export/equity`, {
      params: { format },
      responseType: format === 'csv' ? 'blob' : 'json',
    });
    return response;
  },

  /** Download daily report */
  getDailyReport: async (date?: string) => {
    const response = await client.get('/export/daily-report', {
      params: date ? { date } : {},
    });
    return response.data;
  },

  /** Download monthly PDF report */
  downloadMonthlyReport: async (month?: string) => {
    const response = await client.get('/export/monthly-report', {
      params: month ? { month } : {},
      responseType: 'blob',
    });
    return response;
  },

  /** Trade execution quality report: fill rate, slippage, win rate by grade */
  getExecutionQuality: async (days: number = 30) => {
    const response = await client.get<{
      period_days: number;
      total_trades: number;
      wins: number;
      losses: number;
      win_rate: number;
      total_pnl: number;
      avg_pnl: number;
      fill_rate: number;
      avg_slippage: number;
      slippage_samples: number;
      by_grade: Record<string, {
        wins: number;
        losses: number;
        pnl: number;
        win_rate: number;
        total: number;
      }>;
      error?: string;
    }>('/export/execution-quality', { params: { days } });
    return response.data;
  },
};

// Model monitoring
export const modelMonitorAPI = {
  /** Model drift, rolling accuracy, calibration status, alerts */
  getMonitor: async () => {
    const response = await client.get<{
      drift: Record<string, { psi: number; status: string; ref_mean?: number; cur_mean?: number; ref_std?: number; cur_std?: number }>;
      accuracy: Record<string, number | { rolling_accuracy: number; window?: number; trend?: string }>;
      calibration: Record<string, unknown>;
      alerts: string[];
      healthy: boolean;
    }>('/models/monitor');
    return response.data;
  },
};

// News & Economic Calendar
export const newsAPI = {
  /** Latest news + economic calendar from /api/analysis/news */
  getNews: async () => {
    const response = await client.get<{
      timestamp: string;
      news: Array<{
        title: string;
        source?: string;
        published?: string;
        sentiment?: string;
        impact?: string;
        url?: string;
      }>;
      economic_calendar: Array<{
        event: string;
        date: string;
        time?: string;
        currency?: string;
        impact?: string;
        forecast?: string;
        previous?: string;
        actual?: string;
      }>;
    }>('/analysis/news');
    return response.data;
  },

  /** AI-based market sentiment */
  getSentiment: async () => {
    const response = await client.get<{
      sentiment: string;
      score?: number;
      summary?: string;
    }>('/analysis/sentiment');
    return response.data;
  },
};

// Backtesting
export const backtestAPI = {
  /** Run model backtest — POST /api/training/backtest */
  run: async (params: {
    model?: string;
    period?: string;
    interval?: string;
    include_monte_carlo?: boolean;
    spread_pct?: number;
  } = {}) => {
    const response = await client.post<{
      data_bars: number;
      period: string;
      interval: string;
      xgb?: Record<string, number | string>;
      lstm?: Record<string, number | string>;
      dqn?: Record<string, number | string>;
      ensemble?: Record<string, number | string>;
      monte_carlo?: { risk_distribution?: number[]; VaR_95?: number; CVaR_95?: number; error?: string };
    }>('/training/backtest', null, {
      params: {
        model: params.model ?? 'all',
        period: params.period ?? '3mo',
        interval: params.interval ?? '15m',
        include_monte_carlo: params.include_monte_carlo ?? false,
        spread_pct: params.spread_pct ?? 0.0003,
      },
      timeout: 120_000, // backtests can take a while
    });
    return response.data;
  },
};

// Risk Management (Kill Switch)
export const riskAPI = {
  /** Current risk manager state */
  getStatus: async () => {
    const response = await client.get<{
      halted: boolean;
      halt_reason?: string;
      daily_loss_pct: number;
      daily_loss_soft_limit: number;
      daily_loss_hard_limit: number;
      consecutive_losses: number;
      cooldown_active?: boolean;
      cooldown_until?: string | null;
      max_portfolio_heat_pct?: number;
      kelly_risk_pct?: number;
      session?: string;
      spread_buffer?: number;
    }>('/risk/status');
    return response.data;
  },

  /** Emergency halt — block new trades */
  halt: async (reason: string = 'Manual halt via UI') => {
    const response = await client.post<{ success: boolean; message: string; halted: boolean }>(
      '/risk/halt', null, { params: { reason } }
    );
    return response.data;
  },

  /** Resume trading after halt */
  resume: async () => {
    const response = await client.post<{ success: boolean; message: string; halted: boolean }>(
      '/risk/resume'
    );
    return response.data;
  },
};

export default client;

