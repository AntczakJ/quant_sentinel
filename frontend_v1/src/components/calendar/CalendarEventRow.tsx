/**
 * calendar/CalendarEventRow.tsx — A single event row with expand-on-click.
 *
 * Interaction:
 *   - Click or Enter/Space toggles expansion.
 *   - Expansion reveals forecast/previous/actual comparison with delta.
 *   - High-impact rows have a subtle red glow + left accent bar.
 *   - Past rows render dimmed but remain interactive so users can review outcomes.
 */
import { memo, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown, Flame, AlertTriangle, Info } from 'lucide-react';
import { CountdownPill } from './CountdownPill';
import { eventMs, normalizeImpact, type CalendarEvent } from './types';

interface Props {
  event: CalendarEvent;
  /** True when row is in the "today" or upcoming group (enables animations). */
  upcoming?: boolean;
}

const IMPACT_VISUAL = {
  high:   { bar: 'bg-accent-red',    glow: 'shadow-[0_0_0_1px_rgb(var(--c-red)/0.15),0_8px_24px_-8px_rgb(var(--c-red)/0.25)]', Icon: Flame },
  medium: { bar: 'bg-accent-orange', glow: '',                                                                                  Icon: AlertTriangle },
  low:    { bar: 'bg-accent-blue/60',glow: '',                                                                                  Icon: Info },
} as const;

function parseNumeric(v: string | undefined): number | null {
  if (!v) {return null;}
  const cleaned = v.replace(/[%,+]/g, '').trim();
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

function formatTime(ms: number): string {
  const d = new Date(ms);
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export const CalendarEventRow = memo(function CalendarEventRow({ event, upcoming }: Props) {
  const [open, setOpen] = useState(false);
  const impact = normalizeImpact(event.impact);
  const visual = IMPACT_VISUAL[impact];
  const Icon = visual.Icon;
  const ms = eventMs(event);
  const past = ms < Date.now();

  const toggle = useCallback(() => setOpen((o) => !o), []);
  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
  }, [toggle]);

  // Delta: actual vs forecast, or actual vs previous (fallback).
  const actualN = parseNumeric(event.actual);
  const forecastN = parseNumeric(event.forecast);
  const previousN = parseNumeric(event.previous);
  const baseline = forecastN ?? previousN;
  const delta = actualN !== null && baseline !== null ? actualN - baseline : null;
  const deltaPct = delta !== null && baseline !== null && baseline !== 0
    ? (delta / Math.abs(baseline)) * 100 : null;

  return (
    <motion.div
      layout
      className={`group relative ${past ? 'opacity-55 hover:opacity-85' : ''} ${impact === 'high' ? visual.glow : ''}`}
    >
      {/* Left accent bar — impact signal */}
      <div
        className={`absolute left-0 top-2 bottom-2 w-0.5 rounded-full ${visual.bar}
                    ${upcoming && impact === 'high' ? 'animate-pulse' : ''}`}
        aria-hidden
      />

      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={toggle}
        onKeyDown={onKeyDown}
        className="flex items-center gap-3 pl-4 pr-3 py-3 rounded-lg cursor-pointer
                   border border-transparent hover:border-th-border hover:bg-dark-surface/50
                   transition-[background-color,border-color] duration-200"
      >
        {/* Time */}
        <div className="w-14 shrink-0 font-mono text-[11px] text-th-muted tabular-nums">
          {formatTime(ms)}
        </div>

        {/* Currency flag */}
        <div className="w-10 shrink-0">
          <span className={`inline-flex items-center justify-center w-full h-6 rounded
                           font-mono text-[10px] font-semibold tracking-wider
                           ${event.currency === 'USD' ? 'bg-accent-green/10 text-accent-green' :
                             event.currency === 'EUR' ? 'bg-accent-blue/10 text-accent-blue' :
                             event.currency === 'GBP' ? 'bg-accent-purple/10 text-accent-purple' :
                             'bg-dark-tertiary text-th-muted'}`}>
            {event.currency ?? '—'}
          </span>
        </div>

        {/* Event title + impact icon */}
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <Icon
            size={12}
            className={impact === 'high' ? 'text-accent-red' :
                       impact === 'medium' ? 'text-accent-orange' : 'text-accent-blue/70'}
          />
          <span className="truncate text-sm text-th font-medium">{event.event}</span>
        </div>

        {/* Countdown */}
        <div className="hidden sm:block shrink-0">
          <CountdownPill targetMs={ms} compact />
        </div>

        {/* Compact values preview */}
        <div className="hidden md:flex items-center gap-4 shrink-0 font-mono text-[11px] tabular-nums">
          {event.previous && (
            <div className="flex flex-col items-end">
              <span className="text-[9px] uppercase text-th-dim tracking-wider">Prev</span>
              <span className="text-th-muted">{event.previous}</span>
            </div>
          )}
          {event.forecast && (
            <div className="flex flex-col items-end">
              <span className="text-[9px] uppercase text-th-dim tracking-wider">Fcst</span>
              <span className="text-th-secondary">{event.forecast}</span>
            </div>
          )}
          {event.actual && (
            <div className="flex flex-col items-end">
              <span className="text-[9px] uppercase text-th-dim tracking-wider">Actual</span>
              <span className={`font-semibold ${
                delta !== null ? (delta > 0 ? 'text-accent-green' : delta < 0 ? 'text-accent-red' : 'text-th')
                               : 'text-th'}`}>
                {event.actual}
              </span>
            </div>
          )}
        </div>

        <ChevronDown
          size={14}
          className={`text-th-dim shrink-0 transition-transform duration-200
                      ${open ? 'rotate-180 text-th-secondary' : ''}`}
          aria-hidden
        />
      </div>

      {/* Expanded detail */}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="pl-4 pr-3 pb-3 pt-1 grid grid-cols-1 sm:grid-cols-3 gap-3">
              <DetailCard label="Previous" value={event.previous} />
              <DetailCard label="Forecast" value={event.forecast} emphasize />
              <DetailCard
                label="Actual"
                value={event.actual}
                valueClassName={
                  delta !== null && delta > 0 ? 'text-accent-green' :
                  delta !== null && delta < 0 ? 'text-accent-red' : ''
                }
                hint={(deltaPct !== null && delta !== null)
                  ? `${delta > 0 ? '+' : ''}${delta.toFixed(2)} (${deltaPct.toFixed(1)}%) vs ${forecastN !== null ? 'forecast' : 'previous'}`
                  : undefined}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

function DetailCard({
  label, value, emphasize, valueClassName = '', hint,
}: {
  label: string;
  value: string | undefined;
  emphasize?: boolean;
  valueClassName?: string;
  hint?: string;
}) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${
      emphasize ? 'border-accent-blue/25 bg-accent-blue/[0.04]' : 'border-th-border bg-dark-surface/40'
    }`}>
      <div className="text-[10px] uppercase tracking-wider text-th-dim font-medium">{label}</div>
      <div className={`mt-1 font-mono text-base font-semibold tabular-nums ${
        value ? (valueClassName || 'text-th') : 'text-th-dim'
      }`}>
        {value || '—'}
      </div>
      {hint && <div className="mt-1 text-[10px] text-th-muted">{hint}</div>}
    </div>
  );
}
