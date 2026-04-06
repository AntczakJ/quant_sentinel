/**
 * src/components/ui/ConnectionStatus.tsx — Rich connection status indicator
 *
 * Shows API connection, data freshness, and mock data warnings.
 * Replaces the simple green/red dot in the header with actionable info.
 */

import { useState, useEffect, memo, useCallback } from 'react';
import { Wifi, WifiOff, Clock, AlertTriangle } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { healthAPI, marketAPI } from '../../api/client';

interface StatusInfo {
  api: boolean;
  isMock: boolean;
  lastCheck: Date | null;
  latencyMs: number | null;
}

export const ConnectionStatus = memo(function ConnectionStatus() {
  const { apiConnected, setApiConnected } = useTradingStore();
  const [status, setStatus] = useState<StatusInfo>({
    api: apiConnected,
    isMock: false,
    lastCheck: null,
    latencyMs: null,
  });
  const [expanded, setExpanded] = useState(false);

  const checkStatus = useCallback(async () => {
    const start = performance.now();
    try {
      await healthAPI.check();
      const latency = Math.round(performance.now() - start);
      // Also check if market data is mock
      let isMock = false;
      try {
        const marketStatus = await marketAPI.getStatus();
        isMock = !!marketStatus?.is_mock;
      } catch { /* ignore */ }
      setStatus({ api: true, isMock, lastCheck: new Date(), latencyMs: latency });
      setApiConnected(true);
    } catch {
      const latency = Math.round(performance.now() - start);
      setStatus(prev => ({ ...prev, api: false, lastCheck: new Date(), latencyMs: latency }));
      setApiConnected(false);
    }
  }, [setApiConnected]);

  // Sync from global store (App.tsx runs the primary health check)
  useEffect(() => {
    setStatus(prev => ({ ...prev, api: apiConnected }));
  }, [apiConnected]);

  // Only run our own detailed check every 60s (App.tsx does the fast health ping)
  useEffect(() => {
    void checkStatus();
    const interval = setInterval(checkStatus, 60_000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const dotColor = status.api
    ? status.isMock ? 'bg-amber-400' : 'bg-green-400'
    : 'bg-red-400';

  const textColor = status.api
    ? status.isMock ? 'text-amber-400' : 'text-green-400'
    : 'text-red-400';

  const label = status.api
    ? status.isMock ? 'Mock' : 'Live'
    : 'Offline';

  return (
    <div className="relative">
      <button
        onClick={() => setExpanded(prev => !prev)}
        className={`flex items-center gap-1.5 text-xs font-medium ${textColor} hover:opacity-80 transition-opacity`}
        title="Kliknij po szczegóły połączenia"
      >
        <div className="relative">
          <div className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
          {status.api && !status.isMock && (
            <div className={`absolute inset-0 w-1.5 h-1.5 rounded-full ${dotColor} animate-ping opacity-50`} />
          )}
        </div>
        <span>{label}</span>
      </button>

      {expanded && (
        <div className="absolute top-full right-0 mt-2 w-56 bg-dark-surface border border-dark-secondary rounded-lg shadow-lg p-3 z-50 text-xs">
          <div className="space-y-2">
            {/* API status */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400 flex items-center gap-1">
                {status.api ? <Wifi size={10} /> : <WifiOff size={10} />}
                Backend API
              </span>
              <span className={textColor}>{status.api ? 'Connected' : 'Disconnected'}</span>
            </div>

            {/* Data source */}
            {status.api && (
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Data source</span>
                <span className={status.isMock ? 'text-amber-400' : 'text-green-400'}>
                  {status.isMock ? '⚠ Mock' : '● Live'}
                </span>
              </div>
            )}

            {/* Latency */}
            {status.latencyMs !== null && (
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Latency</span>
                <span className={`font-mono ${
                  status.latencyMs < 200 ? 'text-green-400' :
                  status.latencyMs < 500 ? 'text-amber-400' : 'text-red-400'
                }`}>
                  {status.latencyMs}ms
                </span>
              </div>
            )}

            {/* Last check */}
            {status.lastCheck && (
              <div className="flex items-center justify-between text-gray-500">
                <span className="flex items-center gap-1"><Clock size={9} /> Last check</span>
                <span>{status.lastCheck.toLocaleTimeString('pl-PL')}</span>
              </div>
            )}

            {/* Mock data warning */}
            {status.isMock && (
              <div className="mt-1 p-1.5 bg-amber-900/20 border border-amber-700/30 rounded text-amber-400/80 flex items-start gap-1.5">
                <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                <span className="text-[10px] leading-tight">
                  Dane z cache — API rate limit lub brak połączenia z Twelve Data
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

