/**
 * src/hooks/useSSE.ts — Server-Sent Events hook with native auto-reconnect.
 *
 * Replaces useWebSocket for server→client push (prices, signals).
 * EventSource handles reconnection automatically — no manual backoff needed.
 *
 * Benefits over WebSocket:
 * - Built-in auto-reconnect (browser-native, exponential backoff)
 * - Works through HTTP/2 multiplexing
 * - Simpler protocol (no upgrade handshake)
 * - Firewall-friendly (plain HTTP GET)
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export type SSEStatus = 'connecting' | 'connected' | 'disconnected';

// EventSource claims to auto-reconnect but can silently get stuck in a
// "CLOSED" state where onerror fired yet no further events arrive.
// A watchdog that forces a fresh EventSource after this many seconds
// without a message keeps the signal feed live.
const STALE_WATCHDOG_MS = 30_000;

/**
 * Resolve SSE base URL — same origin as API.
 */
function resolveBase(): string {
  const envUrl = import.meta.env.VITE_API_URL as string | undefined;
  if (envUrl) {return envUrl.replace(/\/$/, '');}
  return '/api';
}

const SSE_BASE = resolveBase();

/**
 * @param path      SSE endpoint path, e.g. "/sse/prices"
 * @param onMessage Called with parsed JSON data on every event
 * @param enabled   Set to false to disconnect
 */
export function useSSE<T = unknown>(
  path: string,
  onMessage: (data: T) => void,
  enabled = true,
): { status: SSEStatus } {
  const [status, setStatus] = useState<SSEStatus>('disconnected');
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const esRef = useRef<EventSource | null>(null);
  const lastEventAtRef = useRef<number>(Date.now());
  const watchdogRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const connect = useCallback(() => {
    if (!enabled) {return;}

    const url = `${SSE_BASE}${path}`;
    const es = new EventSource(url);
    esRef.current = es;
    lastEventAtRef.current = Date.now();
    setStatus('connecting');

    es.onopen = () => {
      setStatus('connected');
      lastEventAtRef.current = Date.now();
    };

    es.onmessage = (event) => {
      lastEventAtRef.current = Date.now();
      try {
        const data = JSON.parse(event.data) as T;
        onMessageRef.current(data);
      } catch {
        // ignore non-JSON (heartbeat comments)
      }
    };

    es.onerror = () => {
      setStatus('disconnected');
      // Initial-connection-failed path: readyState CLOSED immediately after
      // construction means the browser gave up. Trigger a manual reconnect
      // after 2s instead of spinning on 'connecting' forever.
      if (es.readyState === EventSource.CLOSED) {
        setTimeout(() => {
          if (esRef.current === es && enabled) {
            es.close();
            connect();
          }
        }, 2000);
      }
    };
  }, [path, enabled]);

  useEffect(() => {
    if (!enabled) {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
        setStatus('disconnected');
      }
      if (watchdogRef.current) {
        clearInterval(watchdogRef.current);
        watchdogRef.current = null;
      }
      return;
    }

    connect();

    // Watchdog — if no message/event for STALE_WATCHDOG_MS, assume the
    // EventSource is dead and force-reconnect. Typical SSE heartbeats
    // arrive every 15s so 30s of silence is a real problem.
    watchdogRef.current = setInterval(() => {
      if (Date.now() - lastEventAtRef.current > STALE_WATCHDOG_MS) {
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
        }
        connect();
      }
    }, 5_000);

    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (watchdogRef.current) {
        clearInterval(watchdogRef.current);
        watchdogRef.current = null;
      }
    };
  }, [connect, enabled]);

  return { status };
}
