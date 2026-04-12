/**
 * calendar/CalendarTab.tsx — Main calendar view.
 *
 * Orchestrates:
 *   1. Fetch (consumed from parent via props — parent already polls).
 *   2. Filter state (currency/impact/search).
 *   3. Day grouping with "Today"/"Tomorrow" labels.
 *   4. Hero summary + filters + grouped timeline.
 *
 * Performance:
 *   - useMemo on filter+group pipeline so typing in search stays 60fps.
 *   - Day grouping is pure over sorted input — linear.
 *   - Rows are memoized (CalendarEventRow uses React.memo).
 */
import { memo, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { CalendarX } from 'lucide-react';
import { CalendarHero } from './CalendarHero';
import { CalendarFilters } from './CalendarFilters';
import { CalendarDayGroup } from './CalendarDayGroup';
import {
  eventMs, normalizeImpact,
  type CalendarEvent, type CalendarFilterState, type Impact,
} from './types';

interface Props {
  events: CalendarEvent[];
  loading?: boolean;
}

/** Day bucket: identified by YYYY-MM-DD in the viewer's local timezone. */
interface DayBucket {
  key: string;
  label: string;
  sublabel?: string;
  ms: number;
  events: CalendarEvent[];
}

const MS_DAY = 24 * 3600 * 1000;

function localDayKey(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function dayLabel(ms: number, nowMs: number): { label: string; sublabel: string } {
  const d = new Date(ms);
  const today = new Date(nowMs);
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d.setHours(0, 0, 0, 0) - today.getTime()) / MS_DAY);
  const weekday = new Date(ms).toLocaleDateString(undefined, { weekday: 'long' });
  const dateStr = new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

  if (diff === 0) {return { label: 'Today',    sublabel: `${weekday} · ${dateStr}` };}
  if (diff === 1) {return { label: 'Tomorrow', sublabel: `${weekday} · ${dateStr}` };}
  if (diff === -1) {return { label: 'Yesterday', sublabel: `${weekday} · ${dateStr}` };}
  return { label: weekday, sublabel: dateStr };
}

function applyFilters(events: CalendarEvent[], f: CalendarFilterState): CalendarEvent[] {
  const q = f.search.trim().toLowerCase();
  return events.filter((ev) => {
    if (f.impacts.size && !f.impacts.has(normalizeImpact(ev.impact))) {return false;}
    if (f.currencies.size && ev.currency && !f.currencies.has(ev.currency)) {return false;}
    if (q && !ev.event.toLowerCase().includes(q)) {return false;}
    return true;
  });
}

function groupByDay(events: CalendarEvent[], nowMs: number): DayBucket[] {
  const buckets = new Map<string, DayBucket>();
  for (const ev of events) {
    const ms = eventMs(ev);
    if (isNaN(ms)) {continue;}
    const key = localDayKey(ms);
    let bucket = buckets.get(key);
    if (!bucket) {
      const { label, sublabel } = dayLabel(ms, nowMs);
      bucket = { key, label, sublabel, ms, events: [] };
      buckets.set(key, bucket);
    }
    bucket.events.push(ev);
  }
  return Array.from(buckets.values()).sort((a, b) => a.ms - b.ms);
}

export const CalendarTab = memo(function CalendarTab({ events, loading }: Props) {
  const [filters, setFilters] = useState<CalendarFilterState>({
    currencies: new Set(),
    impacts: new Set(),
    search: '',
  });

  const {
    filtered, buckets, hero, impactCounts, availableCurrencies,
  } = useMemo(() => {
    const now = Date.now();
    const filtered = applyFilters(events, filters);
    const buckets = groupByDay(filtered, now);

    // Hero stats computed from filtered view (so they reflect what user sees).
    let nextEvent: CalendarEvent | null = null;
    let nextEventMs: number | null = null;
    let highImpact24h = 0;
    for (const ev of filtered) {
      const ms = eventMs(ev);
      if (isNaN(ms) || ms < now) {continue;}
      if (!nextEvent) { nextEvent = ev; nextEventMs = ms; }
      if (ms < now + MS_DAY && normalizeImpact(ev.impact) === 'high') {
        highImpact24h += 1;
      }
    }

    // Impact counts from the *unfiltered* set (excluding search match) so the
    // chip labels tell the user how many events each impact tier would yield.
    const impactCounts: Record<Impact, number> = { high: 0, medium: 0, low: 0 };
    for (const ev of events) {impactCounts[normalizeImpact(ev.impact)] += 1;}

    const availableCurrencies = Array.from(
      new Set(events.map((e) => e.currency).filter(Boolean) as string[])
    ).sort();

    return {
      filtered,
      buckets,
      hero: { nextEvent, nextEventMs, highImpact24h, totalVisible: filtered.length },
      impactCounts,
      availableCurrencies,
    };
  }, [events, filters]);

  return (
    <div className="space-y-5">
      <CalendarHero {...hero} />

      <div className="card">
        <CalendarFilters
          state={filters}
          availableCurrencies={availableCurrencies}
          impactCounts={impactCounts}
          onChange={setFilters}
        />
      </div>

      {/* Loading skeleton — only when we have no data yet */}
      {loading && events.length === 0 && (
        <div className="card space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 py-3 px-3 animate-pulse">
              <div className="h-3 w-12 bg-dark-tertiary rounded" />
              <div className="h-6 w-10 bg-dark-tertiary rounded" />
              <div className="h-3 flex-1 bg-dark-tertiary rounded" />
              <div className="h-3 w-16 bg-dark-tertiary rounded" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state after filtering */}
      <AnimatePresence mode="wait">
        {!loading && filtered.length === 0 && events.length > 0 && (
          <motion.div
            key="empty"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="card flex flex-col items-center justify-center py-12 gap-3"
          >
            <CalendarX size={32} className="text-th-dim" />
            <div className="text-sm text-th-secondary">No events match your filters.</div>
            <button
              onClick={() => setFilters({ currencies: new Set(), impacts: new Set(), search: '' })}
              className="text-xs text-accent-blue hover:underline"
            >
              Clear filters
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Empty state when backend returned nothing at all */}
      {!loading && events.length === 0 && (
        <div className="card flex flex-col items-center justify-center py-12 gap-3">
          <CalendarX size={32} className="text-th-dim" />
          <div className="text-sm text-th-secondary">
            No calendar data available.
          </div>
          <div className="text-[11px] text-th-dim max-w-sm text-center">
            The backend couldn&apos;t reach the ForexFactory feed. It will retry
            on the next poll (every 2 minutes).
          </div>
        </div>
      )}

      {/* Day-grouped timeline */}
      {buckets.length > 0 && (
        <div className="card space-y-6">
          {buckets.map((bucket) => {
            const now = Date.now();
            const isToday = bucket.label === 'Today';
            const isPastDay = bucket.ms + MS_DAY < now;
            return (
              <CalendarDayGroup
                key={bucket.key}
                label={bucket.label}
                sublabel={bucket.sublabel}
                events={bucket.events}
                highlighted={isToday}
                upcoming={!isPastDay}
              />
            );
          })}
        </div>
      )}
    </div>
  );
});
