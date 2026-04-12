/**
 * src/components/ui/OfflineBanner.tsx — Persistent offline indicator
 *
 * Shows a non-dismissable banner at the top when API is unreachable.
 * Includes retry countdown and manual retry button.
 */

import { memo, useState, useEffect } from 'react';
import { WifiOff, RefreshCw } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { healthAPI } from '../../api/client';

export const OfflineBanner = memo(function OfflineBanner() {
  const apiConnected = useTradingStore(s => s.apiConnected);
  const setApiConnected = useTradingStore(s => s.setApiConnected);
  const [retrying, setRetrying] = useState(false);
  const [secondsAgo, setSecondsAgo] = useState(0);

  // Count up while offline
  useEffect(() => {
    if (apiConnected) { setSecondsAgo(0); return; }
    const t = setInterval(() => setSecondsAgo(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [apiConnected]);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await healthAPI.check();
      setApiConnected(true);
    } catch { /* still offline */ }
    setRetrying(false);
  };

  if (apiConnected) {return null;}

  return (
    <div className="bg-accent-red/10 border-b border-accent-red/25 px-4 py-2 flex items-center justify-center gap-3 text-xs">
      <WifiOff size={12} className="text-accent-red flex-shrink-0" />
      <span className="text-accent-red font-medium">
        Backend disconnected
        {secondsAgo > 0 && <span className="text-accent-red/60 ml-1">({secondsAgo}s)</span>}
      </span>
      <span className="text-th-dim">— using cached data</span>
      <button
        onClick={() => void handleRetry()}
        disabled={retrying}
        className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-accent-red/15 text-accent-red border border-accent-red/25 hover:bg-accent-red/25 transition-colors disabled:opacity-50"
      >
        <RefreshCw size={9} className={retrying ? 'animate-spin' : ''} />
        Retry
      </button>
    </div>
  );
});
