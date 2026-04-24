/**
 * WeekendBanner.tsx — Shown when XAU/USD market is closed for the weekend.
 *
 * Gold spot trades ~23:00 UTC Sunday through ~21:00 UTC Friday. During
 * the weekend window the scanner runs cycles but can't produce trades —
 * this banner explains that so "0 new trades" doesn't look like a bug.
 *
 * Also useful for daily 23:00-24:00 UTC break, but that's only 1 hour
 * and we don't show a banner for it (too noisy). Weekend only.
 */

import { memo } from 'react';
import { Moon } from 'lucide-react';

function isWeekend(): boolean {
  // Gold closes ~Fri 21:00 UTC, reopens ~Sun 21:00 UTC.
  // Using 21:00 boundary in UTC is close enough; brokers vary slightly.
  const now = new Date();
  const utcDay = now.getUTCDay(); // 0=Sun, 5=Fri, 6=Sat
  const utcHour = now.getUTCHours();

  if (utcDay === 6) {
    return true; // Saturday all day
  }
  if (utcDay === 5 && utcHour >= 21) {
    return true; // Friday after 21:00 UTC
  }
  if (utcDay === 0 && utcHour < 21) {
    return true; // Sunday before 21:00 UTC
  }
  return false;
}

function nextOpenLabel(): string {
  const now = new Date();
  const utcDay = now.getUTCDay();
  if (utcDay === 5) {
    return 'Sun 21:00 UTC';
  }
  if (utcDay === 6) {
    return 'Sun 21:00 UTC';
  }
  return 'Sun 21:00 UTC'; // Default fallback
}

function WeekendBannerInner() {
  if (!isWeekend()) {
    return null;
  }
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-dark-bg-soft border border-dark-secondary rounded-lg text-xs">
      <Moon size={14} className="text-accent-blue shrink-0" />
      <div className="flex-1">
        <span className="font-medium text-th-primary">Weekend — XAU/USD closed.</span>{' '}
        <span className="text-th-muted">
          Scanner idle until {nextOpenLabel()}. Watchdog + dashboards still live.
        </span>
      </div>
    </div>
  );
}

export const WeekendBanner = memo(WeekendBannerInner);
