/**
 * pages/NewsPage.tsx — News feed + Economic Calendar
 *
 * Shows latest economic news with sentiment badges and
 * upcoming economic events with countdown timers.
 */

import { memo, useMemo, useState } from 'react';
import { Newspaper, Calendar, Clock, TrendingUp, TrendingDown, Minus, AlertTriangle, RefreshCw } from 'lucide-react';
import { usePollingQuery } from '../hooks/usePollingQuery';
import { newsAPI } from '../api/client';

/* ── Types ─────────────────────────────────────────────────────────── */

interface NewsItem {
  title: string;
  source?: string;
  published?: string;
  sentiment?: string;
  impact?: string;
  url?: string;
}

interface CalendarEvent {
  event: string;
  date: string;
  time?: string;
  currency?: string;
  impact?: string;
  forecast?: string;
  previous?: string;
  actual?: string;
}

interface NewsData {
  timestamp: string;
  news: NewsItem[];
  economic_calendar: CalendarEvent[];
}

/* ── Helpers ───────────────────────────────────────────────────────── */

const SENTIMENT_STYLES: Record<string, { bg: string; text: string; icon: typeof TrendingUp }> = {
  positive:  { bg: 'bg-accent-green/10 border-accent-green/25', text: 'text-accent-green', icon: TrendingUp },
  bullish:   { bg: 'bg-accent-green/10 border-accent-green/25', text: 'text-accent-green', icon: TrendingUp },
  negative:  { bg: 'bg-accent-red/10 border-accent-red/25',     text: 'text-accent-red',   icon: TrendingDown },
  bearish:   { bg: 'bg-accent-red/10 border-accent-red/25',     text: 'text-accent-red',   icon: TrendingDown },
  neutral:   { bg: 'bg-dark-secondary border-dark-secondary',   text: 'text-th-muted',     icon: Minus },
};

const IMPACT_STYLES: Record<string, string> = {
  high:   'bg-accent-red/15 text-accent-red border-accent-red/25',
  medium: 'bg-accent-orange/12 text-accent-orange border-accent-orange/20',
  low:    'bg-accent-blue/10 text-accent-blue border-accent-blue/20',
};

function getSentimentStyle(sentiment: string | undefined) {
  if (!sentiment) return SENTIMENT_STYLES.neutral;
  const lower = sentiment.toLowerCase();
  return SENTIMENT_STYLES[lower] ?? SENTIMENT_STYLES.neutral;
}

function getImpactStyle(impact: string | undefined) {
  if (!impact) return '';
  return IMPACT_STYLES[impact.toLowerCase()] ?? IMPACT_STYLES.low;
}

function timeAgo(dateStr: string | undefined): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  const mins = Math.floor((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return 'teraz';
  if (mins < 60) return `${mins}m temu`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h temu`;
  return `${Math.floor(hrs / 24)}d temu`;
}

function timeUntil(dateStr: string, timeStr?: string): string {
  let combined = dateStr;
  if (timeStr) combined += `T${timeStr}`;
  const d = new Date(combined);
  if (isNaN(d.getTime())) return '';
  const diff = d.getTime() - Date.now();
  if (diff <= 0) return 'juz bylo';
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `za ${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `za ${hrs}h ${mins % 60}m`;
  return `za ${Math.floor(hrs / 24)}d`;
}

/* ── News Card ─────────────────────────────────────────────────────── */

const NewsCard = memo(function NewsCard({ item }: { item: NewsItem }) {
  const style = getSentimentStyle(item.sentiment);
  const Icon = style.icon;

  return (
    <div className={`rounded-lg border p-3 ${style.bg} transition-colors`}>
      <div className="flex items-start gap-2">
        <Icon size={14} className={`${style.text} mt-0.5 flex-shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-th leading-relaxed">{item.title}</div>
          <div className="flex items-center gap-2 mt-1.5 text-[10px]">
            {item.sentiment && (
              <span className={`font-bold uppercase ${style.text}`}>{item.sentiment}</span>
            )}
            {item.impact && (
              <span className={`px-1.5 py-0.5 rounded border text-[9px] font-medium ${getImpactStyle(item.impact)}`}>
                {item.impact.toUpperCase()}
              </span>
            )}
            {item.source && <span className="text-th-dim">{item.source}</span>}
            {item.published && <span className="text-th-dim">{timeAgo(item.published)}</span>}
          </div>
        </div>
      </div>
    </div>
  );
});

/* ── Calendar Row ──────────────────────────────────────────────────── */

const CalendarRow = memo(function CalendarRow({ event }: { event: CalendarEvent }) {
  const countdown = timeUntil(event.date, event.time);
  const isPast = countdown === 'juz bylo';

  return (
    <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-colors ${
      isPast ? 'bg-dark-surface border-dark-secondary opacity-60'
             : 'bg-dark-bg border-dark-secondary hover:border-dark-tertiary'
    }`}>
      {/* Impact dot */}
      {event.impact && (
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
          event.impact.toLowerCase() === 'high' ? 'bg-accent-red' :
          event.impact.toLowerCase() === 'medium' ? 'bg-accent-orange' : 'bg-accent-blue'
        }`} />
      )}

      {/* Event name */}
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-th truncate">{event.event}</div>
        <div className="flex items-center gap-2 text-[10px] text-th-dim mt-0.5">
          {event.currency && <span className="font-bold text-accent-blue">{event.currency}</span>}
          <span>{event.date}{event.time ? ` ${event.time}` : ''}</span>
        </div>
      </div>

      {/* Forecast / Previous / Actual */}
      <div className="flex items-center gap-3 text-[10px] text-right">
        {event.forecast && (
          <div>
            <div className="text-th-dim">Forecast</div>
            <div className="font-mono font-medium text-th-secondary">{event.forecast}</div>
          </div>
        )}
        {event.previous && (
          <div>
            <div className="text-th-dim">Previous</div>
            <div className="font-mono font-medium text-th-secondary">{event.previous}</div>
          </div>
        )}
        {event.actual && (
          <div>
            <div className="text-th-dim">Actual</div>
            <div className="font-mono font-bold text-accent-green">{event.actual}</div>
          </div>
        )}
      </div>

      {/* Countdown */}
      <div className={`text-[10px] font-medium min-w-[60px] text-right ${
        isPast ? 'text-th-dim' : 'text-accent-orange'
      }`}>
        <Clock size={8} className="inline mr-0.5" />
        {countdown}
      </div>
    </div>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────── */

type Tab = 'news' | 'calendar';

export default function NewsPage() {
  const [tab, setTab] = useState<Tab>('news');

  const { data, isLoading } = usePollingQuery<NewsData>(
    'news-calendar',
    () => newsAPI.getNews(),
    120_000, // 2 min
  );

  const news = data?.news ?? [];
  const calendar = data?.economic_calendar ?? [];

  // Separate upcoming and past events
  const { upcoming, past } = useMemo(() => {
    const now = Date.now();
    const up: CalendarEvent[] = [];
    const pa: CalendarEvent[] = [];
    for (const ev of calendar) {
      let d = new Date(ev.date + (ev.time ? `T${ev.time}` : ''));
      if (isNaN(d.getTime())) d = new Date(ev.date);
      if (d.getTime() > now) up.push(ev);
      else pa.push(ev);
    }
    // Sort upcoming by date asc, past by date desc
    up.sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
    pa.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
    return { upcoming: up, past: pa.slice(0, 10) };
  }, [calendar]);

  return (
    <div className="space-y-4 max-w-[1200px] mx-auto">
      {/* Tab bar */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setTab('news')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            tab === 'news'
              ? 'bg-accent-blue/12 text-accent-blue border border-accent-blue/25'
              : 'text-th-muted hover:text-th-secondary border border-transparent'
          }`}
        >
          <Newspaper size={14} />
          News
          {news.length > 0 && <span className="text-[10px] opacity-75">({news.length})</span>}
        </button>
        <button
          onClick={() => setTab('calendar')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            tab === 'calendar'
              ? 'bg-accent-orange/12 text-accent-orange border border-accent-orange/25'
              : 'text-th-muted hover:text-th-secondary border border-transparent'
          }`}
        >
          <Calendar size={14} />
          Calendar
          {upcoming.length > 0 && (
            <span className="text-[10px] bg-accent-orange/20 text-accent-orange px-1 rounded">
              {upcoming.length}
            </span>
          )}
        </button>
      </div>

      {/* Loading */}
      {isLoading && !data && (
        <div className="card flex items-center justify-center py-12 gap-2 text-th-muted text-sm">
          <RefreshCw size={14} className="animate-spin" />
          Ladowanie danych...
        </div>
      )}

      {/* News tab */}
      {tab === 'news' && (
        <div className="card">
          <h2 className="section-title mb-3">
            Economic News
            <span className="text-xs text-th-muted font-normal ml-2">— market-moving headlines</span>
          </h2>
          {news.length === 0 ? (
            <div className="text-xs text-th-muted text-center py-8">
              Brak newsow — dane pojawia sie gdy backend pobierze newsy z feedow
            </div>
          ) : (
            <div className="space-y-2">
              {news.map((item, i) => <NewsCard key={i} item={item} />)}
            </div>
          )}
        </div>
      )}

      {/* Calendar tab */}
      {tab === 'calendar' && (
        <div className="space-y-4">
          {/* Upcoming events */}
          <div className="card">
            <h2 className="section-title mb-3">
              <AlertTriangle size={14} className="inline text-accent-orange mr-1" />
              Upcoming Events
              {upcoming.length > 0 && (
                <span className="text-xs text-accent-orange font-normal ml-2">
                  — najblizszy: {timeUntil(upcoming[0].date, upcoming[0].time)}
                </span>
              )}
            </h2>
            {upcoming.length === 0 ? (
              <div className="text-xs text-th-muted text-center py-6">Brak nadchodzacych eventow</div>
            ) : (
              <div className="space-y-1.5">
                {upcoming.map((ev, i) => <CalendarRow key={i} event={ev} />)}
              </div>
            )}
          </div>

          {/* Past events */}
          {past.length > 0 && (
            <div className="card">
              <h2 className="section-title mb-3">
                Recent Events
                <span className="text-xs text-th-muted font-normal ml-2">— last 10</span>
              </h2>
              <div className="space-y-1.5">
                {past.map((ev, i) => <CalendarRow key={i} event={ev} />)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
