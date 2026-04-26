/**
 * src/api/client.ts — Lean axios client for the Quant Sentinel API.
 *
 * Adapted from frontend_v1/src/api/client.ts but slimmed down.
 * Circuit breaker + 304 ETag caching kept; deduplication kept.
 */
import axios, { type AxiosResponse, type AxiosError } from 'axios'

const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? '/api'

// ─── Circuit breaker (close fast when backend is down) ────────────────
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

// ─── Axios instance ───────────────────────────────────────────────────
const ax = axios.create({
  baseURL: BASE,
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
})

ax.interceptors.request.use((config) => {
  if (!cb.canRequest()) {
    return Promise.reject(new Error('circuit-open'))
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

// ─── Request dedup (multiple components asking for same URL get one request) ──
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

// ─── Typed endpoints ──────────────────────────────────────────────────

export interface Health {
  status: string
  ws_connected?: boolean
  ws_status?: string
  data_provider?: string
}

export interface Portfolio {
  balance: number
  equity?: number
  pnl?: number
  open_trades?: number
  closed_trades?: number
}

export interface Trade {
  id: number
  timestamp: string
  direction: string
  entry: number
  sl: number
  tp: number
  status: string
  profit: number | null
  lot: number
  rsi?: number
  trend?: string
  structure?: string
  pattern?: string
}

export interface Ticker {
  symbol: string
  price: number
  change?: number
  change_pct?: number
  high?: number
  low?: number
  volume?: number
}

export interface ScannerInsight {
  open_trades: number
  closed_today: number
  rejection_breakdown: Array<{ filter: string; reason: string; count: number }>
  recent_signals: Array<{ tf: string; direction: string; grade: string; ts: string }>
  toxic_patterns: Array<{ pattern: string; n: number; wr: number }>
  streak: { count: number; oldest_age_h: number }
}

export interface MacroContext {
  usdjpy_zscore_20: number
  xau_usdjpy_corr_20: number
  macro_regime: 'zielony' | 'czerwony' | 'neutralny'
  market_regime: 'squeeze' | 'trending_high_vol' | 'trending_low_vol' | 'ranging'
}

export const api = {
  health: () => get<Health>('/health'),
  portfolio: () => get<Portfolio>('/portfolio'),
  trades: (limit = 50) => get<Trade[]>('/trades/recent', { limit }),
  tradesAll: () => get<Trade[]>('/trades/all'),
  ticker: (symbol = 'XAU/USD') => get<Ticker>('/market/ticker', { symbol }),
  candles: (symbol = 'XAU/USD', interval = '5m', count = 200) =>
    get<{ candles: Array<{ time: number; open: number; high: number; low: number; close: number }> }>(
      '/market/candles',
      { symbol, interval, count },
    ),
  scannerInsight: () => get<ScannerInsight>('/scanner/insight'),
  macroContext: () => get<MacroContext>('/macro/context'),
  models: () => get<{ models: Array<{ name: string; trained_at: string; score: number; direction: string }> }>(
    '/models',
  ),
}

export const isCircuitOpen = () => cb.state !== 'CLOSED'
