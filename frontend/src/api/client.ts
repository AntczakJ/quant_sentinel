/**
 * src/api/client.ts — Quant Sentinel API client.
 *
 * Wired against the real endpoints exposed by api/main.py (FastAPI).
 * Several endpoints return prices as `"$4732.84"` strings — we parse those
 * into numbers in the wrappers so components see typed numerics.
 */
import axios, { type AxiosResponse, type AxiosError } from 'axios'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

// ─── Circuit breaker ──────────────────────────────────────────────────
const cb = {
  state: 'CLOSED' as 'CLOSED' | 'OPEN' | 'HALF_OPEN',
  failures: 0,
  lastFailure: 0,
  threshold: 6,
  cooldown: 15_000,
  ok() { this.failures = 0; this.state = 'CLOSED' },
  fail() {
    this.failures++
    this.lastFailure = Date.now()
    if (this.failures >= this.threshold) this.state = 'OPEN'
  },
  canRequest(): boolean {
    if (this.state === 'CLOSED') return true
    if (this.state === 'OPEN' && Date.now() - this.lastFailure > this.cooldown) {
      this.state = 'HALF_OPEN'
      return true
    }
    return this.state === 'HALF_OPEN'
  },
}

// 2026-05-04: backend now requires X-API-Key on all POST/PUT/DELETE under
// /api/* (commit 86ee235 removed /api/training/, /api/portfolio/, /api/agent/
// from public prefixes). Frontend must send the API key. Read from Vite env
// VITE_API_SECRET_KEY (set in .env.local for dev). GETs unaffected.
const API_KEY = (import.meta.env.VITE_API_SECRET_KEY as string | undefined) ?? ''

const ax = axios.create({
  baseURL: BASE,
  timeout: 8000,
  headers: {
    'Content-Type': 'application/json',
    ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
  },
})

ax.interceptors.request.use((config) => {
  if (!cb.canRequest()) return Promise.reject(new Error('circuit-open'))
  // Defensive: re-attach API key if header was stripped by an interceptor.
  if (API_KEY && !config.headers['X-API-Key']) {
    config.headers['X-API-Key'] = API_KEY
  }
  return config
})
ax.interceptors.response.use(
  (r: AxiosResponse) => { cb.ok(); return r },
  (e: AxiosError) => {
    if (e.message !== 'circuit-open') cb.fail()
    return Promise.reject(e)
  },
)

const inflight = new Map<string, Promise<unknown>>()

async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const key = `${path}::${JSON.stringify(params ?? {})}`
  const existing = inflight.get(key) as Promise<T> | undefined
  if (existing) return existing
  const p = ax.get<T>(path, { params }).then((r) => r.data).finally(() => {
    setTimeout(() => inflight.delete(key), 100)
  })
  inflight.set(key, p)
  return p
}

// ─── Helpers ──────────────────────────────────────────────────────────

/** Parse "$4732.84" or "$-3.29" → 4732.84 / -3.29. Already-numeric returns as-is. */
function parsePrice(v: unknown): number | null {
  if (v == null) return null
  if (typeof v === 'number') return v
  if (typeof v !== 'string') return null
  const cleaned = v.replace(/[$,\s]/g, '')
  if (!cleaned || cleaned === '—') return null
  const n = parseFloat(cleaned)
  return Number.isFinite(n) ? n : null
}

// ─── Public types ─────────────────────────────────────────────────────

export interface Health {
  status: string
  uptime?: string
  uptime_seconds?: number
  models_loaded?: boolean
  data_provider?: string
}

export interface PortfolioSummary {
  balance: number
  currency: string
  pnl: number
  pnl_pct: number
  /** open positions count, fetched via /portfolio/open-positions */
  open_positions?: number
}

export interface Trade {
  id: number
  timestamp: string
  direction: string
  entry: number | null
  sl: number | null
  tp: number | null
  status: string
  profit: number | null
  timeframe?: string
  pattern?: string
  setup_grade?: string | null
  setup_score?: number | null
  factors?: string | null  // JSON-encoded factors dict
}

export interface Ticker {
  symbol: string
  price: number
  change?: number
  change_pct?: number
  high_24h?: number
  low_24h?: number
}

export interface Candle {
  /** Unix seconds (lightweight-charts compatible) */
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface ScannerInsight {
  hours_window: number
  rejections: { total: number; top: Array<{ filter: string; count: number }> }
  toxic_patterns: Array<{ pattern: string; n: number; win_rate: number; blocked: boolean }>
}

export interface MacroContext {
  usdjpy?: number | null
  usdjpy_zscore?: number | null
  xau_usdjpy_corr?: number | null
  macro_regime?: 'zielony' | 'czerwony' | 'neutralny' | null
  market_regime?: 'squeeze' | 'trending_high_vol' | 'trending_low_vol' | 'ranging' | null
}

export interface ModelStat {
  model_name: string
  accuracy: number | null
  win_rate: number | null
  last_training: string | null
}

// ─── Endpoints ────────────────────────────────────────────────────────

export const api = {
  health: () => get<Health>('/health'),

  async portfolio(): Promise<PortfolioSummary> {
    const [summary, open] = await Promise.all([
      get<{ balance: number; currency: string; pnl: number; pnl_pct: number }>('/portfolio/summary'),
      get<{ positions: unknown[] }>('/portfolio/open-positions').catch(() => ({ positions: [] })),
    ])
    return { ...summary, open_positions: open.positions?.length ?? 0 }
  },

  async trades(limit = 50): Promise<Trade[]> {
    const raw = await get<{
      trades: Array<{
        id: number
        timestamp: string
        direction: string
        entry: string | number
        sl: string | number
        tp: string | number
        status: string
        profit: string | number | null
        timeframe?: string
        pattern?: string
        setup_grade?: string | null
        setup_score?: number | null
        factors?: string | null
      }>
    }>('/analysis/trades', { limit })
    return (raw.trades ?? []).map((t) => ({
      id: t.id,
      timestamp: t.timestamp,
      direction: t.direction,
      entry: parsePrice(t.entry),
      sl: parsePrice(t.sl),
      tp: parsePrice(t.tp),
      status: t.status,
      profit: parsePrice(t.profit),
      timeframe: t.timeframe,
      pattern: t.pattern,
      setup_grade: t.setup_grade,
      setup_score: t.setup_score,
      factors: t.factors,
    }))
  },

  ticker: (symbol = 'XAU/USD') => get<Ticker>('/market/ticker', { symbol }),

  async candles(symbol = 'XAU/USD', interval = '5m', count = 500): Promise<Candle[]> {
    const raw = await get<{
      candles: Array<{
        timestamp: string
        open: number
        high: number
        low: number
        close: number
      }>
    }>('/market/candles', { symbol, interval, count })
    return (raw.candles ?? []).map((c) => ({
      time: Math.floor(new Date(c.timestamp).getTime() / 1000),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
  },

  scannerInsight: () => get<ScannerInsight>('/scanner/insight'),
  macroContext: () => get<MacroContext>('/macro/context'),

  /** All feature flags + dynamic_params in one place (2026-05-04). */
  flags: () =>
    get<{
      env_flags: Record<string, string>
      dynamic_params: Record<string, number | string | null>
      session_2026_05_04_flags: {
        regime_v2_active: boolean
        toxic_pair_filter_active: boolean
        llm_news_active: boolean
        calibration_disabled: boolean
        trailing_disabled: boolean
        max_lot_cap: number
      }
    }>('/flags'),

  async models(): Promise<ModelStat[]> {
    const raw = await get<{ rl_stats?: ModelStat; lstm_stats?: ModelStat; xgb_stats?: ModelStat }>(
      '/models/stats',
    )
    return [raw.lstm_stats, raw.xgb_stats, raw.rl_stats].filter(Boolean) as ModelStat[]
  },

  /** Live voter weights from `dynamic_params` — drives Models page beams. */
  ensembleWeights: () =>
    get<{
      weights: Record<string, number>
      normalized: Record<string, number>
      total: number
      voters: string[]
    }>('/models/ensemble-weights'),

  /** Per-voter forward-move accuracy over recent N hours. */
  voterLiveAccuracy: (hours = 72, horizonCandles = 12) =>
    get<{
      hours_window: number
      horizon_candles: number
      horizon_label: string
      voters: Record<
        string,
        {
          decisive_samples: number
          combined_accuracy_pct: number | null
          bullish_accuracy_pct: number | null
          bearish_accuracy_pct: number | null
          status: 'insufficient' | 'anti_signal' | 'ok' | 'good' | 'underperforming' | string
        }
      >
    }>('/voter-live-accuracy', { hours, horizon_candles: horizonCandles }),

  /** Equity timeline — falls back to trades-derived series when cache is empty. */
  portfolioHistory: () =>
    get<{
      timestamps: string[]
      equity_values: number[]
      pnl_values: number[]
    }>('/portfolio/history'),

  /** Open positions with live P&L. */
  openPositions: () =>
    get<{
      positions: Array<{
        id: number
        direction: string
        entry: number
        sl: number
        tp: number
        lot?: number
        unrealized_pnl?: number
        timestamp?: string
      }>
      total_unrealized_pnl: number
      current_price: number
    }>('/portfolio/open-positions'),

  /** Diagnostic snapshot of the running stack — versions, models, GPU, env. */
  systemInfo: () =>
    get<{
      platform: { system: string; release: string; machine: string; python: string }
      git: { sha: string | null; branch: string | null; dirty: boolean | null; error?: string }
      versions: Record<string, string | null>
      models: Array<{ name: string; size_kb: number; mtime_iso: string; age_hours: number }>
      xgb_loader: { status: string; path?: string; error?: string }
      process: { rss_mb?: number; vms_mb?: number; num_threads?: number; cpu_percent?: number; uptime_s?: number; error?: string }
      gpu: Record<string, unknown>
      disk: { total_gb: number; used_gb: number; free_gb: number; free_pct: number }
      env: Record<string, boolean>
      integrations?: Record<'logfire' | 'sentry' | 'modal', { active: boolean; url: string; what: string }>
    }>('/system/info'),

  /** Multi-TF scanner peek — all 5 timeframes in one call + agreement label. */
  scannerPeekAll: (symbol = 'XAU/USD', count = 100) =>
    get<{
      symbol: string
      by_tf: Record<string, {
        symbol: string
        interval: string
        bars_used: number
        last_bar: { ts: string; close: number; high: number; low: number }
        indicators: {
          atr_14: number; rsi_14: number; ema_20: number; ema_distance_pct: number
          high_14: number; low_14: number; volatility_20: number
        }
        bias: 'bullish' | 'bearish' | 'neutral'
      }>
      errors: Record<string, string>
      agreement: {
        label: 'strong_bull' | 'strong_bear' | 'lean_bull' | 'lean_bear' | 'mixed'
        bull_count: number; bear_count: number; neutral_count: number
        tfs_ok: string[]; tfs_failed: string[]
      }
    }>('/scanner/peek-all', { symbol, count }),

  /** Scanner diagnostic — what indicators look like RIGHT NOW (no scoring/ML). */
  scannerPeek: (symbol = 'XAU/USD', interval = '15m', count = 100) =>

    get<{
      symbol: string
      interval: string
      bars_used: number
      last_bar: { ts: string; close: number; high: number; low: number }
      indicators: {
        atr_14: number
        rsi_14: number
        ema_20: number
        ema_distance_pct: number
        high_14: number
        low_14: number
        volatility_20: number
      }
      bias: 'bullish' | 'bearish' | 'neutral'
    }>('/scanner/peek', { symbol, interval, count }),

  /** Heuristic suggestions — missing tokens, stale models, paused scanner, etc. */
  recommendations: () =>
    get<{
      count: number
      by_severity: { error: number; warn: number; info: number }
      items: Array<{
        id: string
        severity: 'error' | 'warn' | 'info'
        title: string
        detail: string
        action_url?: string
      }>
    }>('/system/recommendations'),

  /** sentinel.db query latencies — `fast` / `ok` / `slow` / `concerning`. */
  dbTiming: (repeats = 5) =>

    get<{
      queries: Record<string, { median_ms: number; min_ms: number; max_ms: number; rows: number; repeats: number; error?: string }>
      summary: {
        total_queries: number
        ok_queries: number
        median_of_medians_ms: number | null
        max_median_ms: number | null
        verdict: 'fast' | 'ok' | 'slow' | 'concerning'
      }
    }>('/system/db-timing', { repeats }),

  /** sentinel.db row counts + file size. */
  dbStats: () =>
    get<{
      trades: { total: number; open: number; closed: number; wins: number; losses: number; win_rate_pct: number | null }
      tables: Record<string, number | null>
      file: { path: string; size_kb: number | null }
    }>('/system/db-stats'),

  /** Detailed subsystem health probe. */
  healthDeep: () =>
    get<{
      all_ok: boolean
      checks: Record<string, {
        ok: boolean
        message?: string
        loaded?: Record<string, boolean>
        paused?: boolean
        last_cycle_s_ago?: number | null
        last_timestamp?: string | null
        last_status?: string | null
        open_count?: number
      }>
    }>('/system/health/deep'),

  /** Recent macro_regime snapshots (per-cycle persistence). */
  macroSnapshots: (limit = 200) =>
    get<{
      items: Array<{
        id: number
        timestamp: string
        macro_regime: 'zielony' | 'czerwony' | 'neutralny' | null
        usdjpy_zscore: number | null
        usdjpy_price: number | null
        atr_ratio: number | null
        market_regime: string | null
      }>
      count: number
    }>('/macro/snapshots', { limit }),

  /** API credit-bucket status (TwelveData primary). */
  rateLimit: () =>
    get<{
      current_credits: number
      safe_limit: number
      max_limit: number
      credits_used_last_min: number
      recent_requests: number
      last_refill: number
      all_requests_count: number
      alarm_threshold?: number
      alarm_cooldown_sec?: number
      last_alarm_ts?: number
    }>('/system/rate-limit'),

  // Scanner control
  scannerStatus: () =>
    get<{ paused: boolean; reason: string | null; since: string | null }>('/scanner/status'),
  scannerPause: (reason?: string) =>
    ax.post<{ ok: boolean }>('/scanner/pause', { reason }).then((r) => r.data),
  scannerResume: () => ax.post<{ ok: boolean }>('/scanner/resume').then((r) => r.data),

  // Grid backtest winner control
  gridList: () =>
    get<{ grids: Array<{ name: string; stages: Array<{ stage: string; n_cells: number; best_composite: number | null; modified: number }> }> }>(
      '/grid/list',
    ),
  gridPreview: (grid: string, cellHash?: string) =>
    get<{
      grid: string
      stage: string
      cell_hash: string
      metrics: Record<string, number | null>
      diff: Array<{ param: string; current: unknown; winner: unknown; change_pct: number | null; unchanged: boolean }>
      winner_params: Record<string, number | null>
      code_level_params: Record<string, unknown>
    }>('/grid/preview', { grid, cell_hash: cellHash }),
  gridApply: (grid: string, cellHash?: string, confirm = false) =>
    ax.post<{
      ok: boolean
      applied: boolean
      grid?: string
      cell_hash?: string
      winner?: Record<string, number>
      backup_path?: string
      reason?: string
    }>('/grid/apply', { grid, cell_hash: cellHash, confirm }).then((r) => r.data),
  gridBackups: () =>
    get<{
      backups: Array<{
        filename: string
        path: string
        backup_ts_utc: string
        reason: string
        size_kb: number
        params: Record<string, unknown>
      }>
    }>('/grid/backups'),
  gridRollback: (backupFilename: string, confirm = false) =>
    ax.post<{
      ok: boolean
      applied: boolean
      from?: string
      restored?: Record<string, unknown>
      would_restore?: Record<string, unknown>
    }>('/grid/rollback', { backup_filename: backupFilename, confirm }).then((r) => r.data),
}

export const isCircuitOpen = () => cb.state !== 'CLOSED'
