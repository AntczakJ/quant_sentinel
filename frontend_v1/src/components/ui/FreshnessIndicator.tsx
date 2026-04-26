/**
 * src/components/ui/FreshnessIndicator.tsx — "Updated X ago" widget badge
 *
 * Shows how stale the data is. Turns yellow > red as data ages.
 * Designed to sit in widget headers next to the title.
 */

import { memo, useEffect, useState } from 'react';
import { Clock } from 'lucide-react';

interface Props {
  /** Last update timestamp (Date object or epoch ms) */
  lastUpdated: Date | number | null;
  /** Max acceptable staleness in seconds before warning (default 120) */
  warnAfterSec?: number;
  /** Max staleness before error state (default 300) */
  errorAfterSec?: number;
}

export const FreshnessIndicator = memo(function FreshnessIndicator({
  lastUpdated, warnAfterSec = 120, errorAfterSec = 300,
}: Props) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);

  if (!lastUpdated) {return null;}

  const ts = typeof lastUpdated === 'number' ? lastUpdated : lastUpdated.getTime();
  const ageSec = Math.floor((now - ts) / 1000);

  if (ageSec < 5) {return null;} // Too fresh to show

  const color = ageSec > errorAfterSec
    ? 'text-accent-red'
    : ageSec > warnAfterSec
    ? 'text-accent-orange'
    : 'text-th-dim';

  const label = ageSec < 60
    ? `${ageSec}s`
    : ageSec < 3600
    ? `${Math.floor(ageSec / 60)}m`
    : `${Math.floor(ageSec / 3600)}h`;

  return (
    <span className={`inline-flex items-center gap-0.5 text-[9px] font-medium ${color}`} title={`Last updated ${label} ago`}>
      <Clock size={7} />
      {label}
    </span>
  );
});
