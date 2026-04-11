/**
 * src/components/ui/AnimatedNumber.tsx — Smooth number counter animation
 *
 * Animates from previous value to new value over ~500ms using requestAnimationFrame.
 * Avoids layout shift — same font/size as static text.
 */

import { memo, useEffect, useRef, useState } from 'react';

interface Props {
  value: number;
  /** Number of decimal places (default 2) */
  decimals?: number;
  /** Prefix (e.g. "$", "+$") */
  prefix?: string;
  /** Suffix (e.g. "%", " PLN") */
  suffix?: string;
  /** Animation duration in ms (default 500) */
  duration?: number;
  /** CSS class for the number */
  className?: string;
}

export const AnimatedNumber = memo(function AnimatedNumber({
  value, decimals = 2, prefix = '', suffix = '', duration = 500, className = '',
}: Props) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);
  const rafRef = useRef(0);

  useEffect(() => {
    const from = prevRef.current;
    const to = value;
    prevRef.current = value;

    if (from === to) return;

    const startTime = performance.now();
    const diff = to - from;

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = duration > 0 ? Math.min(elapsed / duration, 1) : 1;
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(from + diff * eased);

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate);
      } else {
        setDisplay(to);
      }
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, duration]);

  return (
    <span className={className}>
      {prefix}{display.toFixed(decimals)}{suffix}
    </span>
  );
});
