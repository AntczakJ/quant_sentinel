/**
 * src/components/ui/Skeleton.tsx — Shimmer loading placeholders
 *
 * Usage:
 *   <Skeleton w="100%" h={20} />           // single bar
 *   <SkeletonCard />                       // full card placeholder
 *   <SkeletonChart />                      // chart-like placeholder
 *   <SkeletonRows count={5} />             // list rows
 */

import { memo } from 'react';

/* ── Base shimmer ──────────────────────────────────────────────────── */

interface SkeletonProps {
  w?: string | number;
  h?: string | number;
  rounded?: string;
  className?: string;
}

export const Skeleton = memo(function Skeleton({
  w = '100%', h = 16, rounded = 'rounded', className = '',
}: SkeletonProps) {
  return (
    <div
      className={`skeleton-shimmer ${rounded} ${className}`}
      style={{
        width: typeof w === 'number' ? `${w}px` : w,
        height: typeof h === 'number' ? `${h}px` : h,
      }}
    />
  );
});

/* ── Presets ────────────────────────────────────────────────────────── */

/** Skeleton mimicking a stat card with label + big value */
export const SkeletonStat = memo(function SkeletonStat() {
  return (
    <div className="stat-item space-y-2">
      <Skeleton w={60} h={8} rounded="rounded-full" />
      <Skeleton w={100} h={20} rounded="rounded" />
      <Skeleton w={80} h={8} rounded="rounded-full" />
    </div>
  );
});

/** Skeleton mimicking a full card section */
export const SkeletonCard = memo(function SkeletonCard({ lines = 4 }: { lines?: number }) {
  return (
    <div className="space-y-3 py-2">
      <Skeleton w={120} h={12} rounded="rounded" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} w={`${85 - i * 10}%`} h={10} rounded="rounded-full" />
      ))}
    </div>
  );
});

/** Skeleton mimicking a chart area */
export const SkeletonChart = memo(function SkeletonChart({ height = 200 }: { height?: number }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Skeleton w={60} h={10} rounded="rounded-full" />
        <Skeleton w={40} h={10} rounded="rounded-full" />
      </div>
      <Skeleton w="100%" h={height} rounded="rounded-lg" />
    </div>
  );
});

/** Multiple skeleton rows (for lists/tables) */
export const SkeletonRows = memo(function SkeletonRows({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton w={28} h={28} rounded="rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton w={`${70 + (i % 3) * 10}%`} h={10} rounded="rounded-full" />
            <Skeleton w={`${50 + (i % 2) * 15}%`} h={8} rounded="rounded-full" />
          </div>
          <Skeleton w={50} h={14} rounded="rounded" />
        </div>
      ))}
    </div>
  );
});

/** Two stat cards side by side */
export const SkeletonStatRow = memo(function SkeletonStatRow() {
  return (
    <div className="grid grid-cols-2 gap-3">
      <SkeletonStat />
      <SkeletonStat />
    </div>
  );
});
