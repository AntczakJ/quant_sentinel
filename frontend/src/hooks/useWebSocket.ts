/**
 * src/hooks/useWebSocket.ts — Generic WebSocket hook with auto-reconnect.
 * Used primarily for live XAU/USD price feed from /ws/prices.
 *
 * URL resolution order:
 *   1. VITE_WS_URL env var (explicit override, e.g. wss://production.example.com)
 *   2. window.location.host  — keeps Vite dev-server proxy working in dev,
 *      and works without configuration when API serves the frontend.
 *
 * Reconnect strategy:
 *   - Exponential backoff: 2s → 4s → 8s → … → 60s max
 *   - After MAX_RECONNECT_ATTEMPTS (12) failures, pauses for IDLE_RETRY_INTERVAL (60s)
 *     and only retries if the REST API is reachable (quick /health pre-check).
 *   - A successful connection resets the attempt counter.
 */

import { useEffect, useRef, useCallback, useState } from 'react';

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected';

/** Maximum consecutive failures before switching to slow "idle" retry mode. */
const MAX_RECONNECT_ATTEMPTS = 5;
/** How long to wait in idle mode before retrying (ms). */
const IDLE_RETRY_INTERVAL = 120_000;

/**
 * Derive the base WebSocket URL once at module load.
 */
function resolveWsBase(): string {
  const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
  if (envUrl) return envUrl.replace(/\/$/, '');

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

const WS_BASE_URL = resolveWsBase();

/**
 * Derive the REST API base URL the same way client.ts does so the health
 * check follows the exact same network path as every other API call.
 *
 * In dev the Vite proxy forwards /api → http://localhost:8000, so we prefer
 * the relative path to avoid cross-origin fetch issues.
 */
function resolveHealthUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL as string | undefined;
  if (envUrl) return `${envUrl.replace(/\/$/, '')}/health`;
  // Relative path — goes through Vite proxy in dev, works in prod when
  // the API serves the frontend from the same origin.
  return '/api/health';
}

const HEALTH_URL = resolveHealthUrl();

/**
 * Quick health-check against the REST API.
 * Returns true if the backend responds within 3 seconds.
 */
async function isBackendReachable(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const r = await fetch(HEALTH_URL, { signal: controller.signal });
    clearTimeout(timer);
    return r.ok;
  } catch (err) {
    console.debug('[WebSocket] Health check failed:', (err as Error).message ?? err);
    return false;
  }
}

/**
 * @param path      WebSocket path, e.g. "/ws/prices"
 * @param onMessage Called with parsed JSON data on every message
 * @param enabled   Set to false to completely disable the socket
 */
export function useWebSocket<T = unknown>(
  path: string,
  onMessage: (data: T) => void,
  enabled = true
): { status: WebSocketStatus } {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const reconnectAttemptsRef = useRef(0);
  const mountedRef = useRef(true);
  /** True while we are in the "idle" slow-retry mode (backend unreachable). */
  const idleModeRef = useRef(false);

  // Keep callback ref up-to-date so we never need to re-create the socket
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      const ws = wsRef.current;
      ws.onopen = null;
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      try { ws.close(); } catch { /* ignore */ }
      wsRef.current = null;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    reconnectAttemptsRef.current += 1;

    // After too many failures, switch to idle mode
    if (reconnectAttemptsRef.current > MAX_RECONNECT_ATTEMPTS) {
      if (!idleModeRef.current) {
        idleModeRef.current = true;
        console.log(
          `[WebSocket] Backend unreachable after ${MAX_RECONNECT_ATTEMPTS} attempts — ` +
          `switching to idle retry every ${IDLE_RETRY_INTERVAL / 1000}s`
        );
      }
      reconnectTimerRef.current = setTimeout(async () => {
        if (!mountedRef.current || !enabled) return;
        const alive = await isBackendReachable();
        if (alive) {
          console.log('[WebSocket] Backend is back — reconnecting');
          reconnectAttemptsRef.current = 0;
          idleModeRef.current = false;
          connectRef.current();
        } else {
          // Still down — schedule another idle check
          scheduleReconnectRef.current();
        }
      }, IDLE_RETRY_INTERVAL);
      return;
    }

    // Exponential backoff: 2s, 4s, 8s, 16s, 32s … max 60s
    const delay = Math.min(2000 * Math.pow(2, reconnectAttemptsRef.current - 1), 60_000);
    if (reconnectAttemptsRef.current <= 1) {
      console.log(`[WebSocket] Reconnecting in ${delay / 1000}s (attempt ${reconnectAttemptsRef.current})`);
    }
    reconnectTimerRef.current = setTimeout(() => connectRef.current(), delay);
  }, [enabled]);

  // Stable refs so callbacks can call each other without stale closures
  const connectRef = useRef(() => {});
  const scheduleReconnectRef = useRef(scheduleReconnect);
  scheduleReconnectRef.current = scheduleReconnect;

  const connect = useCallback(() => {
    if (!enabled || !mountedRef.current) return;

    // Clear any pending reconnect timer
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    // Tear down existing socket before opening a new one
    cleanup();

    const wsUrl = `${WS_BASE_URL}${path}`;

    // Suppress noisy logs after the first few failures
    if (reconnectAttemptsRef.current <= 1) {
      console.log(`[WebSocket] Connecting to ${wsUrl}`);
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl);
    } catch (err) {
      console.error(`[WebSocket] Cannot create WebSocket:`, err);
      scheduleReconnectRef.current();
      return;
    }

    wsRef.current = ws;
    if (mountedRef.current) setStatus('connecting');

    ws.onopen = () => {
      if (!mountedRef.current) return;
      console.log(`[WebSocket] Connected to ${path}`);
      setStatus('connected');
      reconnectAttemptsRef.current = 0;
      idleModeRef.current = false;
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(event.data as string) as T;
        onMessageRef.current(data);
      } catch {
        // ignore non-JSON frames (e.g. plain text pings)
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;
      if (reconnectAttemptsRef.current <= 1) {
        console.log(`[WebSocket] Disconnected from ${path} (code ${event.code})`);
      }
      setStatus('disconnected');
      wsRef.current = null;
      if (enabled && mountedRef.current) {
        scheduleReconnectRef.current();
      }
    };

    ws.onerror = () => {
      if (reconnectAttemptsRef.current <= 1) {
        console.warn(`[WebSocket] Connection error on ${path}`);
      }
    };
  }, [path, enabled, cleanup]);

  connectRef.current = connect;

  useEffect(() => {
    mountedRef.current = true;
    reconnectAttemptsRef.current = 0;
    idleModeRef.current = false;

    // Wait for the backend to be reachable before opening the first WebSocket.
    // This avoids a storm of "socket hang up" errors in the Vite proxy when the
    // backend is still loading (TF/Keras imports take 10–30 s on startup).
    let cancelled = false;
    (async () => {
      // Quick first check — backend may already be up
      if (await isBackendReachable()) {
        if (!cancelled) connect();
        return;
      }
      // Poll every 5 s until the backend is ready (or component unmounts)
      console.log('[WebSocket] Waiting for backend to be ready before connecting…');
      const poll = setInterval(async () => {
        if (cancelled) { clearInterval(poll); return; }
        if (await isBackendReachable()) {
          clearInterval(poll);
          if (!cancelled) {
            console.log('[WebSocket] Backend ready — opening connection');
            connect();
          }
        }
      }, 5000);
      reconnectTimerRef.current = poll as unknown as ReturnType<typeof setTimeout>;
    })();

    return () => {
      cancelled = true;
      mountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);

  return { status };
}
