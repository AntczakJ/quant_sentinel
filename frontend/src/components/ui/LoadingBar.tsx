/**
 * src/components/ui/LoadingBar.tsx — Thin progress bar at page top
 *
 * Shows animated progress during data loading, like GitHub/YouTube.
 * Uses React Query's isFetching state to determine visibility.
 */

import { memo } from 'react';
import { useIsFetching } from '@tanstack/react-query';

export const LoadingBar = memo(function LoadingBar() {
  const isFetching = useIsFetching();

  if (!isFetching) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[100] h-[2px] pointer-events-none">
      <div className="h-full bg-accent-green loading-bar-animate" />
    </div>
  );
});
