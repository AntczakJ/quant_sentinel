/**
 * src/components/ui/ConnectionStatus.tsx — Rich connection status indicator
 */

import { useState, useEffect, memo, useCallback } from 'react';
import { Wifi, WifiOff, Clock, AlertTriangle, Radio, Activity } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { healthAPI, marketAPI } from '../../api/client';

type ScannerStatus = 'healthy' | 'stale' | 'degraded' | 'no_data';

interface StatusInfo {
  api: boolean;
  isMock: boolean;
  lastCheck: Date | null;
  latencyMs: number | null;
  scanner: ScannerStatus | null;
  scannerP95Ms: number | null;
  scannerLastRunAgoS: number | null;
  scannerErrorRate: number | null;
}

export const ConnectionStatus = memo(function ConnectionStatus() {
  const { apiConnected, setApiConnected, wsConnected } = useTradingStore();
  const [status, setStatus] = useState<StatusInfo>({
    api: apiConnected,
    isMock: false,
    lastCheck: null,
    latencyMs: null,
    scanner: null,
    scannerP95Ms: null,
    scannerLastRunAgoS: null,
    scannerErrorRate: null,
  });
  const [expanded, setExpanded] = useState(false);

  const checkStatus = useCallback(async () => {
    const start = performance.now();
    try {
      await healthAPI.check();
      const latency = Math.round(performance.now() - start);
      let isMock = false;
      try {
        const marketStatus = await marketAPI.getStatus();
        isMock = Boolean(marketStatus?.is_mock);
      } catch { /* ignore */ }
      // Scanner health (best-effort — don't fail the whole status on this)
      let scanner: ScannerStatus | null = null;
      let scannerP95Ms: number | null = null;
      let scannerLastRunAgoS: number | null = null;
      let scannerErrorRate: number | null = null;
      try {
        const sh = await healthAPI.scanner();
        scanner = sh.status;
        scannerP95Ms = sh.p95_duration_ms;
        scannerLastRunAgoS = sh.last_run_seconds_ago;
        scannerErrorRate = sh.error_rate;
      } catch { /* ignore */ }
      setStatus({
        api: true, isMock, lastCheck: new Date(), latencyMs: latency,
        scanner, scannerP95Ms, scannerLastRunAgoS, scannerErrorRate,
      });
      setApiConnected(true);
    } catch {
      const latency = Math.round(performance.now() - start);
      setStatus(prev => ({ ...prev, api: false, lastCheck: new Date(), latencyMs: latency }));
      setApiConnected(false);
    }
  }, [setApiConnected]);

  useEffect(() => {
    setStatus(prev => ({ ...prev, api: apiConnected }));
  }, [apiConnected]);

  useEffect(() => {
    void checkStatus();
    const interval = setInterval(checkStatus, 60_000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const dotColor = status.api
    ? status.isMock ? 'bg-accent-orange' : 'bg-accent-green'
    : 'bg-accent-red';

  const textColor = status.api
    ? status.isMock ? 'text-accent-orange' : 'text-accent-green'
    : 'text-accent-red';

  const label = status.api
    ? wsConnected ? 'WS Live' : status.isMock ? 'Mock' : 'Live'
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
              <span className="text-th-secondary flex items-center gap-1">
                {status.api ? <Wifi size={10} /> : <WifiOff size={10} />}
                Backend API
              </span>
              <span className={textColor}>{status.api ? 'Connected' : 'Disconnected'}</span>
            </div>

            {/* WebSocket status */}
            {status.api && (
              <div className="flex items-center justify-between">
                <span className="text-th-secondary flex items-center gap-1">
                  <Radio size={10} />
                  Price Feed
                </span>
                <span className={wsConnected ? 'text-accent-green' : 'text-accent-orange'}>
                  {wsConnected ? 'WebSocket' : 'HTTP Polling'}
                </span>
              </div>
            )}

            {/* Data source */}
            {status.api && (
              <div className="flex items-center justify-between">
                <span className="text-th-secondary">Data source</span>
                <span className={status.isMock ? 'text-accent-orange' : 'text-accent-green'}>
                  {status.isMock ? 'Mock' : 'Live'}
                </span>
              </div>
            )}

            {/* Scanner health */}
            {status.api && status.scanner && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-th-secondary flex items-center gap-1">
                    <Activity size={10} />
                    Scanner
                  </span>
                  <span className={
                    status.scanner === 'healthy' ? 'text-accent-green' :
                    status.scanner === 'degraded' ? 'text-accent-red' :
                    'text-accent-orange'
                  }>
                    {status.scanner === 'healthy' ? 'Healthy' :
                     status.scanner === 'degraded' ? 'Degraded' :
                     status.scanner === 'stale' ? 'Stale' : 'No data'}
                  </span>
                </div>
                {status.scannerP95Ms !== null && status.scannerP95Ms > 0 && (
                  <div className="flex items-center justify-between text-th-muted">
                    <span>↳ p95 scan time</span>
                    <span className="font-mono">{status.scannerP95Ms.toFixed(0)}ms</span>
                  </div>
                )}
                {status.scannerLastRunAgoS !== null && (
                  <div className="flex items-center justify-between text-th-muted">
                    <span>↳ last run</span>
                    <span className="font-mono">
                      {status.scannerLastRunAgoS < 60
                        ? `${Math.round(status.scannerLastRunAgoS)}s ago`
                        : `${Math.round(status.scannerLastRunAgoS / 60)}m ago`}
                    </span>
                  </div>
                )}
                {status.scannerErrorRate !== null && status.scannerErrorRate > 0 && (
                  <div className="flex items-center justify-between text-th-muted">
                    <span>↳ error rate</span>
                    <span className={`font-mono ${status.scannerErrorRate > 0.1 ? 'text-accent-red' : ''}`}>
                      {(status.scannerErrorRate * 100).toFixed(1)}%
                    </span>
                  </div>
                )}
              </>
            )}

            {/* Latency */}
            {status.latencyMs !== null && (
              <div className="flex items-center justify-between">
                <span className="text-th-secondary">Latency</span>
                <span className={`font-mono ${
                  status.latencyMs < 200 ? 'text-accent-green' :
                  status.latencyMs < 500 ? 'text-accent-orange' : 'text-accent-red'
                }`}>
                  {status.latencyMs}ms
                </span>
              </div>
            )}

            {/* Last check */}
            {status.lastCheck && (
              <div className="flex items-center justify-between text-th-muted">
                <span className="flex items-center gap-1"><Clock size={9} /> Last check</span>
                <span>{status.lastCheck.toLocaleTimeString('pl-PL')}</span>
              </div>
            )}

            {/* Mock data warning */}
            {status.isMock && (
              <div className="mt-1 p-1.5 bg-accent-orange/10 border border-accent-orange/25 rounded text-accent-orange/80 flex items-start gap-1.5">
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
