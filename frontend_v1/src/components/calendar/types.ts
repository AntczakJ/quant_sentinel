/**
 * calendar/types.ts — Shared types for the Calendar feature.
 *
 * Backend contract (src/data/news.py get_economic_calendar):
 *   - `date_utc` — ISO 8601 string with timezone
 *   - `ts_utc`   — unix epoch seconds (preferred for arithmetic)
 *
 * We keep the legacy `date`/`time` fields for backwards compatibility with
 * other consumers (OpenAI agent, tests) but the UI reads ts_utc exclusively.
 */

export type Impact = 'high' | 'medium' | 'low';

export type Currency =
  | 'USD' | 'EUR' | 'GBP' | 'JPY' | 'CHF'
  | 'AUD' | 'CAD' | 'NZD' | 'CNY' | 'All';

export interface CalendarEvent {
  event: string;
  date: string;
  time?: string;
  currency?: string;
  impact?: string;
  forecast?: string;
  previous?: string;
  actual?: string;
  date_utc?: string;
  ts_utc?: number;
}

export interface CalendarFilterState {
  currencies: Set<string>;   // empty = all
  impacts: Set<Impact>;      // empty = all
  search: string;
}

/** Parse event timestamp with fallbacks. Returns ms epoch or NaN. */
export function eventMs(ev: CalendarEvent): number {
  if (typeof ev.ts_utc === 'number') {return ev.ts_utc * 1000;}
  if (ev.date_utc) {
    const t = Date.parse(ev.date_utc);
    if (!isNaN(t)) {return t;}
  }
  const combined = ev.time ? `${ev.date}T${ev.time}` : ev.date;
  return Date.parse(combined);
}

export function normalizeImpact(raw: string | undefined): Impact {
  const v = (raw ?? '').toLowerCase();
  if (v === 'high' || v === 'medium' || v === 'low') {return v;}
  return 'low';
}
