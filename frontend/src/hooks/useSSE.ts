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

  const connect = useCallback(() => {
    if (!enabled) {return;}

    const url = `${SSE_BASE}${path}`;
    const es = new EventSource(url);
    esRef.current = es;
    setStatus('connecting');

    es.onopen = () => {
      setStatus('connected');
    };

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as T;
        onMessageRef.current(data);
      } catch {
        // ignore non-JSON (heartbeat comments)
      }
    };

    es.onerror = () => {
      setStatus('disconnected');
      // EventSource auto-reconnects — no manual logic needed
    };
  }, [path, enabled]);

  useEffect(() => {
    if (!enabled) {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
        setStatus('disconnected');
      }
      return;
    }

    connect();

    return () => {
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect, enabled]);

  return { status };
}
