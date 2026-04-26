/**
 * pages/NewsPage.tsx — News feed + premium Economic Calendar.
 *
 * Two tabs sharing the same poll (single `/api/analysis/news` call every 2 min):
 *   - News    : RSS-aggregated market-moving headlines with sentiment
 *   - Calendar: day-grouped timeline of economic events (Motion-animated)
 *
 * The calendar sub-tree is isolated under `components/calendar/` so this page
 * stays thin and focused on layout orchestration.
 */

import { memo, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Newspaper, Calendar as CalendarIcon,
  TrendingUp, TrendingDown, Minus, RefreshCw,
} from 'lucide-react';
import { usePollingQuery } from '../hooks/usePollingQuery';
import { newsAPI } from '../api/client';
import { CalendarTab, type CalendarEvent } from '../components/calendar';

/* ── Types ─────────────────────────────────────────────────────────── */

interface NewsItem {
  title: string;
  source?: string;
  published?: string;
  sentiment?: string;
  impact?: string;
  url?: string;
}

interface NewsData {
  timestamp: string;
  news: NewsItem[];
  economic_calendar: CalendarEvent[];
}

type Tab = 'news' | 'calendar';

/* ── Helpers ───────────────────────────────────────────────────────── */

const SENTIMENT_STYLES = {
  positive: { bg: 'bg-accent-green/[0.06] border-accent-green/20', text: 'text-accent-green', icon: TrendingUp },
  bullish:  { bg: 'bg-accent-green/[0.06] border-accent-green/20', text: 'text-accent-green', icon: TrendingUp },
  negative: { bg: 'bg-accent-red/[0.06] border-accent-red/20',     text: 'text-accent-red',   icon: TrendingDown },
  bearish:  { bg: 'bg-accent-red/[0.06] border-accent-red/20',     text: 'text-accent-red',   icon: TrendingDown },
  neutral:  { bg: 'bg-dark-surface/40 border-th-border',           text: 'text-th-muted',     icon: Minus },
} as const;

const IMPACT_STYLES: Record<string, string> = {
  high:   'bg-accent-red/12 text-accent-red border-accent-red/25',
  medium: 'bg-accent-orange/10 text-accent-orange border-accent-orange/20',
  low:    'bg-accent-blue/[0.08] text-accent-blue border-accent-blue/20',
};

function getSentimentStyle(sentiment: string | undefined) {
  const key = (sentiment ?? 'neutral').toLowerCase() as keyof typeof SENTIMENT_STYLES;
  return SENTIMENT_STYLES[key] ?? SENTIMENT_STYLES.neutral;
}

function getImpactStyle(impact: string | undefined): string {
  return IMPACT_STYLES[(impact ?? '').toLowerCase()] ?? IMPACT_STYLES.low;
}

function timeAgo(dateStr: string | undefined): string {
  if (!dateStr) {return '';}
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) {return '';}
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (mins < 1) {return 'now';}
  if (mins < 60) {return `${mins}m ago`;}
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) {return `${hrs}h ago`;}
  return `${Math.floor(hrs / 24)}d ago`;
}

/* ── News Card ─────────────────────────────────────────────────────── */

const NewsCard = memo(function NewsCard({ item, index }: { item: NewsItem; index: number }) {
  const style = getSentimentStyle(item.sentiment);
  const Icon = style.icon;

  return (
    <motion.a
      href={item.url || undefined}
      target={item.url ? '_blank' : undefined}
      rel={item.url ? 'noopener noreferrer' : undefined}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.02, 0.3), duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
      whileHover={{ y: -1 }}
      className={`block rounded-xl border p-3.5 transition-colors ${style.bg}
                  ${item.url ? 'cursor-pointer hover:border-th-border-h' : 'cursor-default'}`}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 p-1.5 rounded-lg ${style.text} bg-current/[0.08]`}>
          <Icon size={14} className={style.text} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium text-th leading-snug">{item.title}</div>
          <div className="flex items-center gap-2 mt-2 text-[10px] flex-wrap">
            {item.sentiment && (
              <span className={`font-semibold uppercase tracking-wider ${style.text}`}>
                {item.sentiment}
              </span>
            )}
            {item.impact && (
              <span className={`px-1.5 py-0.5 rounded border text-[9px] font-medium uppercase tracking-wider ${getImpactStyle(item.impact)}`}>
                {item.impact}
              </span>
            )}
            {item.source && <span className="text-th-dim font-medium">{item.source}</span>}
            {item.published && <span className="text-th-dim">· {timeAgo(item.published)}</span>}
          </div>
        </div>
      </div>
    </motion.a>
  );
});

/* ── Tab button ────────────────────────────────────────────────────── */

function TabButton({
  active, onClick, icon: Icon, label, count, accent,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Newspaper;
  label: string;
  count?: number;
  accent: 'blue' | 'orange';
}) {
  const accentText = accent === 'blue' ? 'text-accent-blue' : 'text-accent-orange';
  const accentBar  = accent === 'blue' ? 'bg-accent-blue'   : 'bg-accent-orange';

  return (
    <button
      onClick={onClick}
      aria-selected={active}
      role="tab"
      className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors
                  ${active ? accentText : 'text-th-muted hover:text-th-secondary'}`}
    >
      <Icon size={14} />
      <span>{label}</span>
      {count !== undefined && count > 0 && (
        <span className={`font-mono text-[10px] font-semibold tabular-nums
                         ${active ? 'text-current opacity-80' : 'text-th-dim'}`}>
          {count}
        </span>
      )}
      {active && (
        <motion.span
          layoutId="newspage-tab-underline"
          className={`absolute left-0 right-0 -bottom-px h-0.5 rounded-full ${accentBar}`}
          transition={{ type: 'spring', stiffness: 380, damping: 30 }}
        />
      )}
    </button>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────── */

export default function NewsPage() {
  const [tab, setTab] = useState<Tab>('calendar');

  const { data, isLoading, refetch } = usePollingQuery<NewsData>(
    'news-calendar',
    () => newsAPI.getNews(),
    120_000,
  );

  const news = data?.news ?? [];
  const calendar = data?.economic_calendar ?? [];

  // Upcoming count for the Calendar tab badge — informs the user at a glance.
  const upcomingCount = useMemo(() => {
    const now = Date.now();
    return calendar.filter((e) => {
      const ts = typeof e.ts_utc === 'number' ? e.ts_utc * 1000
               : Date.parse(e.date_utc ?? e.date);
      return !isNaN(ts) && ts > now;
    }).length;
  }, [calendar]);

  return (
    <div className="max-w-[1200px] mx-auto">
      {/* Page header */}
      <header className="mb-5 flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-display font-semibold tracking-tight text-th">
            Market Intelligence
          </h1>
          <p className="mt-1 text-sm text-th-muted">
            Macro calendar and real-time headlines that move gold.
          </p>
        </div>
        <button
          onClick={() => { void refetch(); }}
          aria-label="Refresh"
          className="group p-2 rounded-lg text-th-muted hover:text-th hover:bg-th-hover
                     transition-colors"
        >
          <RefreshCw
            size={14}
            className={`transition-transform duration-500 group-hover:rotate-180
                        ${isLoading ? 'animate-spin' : ''}`}
          />
        </button>
      </header>

      {/* Tab bar */}
      <div role="tablist" className="relative flex items-center gap-1 border-b border-th-border mb-5">
        <TabButton
          active={tab === 'calendar'}
          onClick={() => setTab('calendar')}
          icon={CalendarIcon}
          label="Calendar"
          count={upcomingCount}
          accent="orange"
        />
        <TabButton
          active={tab === 'news'}
          onClick={() => setTab('news')}
          icon={Newspaper}
          label="News"
          count={news.length}
          accent="blue"
        />
      </div>

      {/* Tab content — crossfade between panels */}
      <AnimatePresence mode="wait">
        {tab === 'calendar' ? (
          <motion.div
            key="calendar"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            role="tabpanel"
          >
            <CalendarTab events={calendar} loading={isLoading && calendar.length === 0} />
          </motion.div>
        ) : (
          <motion.div
            key="news"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            role="tabpanel"
            className="card"
          >
            <div className="flex items-baseline justify-between mb-4">
              <h2 className="section-title">Economic News</h2>
              <span className="text-xs text-th-muted">Market-moving headlines</span>
            </div>
            {isLoading && news.length === 0 ? (
              <div className="flex items-center justify-center py-12 gap-2 text-th-muted text-sm">
                <RefreshCw size={14} className="animate-spin" />
                Loading news...
              </div>
            ) : news.length === 0 ? (
              <div className="text-sm text-th-muted text-center py-12">
                No news available right now. The feed will retry shortly.
              </div>
            ) : (
              <div className="space-y-2">
                {news.map((item, i) => <NewsCard key={`${item.title}-${i}`} item={item} index={i} />)}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
