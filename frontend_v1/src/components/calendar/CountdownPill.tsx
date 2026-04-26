/**
 * calendar/CountdownPill.tsx — Live countdown to a future event.
 *
 * Ticks every 1s when < 2h away (precision matters near impact), 30s otherwise.
 * Color coding escalates as event approaches:
 *   > 1d    : muted (informational)
 *   < 1d    : accent-blue (next up)
 *   < 1h    : accent-orange (imminent)
 *   < 5min  : accent-red + pulsing dot (critical — event-guard window)
 *   past    : dim with "just now" / relative minutes
 */
import { memo, useEffect, useState } from 'react';
import { motion } from 'motion/react';

interface Props {
  /** Event timestamp in ms epoch. */
  targetMs: number;
  /** Compact mode hides the icon. */
  compact?: boolean;
}

function formatDelta(deltaMs: number): string {
  const future = deltaMs > 0;
  const abs = Math.abs(deltaMs);
  const mins = Math.floor(abs / 60_000);
  const hrs = Math.floor(mins / 60);
  const days = Math.floor(hrs / 24);

  if (days >= 1) {return future ? `in ${days}d ${hrs % 24}h` : `${days}d ago`;}
  if (hrs >= 1) {return future ? `in ${hrs}h ${mins % 60}m` : `${hrs}h ago`;}
  if (mins >= 1) {return future ? `in ${mins}m` : `${mins}m ago`;}
  const secs = Math.floor(abs / 1000);
  return future ? `in ${secs}s` : 'just now';
}

export const CountdownPill = memo(function CountdownPill({ targetMs, compact }: Props) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    // Dynamic tick rate — we don't need sub-second precision for distant events.
    const delta = Math.abs(targetMs - Date.now());
    const interval = delta < 2 * 3600_000 ? 1_000 : 30_000;
    const id = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(id);
  }, [targetMs]);

  const delta = targetMs - now;
  const absDelta = Math.abs(delta);
  const past = delta < 0;

  let tone = 'text-th-dim';
  let critical = false;
  if (!past) {
    if (absDelta < 5 * 60_000) { tone = 'text-accent-red'; critical = true; }
    else if (absDelta < 60 * 60_000) {tone = 'text-accent-orange';}
    else if (absDelta < 24 * 3600_000) {tone = 'text-accent-blue';}
    else {tone = 'text-th-muted';}
  }

  return (
    <span className={`inline-flex items-center gap-1 font-mono text-[11px] tabular-nums ${tone}`}>
      {critical && (
        <motion.span
          className="inline-block w-1.5 h-1.5 rounded-full bg-accent-red"
          animate={{ opacity: [1, 0.3, 1], scale: [1, 1.3, 1] }}
          transition={{ duration: 1, repeat: Infinity, ease: 'easeInOut' }}
          aria-hidden
        />
      )}
      {!compact && !critical && <span aria-hidden className="opacity-60">•</span>}
      <span>{formatDelta(delta)}</span>
    </span>
  );
});
