/**
 * calendar/CalendarFilters.tsx — Currency + impact chips with animated selection.
 *
 * Selection model:
 *   - Empty set = "all" (no filter applied).
 *   - Click chip toggles membership.
 *   - Clear button resets both filter axes + search.
 *
 * The animated pill behind the active chip uses Motion's `layoutId` so it
 * slides smoothly between selections instead of hard-cutting.
 */
import { memo } from 'react';
import { motion } from 'motion/react';
import { Search, X, Flame, AlertTriangle, Info } from 'lucide-react';
import type { CalendarFilterState, Impact } from './types';

interface Props {
  state: CalendarFilterState;
  /** All currencies present in the data — only these chips are rendered. */
  availableCurrencies: string[];
  onChange: (next: CalendarFilterState) => void;
  /** Counts per-impact for badge labels. */
  impactCounts: Record<Impact, number>;
}

const IMPACTS: { key: Impact; label: string; icon: typeof Flame; tone: string }[] = [
  { key: 'high',   label: 'High',   icon: Flame,         tone: 'text-accent-red' },
  { key: 'medium', label: 'Medium', icon: AlertTriangle, tone: 'text-accent-orange' },
  { key: 'low',    label: 'Low',    icon: Info,          tone: 'text-accent-blue' },
];

function toggle<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) {next.delete(value);} else {next.add(value);}
  return next;
}

export const CalendarFilters = memo(function CalendarFilters({
  state, availableCurrencies, onChange, impactCounts,
}: Props) {
  const hasAnyFilter =
    state.currencies.size > 0 || state.impacts.size > 0 || state.search.length > 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Search + clear */}
      <div className="relative">
        <Search
          size={14}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-th-dim pointer-events-none"
        />
        <input
          type="text"
          value={state.search}
          onChange={(e) => onChange({ ...state, search: e.target.value })}
          placeholder="Search events (e.g. CPI, FOMC, Powell)"
          aria-label="Search calendar events"
          className="w-full h-10 pl-9 pr-10 rounded-lg bg-dark-surface/60 border border-th-border
                     text-sm text-th placeholder:text-th-dim
                     focus:outline-none focus:border-accent-blue/50
                     focus:bg-dark-surface transition-colors"
        />
        {hasAnyFilter && (
          <button
            type="button"
            onClick={() => onChange({ currencies: new Set(), impacts: new Set(), search: '' })}
            aria-label="Clear all filters"
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-md
                       text-th-dim hover:text-th hover:bg-th-hover transition-colors"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Impact chips */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[10px] uppercase tracking-wider text-th-dim font-medium mr-1">
          Impact
        </span>
        {IMPACTS.map(({ key, label, icon: Icon, tone }) => {
          const active = state.impacts.has(key);
          return (
            <button
              key={key}
              onClick={() => onChange({ ...state, impacts: toggle(state.impacts, key) })}
              aria-pressed={active}
              className={`relative px-2.5 py-1 rounded-full text-[11px] font-medium
                          flex items-center gap-1.5 transition-colors
                          ${active
                            ? 'text-th border border-th-border-h'
                            : 'text-th-muted border border-transparent hover:text-th-secondary hover:border-th-border'}`}
            >
              {active && (
                <motion.span
                  layoutId="impact-pill"
                  className="absolute inset-0 rounded-full bg-dark-tertiary"
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
              <span className="relative flex items-center gap-1.5">
                <Icon size={11} className={tone} />
                {label}
                <span className="font-mono text-th-dim">{impactCounts[key]}</span>
              </span>
            </button>
          );
        })}
      </div>

      {/* Currency chips */}
      {availableCurrencies.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider text-th-dim font-medium mr-1">
            Currency
          </span>
          {availableCurrencies.map((curr) => {
            const active = state.currencies.has(curr);
            return (
              <button
                key={curr}
                onClick={() => onChange({ ...state, currencies: toggle(state.currencies, curr) })}
                aria-pressed={active}
                className={`px-2 py-1 rounded-md font-mono text-[11px] font-semibold transition-colors
                            ${active
                              ? 'bg-accent-blue/15 text-accent-blue border border-accent-blue/30'
                              : 'text-th-muted border border-th-border hover:text-th hover:border-th-border-h'}`}
              >
                {curr}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
});
