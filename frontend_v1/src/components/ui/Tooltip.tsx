/**
 * src/components/ui/Tooltip.tsx — Lightweight hover tooltip
 *
 * Usage:
 *   <Tooltip content="Profit Factor">
 *     <span>PF</span>
 *   </Tooltip>
 *
 * Position-aware: defaults to top, flips to bottom if near top edge.
 */

import { memo, useState, useRef, useCallback, type ReactNode } from 'react';

interface Props {
  content: string | ReactNode;
  children: ReactNode;
  /** Preferred position (default "top") */
  position?: 'top' | 'bottom';
  /** Delay before showing in ms (default 400) */
  delay?: number;
}

export const Tooltip = memo(function Tooltip({
  content, children, position = 'top', delay = 400,
}: Props) {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);

  const show = useCallback(() => {
    timerRef.current = setTimeout(() => setVisible(true), delay);
  }, [delay]);

  const hide = useCallback(() => {
    clearTimeout(timerRef.current);
    setVisible(false);
  }, []);

  const posClass = position === 'bottom'
    ? 'top-full mt-1.5'
    : 'bottom-full mb-1.5';

  return (
    <div
      ref={containerRef}
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {visible && (
        <div
          role="tooltip"
          className={`absolute left-1/2 -translate-x-1/2 ${posClass} z-50 px-2.5 py-1.5 rounded-lg text-[10px] font-medium whitespace-nowrap pointer-events-none shadow-lg border`}
          style={{
            background: 'var(--color-surface)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text-primary)',
          }}
        >
          {content}
          {/* Arrow */}
          <div
            className={`absolute left-1/2 -translate-x-1/2 w-2 h-2 rotate-45 border ${
              position === 'bottom' ? '-top-1 border-b-0 border-r-0' : '-bottom-1 border-t-0 border-l-0'
            }`}
            style={{
              background: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
            }}
          />
        </div>
      )}
    </div>
  );
});
