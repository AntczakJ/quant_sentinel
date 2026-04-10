/**
 * useScrollDirection.ts — Detects scroll direction for auto-hiding header
 *
 * Returns 'up' | 'down' | null. Threshold prevents jitter on small scrolls.
 */

import { useEffect, useRef, useState } from 'react';

type Direction = 'up' | 'down' | null;

export function useScrollDirection(threshold = 10): Direction {
  const [direction, setDirection] = useState<Direction>(null);
  const lastY = useRef(0);
  const ticking = useRef(false);

  useEffect(() => {
    const handleScroll = () => {
      if (ticking.current) return;
      ticking.current = true;

      requestAnimationFrame(() => {
        const y = window.scrollY;
        const diff = y - lastY.current;

        if (Math.abs(diff) > threshold) {
          setDirection(diff > 0 ? 'down' : 'up');
          lastY.current = y;
        }

        // Always show header when at very top
        if (y < 50) setDirection(null);

        ticking.current = false;
      });
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [threshold]);

  return direction;
}
