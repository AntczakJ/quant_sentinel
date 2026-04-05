/**
 * src/hooks/usePrefetchRoutes.ts — Preload lazy page chunks during idle time
 *
 * After the initial page renders, uses requestIdleCallback to pre-import
 * adjacent route chunks so that navigation feels instant.
 */

const routes = [
  () => import('../pages/ChartPage'),
  () => import('../pages/AnalysisPage'),
  () => import('../pages/TradesPage'),
  () => import('../pages/ModelsPage'),
  () => import('../pages/AgentPage'),
];

let prefetched = false;

export function prefetchAllRoutes(): void {
  if (prefetched) {return;}
  prefetched = true;

  const schedule = typeof requestIdleCallback === 'function'
    ? requestIdleCallback
    : (cb: () => void) => setTimeout(cb, 2000);

  schedule(() => {
    for (const load of routes) {
      load().catch(() => { /* chunk may already be cached */ });
    }
  });
}

