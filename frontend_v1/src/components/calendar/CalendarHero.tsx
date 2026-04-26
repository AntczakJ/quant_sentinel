/**
 * calendar/CalendarHero.tsx — Top summary strip.
 *
 * Shows at-a-glance info that matters to a trader:
 *   - Next event (with countdown)
 *   - Count of high-impact events in the next 24h
 *   - Total events in the visible window
 *
 * Three tiles, equal visual weight, subtle hover lift. This is the
 * "oniesmielajacy" element — pixel-detailed typography + soft gradient overlay.
 */
import { memo } from 'react';
import { motion } from 'motion/react';
import { Clock, Flame, CalendarDays } from 'lucide-react';
import { CountdownPill } from './CountdownPill';
import type { CalendarEvent } from './types';

interface Props {
  nextEvent: CalendarEvent | null;
  nextEventMs: number | null;
  highImpact24h: number;
  totalVisible: number;
}

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

const tileVariants = {
  hidden: { opacity: 0, y: 12 },
  show:   (i: number) => ({
    opacity: 1, y: 0,
    transition: { delay: i * 0.06, duration: 0.4, ease: EASE_OUT },
  }),
} as const;

export const CalendarHero = memo(function CalendarHero({
  nextEvent, nextEventMs, highImpact24h, totalVisible,
}: Props) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <HeroTile index={0} icon={<Clock size={14} />} label="Next event" accent="blue">
        {nextEvent && nextEventMs !== null ? (
          <>
            <div className="text-[15px] font-semibold text-th leading-tight truncate">
              {nextEvent.event}
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-th-muted">
              <span className="font-mono font-semibold">{nextEvent.currency}</span>
              <span className="text-th-dim">•</span>
              <CountdownPill targetMs={nextEventMs} />
            </div>
          </>
        ) : (
          <div className="text-sm text-th-dim">No upcoming events</div>
        )}
      </HeroTile>

      <HeroTile index={1} icon={<Flame size={14} />} label="High impact · 24h" accent="red">
        <div className="flex items-baseline gap-2">
          <div className="text-3xl font-display font-semibold tabular-nums text-th tracking-tight">
            {highImpact24h}
          </div>
          <div className="text-[11px] text-th-muted pb-1">market-moving</div>
        </div>
      </HeroTile>

      <HeroTile index={2} icon={<CalendarDays size={14} />} label="Events in view" accent="cyan">
        <div className="flex items-baseline gap-2">
          <div className="text-3xl font-display font-semibold tabular-nums text-th tracking-tight">
            {totalVisible}
          </div>
          <div className="text-[11px] text-th-muted pb-1">scheduled</div>
        </div>
      </HeroTile>
    </div>
  );
});

function HeroTile({
  index, icon, label, children, accent,
}: {
  index: number;
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
  accent: 'blue' | 'red' | 'cyan';
}) {
  const gradient = {
    blue: 'from-accent-blue/10 to-transparent',
    red:  'from-accent-red/10 to-transparent',
    cyan: 'from-accent-cyan/10 to-transparent',
  }[accent];
  const dot = {
    blue: 'text-accent-blue',
    red:  'text-accent-red',
    cyan: 'text-accent-cyan',
  }[accent];

  return (
    <motion.div
      custom={index}
      variants={tileVariants}
      initial="hidden"
      animate="show"
      whileHover={{ y: -2 }}
      transition={{ type: 'spring', stiffness: 400, damping: 28 }}
      className="relative overflow-hidden rounded-xl border border-th-border bg-dark-surface/60 p-4"
    >
      {/* Soft accent wash */}
      <div className={`absolute inset-0 bg-gradient-to-br ${gradient} pointer-events-none`} aria-hidden />

      <div className="relative">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-th-dim font-medium">
          <span className={dot}>{icon}</span>
          <span>{label}</span>
        </div>
        <div className="mt-2">{children}</div>
      </div>
    </motion.div>
  );
}
