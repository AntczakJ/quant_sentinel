/**
 * src/hooks/usePrefetch.ts — Prefetch lazy-loaded page chunks on link hover
 *
 * When user hovers a nav link, we trigger the dynamic import ahead of time.
 * By the time they click, the chunk is already in the browser cache.
 * Zero cost if never hovered; ~50–100ms saved per navigation if hovered.
 */

const prefetchedRoutes = new Set<string>();

// Map route paths to their dynamic import functions
const routeImports: Record<string, () => Promise<unknown>> = {
  '/':         () => import('../pages/ChartPage'),
  '/analysis': () => import('../pages/AnalysisPage'),
  '/trades':   () => import('../pages/TradesPage'),
  '/models':   () => import('../pages/ModelsPage'),
  '/agent':    () => import('../pages/AgentPage'),
};

/**
 * Call on mouseenter / focus of a nav link.
 * Safe to call multiple times — deduplicates via Set.
 */
export function prefetchRoute(path: string): void {
  if (prefetchedRoutes.has(path)) {return;}
  const loader = routeImports[path];
  if (!loader) {return;}

  prefetchedRoutes.add(path);

  // Use requestIdleCallback if available, else setTimeout
  const schedule = typeof requestIdleCallback === 'function'
    ? requestIdleCallback
    : (cb: () => void) => setTimeout(cb, 50);

  schedule(() => {
    loader().catch(() => {
      // Failed to prefetch — remove from set so it retries later
      prefetchedRoutes.delete(path);
    });
  });
}

