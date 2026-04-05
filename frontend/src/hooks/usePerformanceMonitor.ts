/**
 * src/hooks/usePerformanceMonitor.ts — Lightweight Web Vitals + custom metrics
 *
 * Logs FCP, LCP, FID, CLS, and custom app metrics to console in development.
 * In production, these could be sent to an analytics endpoint.
 */

interface PerfMetric {
  name: string;
  value: number;
  rating: 'good' | 'needs-improvement' | 'poor';
}

function rateMetric(name: string, value: number): PerfMetric['rating'] {
  const thresholds: Record<string, [number, number]> = {
    FCP: [1800, 3000],
    LCP: [2500, 4000],
    FID: [100, 300],
    CLS: [0.1, 0.25],
    TTFB: [800, 1800],
  };
  const [good, poor] = thresholds[name] ?? [Infinity, Infinity];
  if (value <= good) return 'good';
  if (value <= poor) return 'needs-improvement';
  return 'poor';
}

const COLORS: Record<PerfMetric['rating'], string> = {
  good: 'color: #22c55e',
  'needs-improvement': 'color: #f59e0b',
  poor: 'color: #ef4444',
};

function logMetric(metric: PerfMetric) {
  if (import.meta.env.PROD) return;
  const style = COLORS[metric.rating];
  console.log(
    `%c⚡ ${metric.name}: ${metric.value.toFixed(1)}ms [${metric.rating}]`,
    style
  );
}

/**
 * Call once on app mount to start collecting Web Vitals via PerformanceObserver.
 */
export function initPerformanceMonitoring(): void {
  if (typeof window === 'undefined' || !('PerformanceObserver' in window)) return;

  // First Contentful Paint
  try {
    const fcp = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === 'first-contentful-paint') {
          logMetric({ name: 'FCP', value: entry.startTime, rating: rateMetric('FCP', entry.startTime) });
        }
      }
    });
    fcp.observe({ type: 'paint', buffered: true });
  } catch { /* not supported */ }

  // Largest Contentful Paint
  try {
    const lcp = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const last = entries[entries.length - 1];
      if (last) {
        logMetric({ name: 'LCP', value: last.startTime, rating: rateMetric('LCP', last.startTime) });
      }
    });
    lcp.observe({ type: 'largest-contentful-paint', buffered: true });
  } catch { /* not supported */ }

  // Cumulative Layout Shift
  try {
    let clsValue = 0;
    const cls = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!(entry as any).hadRecentInput) {
          clsValue += (entry as any).value ?? 0;
        }
      }
      logMetric({ name: 'CLS', value: clsValue, rating: rateMetric('CLS', clsValue) });
    });
    cls.observe({ type: 'layout-shift', buffered: true });
  } catch { /* not supported */ }

  // Navigation timing (TTFB)
  try {
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming;
    if (nav) {
      const ttfb = nav.responseStart - nav.requestStart;
      logMetric({ name: 'TTFB', value: ttfb, rating: rateMetric('TTFB', ttfb) });
    }
  } catch { /* not supported */ }
}

