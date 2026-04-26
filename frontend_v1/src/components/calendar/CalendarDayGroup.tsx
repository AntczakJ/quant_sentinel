/**
 * calendar/CalendarDayGroup.tsx — Sticky date header + staggered event list.
 *
 * Groups visually by day. Uses Motion's stagger to reveal children one-by-one
 * for a premium feel without being slow (8 ms stagger, well under perceptible
 * latency in aggregate but creates cascade effect on scroll-into-view).
 */
import { memo } from 'react';
import { motion } from 'motion/react';
import { CalendarEventRow } from './CalendarEventRow';
import type { CalendarEvent } from './types';

interface Props {
  label: string;
  sublabel?: string;
  events: CalendarEvent[];
  /** True when this group is today/tomorrow — enables subtle highlight. */
  highlighted?: boolean;
  /** Enables upcoming-specific styling (pulse on high-impact bars, etc.). */
  upcoming?: boolean;
}

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

const container = {
  hidden: { opacity: 0 },
  show:   { opacity: 1, transition: { staggerChildren: 0.025 } },
} as const;

const item = {
  hidden: { opacity: 0, y: 8 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.28, ease: EASE_OUT } },
} as const;

export const CalendarDayGroup = memo(function CalendarDayGroup({
  label, sublabel, events, highlighted, upcoming,
}: Props) {
  if (events.length === 0) {return null;}

  return (
    <section aria-label={label} className="relative">
      {/* Sticky day header — backdrop blur keeps event rows readable behind it */}
      <div className="sticky top-0 z-10 -mx-2 px-2 py-2
                      bg-dark-bg/80 backdrop-blur-md border-b border-th-border/60">
        <div className="flex items-baseline justify-between gap-3">
          <div className="flex items-baseline gap-2.5">
            <h3 className={`text-sm font-semibold tracking-tight ${
              highlighted ? 'text-th' : 'text-th-secondary'
            }`}>
              {label}
            </h3>
            {sublabel && (
              <span className="text-[11px] text-th-dim font-medium">{sublabel}</span>
            )}
          </div>
          <span className="text-[10px] font-mono text-th-dim tabular-nums">
            {events.length} {events.length === 1 ? 'event' : 'events'}
          </span>
        </div>
        {highlighted && (
          <motion.div
            layoutId="today-underline"
            className="mt-1 h-px bg-gradient-to-r from-accent-blue/60 via-accent-cyan/60 to-transparent"
            transition={{ type: 'spring', stiffness: 260, damping: 28 }}
          />
        )}
      </div>

      <motion.div
        role="list"
        variants={container}
        initial="hidden"
        animate="show"
        className="py-1"
      >
        {events.map((ev, i) => (
          <motion.div key={`${ev.event}-${ev.ts_utc ?? i}`} role="listitem" variants={item}>
            <CalendarEventRow event={ev} upcoming={upcoming} />
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
});
