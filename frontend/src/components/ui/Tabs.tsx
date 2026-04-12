/**
 * components/ui/Tabs.tsx — Accessible tabs with Motion sliding indicator.
 *
 * Design notes:
 *   - Sliding indicator uses `layoutId` so it flies between tabs rather than
 *     hard-cutting. This is the single biggest "premium" tell in the UI.
 *   - ARIA compliant: role=tablist/tab/tabpanel, aria-selected, aria-controls.
 *   - Keyboard: Arrow keys move focus between tabs, Home/End jumps to ends.
 *   - Can render as underline bar (default) or pill shape (variant="pill").
 *
 * Usage:
 *   const items: TabItem[] = [
 *     { id: 'overview', label: 'Overview', icon: Home },
 *     { id: 'details',  label: 'Details',  count: 3 },
 *   ];
 *   <Tabs items={items} activeId={id} onChange={setId} />
 *   {id === 'overview' && <Overview />}
 */
import { memo, useRef, useId, type KeyboardEvent } from 'react';
import { motion } from 'motion/react';
import { SPRING_SNAP } from '../../lib/motion';

export interface TabItem {
  id: string;
  label: string;
  icon?: React.ComponentType<{ size?: number; className?: string }>;
  /** Small badge number shown next to label. */
  count?: number;
  /** Disable interaction (e.g. not yet available). */
  disabled?: boolean;
  /** Override the accent color for THIS tab when active. Default is accent-blue. */
  accent?: 'blue' | 'orange' | 'green' | 'purple' | 'red';
}

interface Props {
  items: TabItem[];
  activeId: string;
  onChange: (id: string) => void;
  /** Visual style. Default 'underline'. */
  variant?: 'underline' | 'pill';
  /** Unique instance id — required when rendering >1 Tabs on the same page
   *  so layoutId indicators don't collide. Falls back to useId(). */
  instanceId?: string;
  className?: string;
}

const ACCENT_TEXT = {
  blue:   'text-accent-blue',
  orange: 'text-accent-orange',
  green:  'text-accent-green',
  purple: 'text-accent-purple',
  red:    'text-accent-red',
} as const;
const ACCENT_BG = {
  blue:   'bg-accent-blue',
  orange: 'bg-accent-orange',
  green:  'bg-accent-green',
  purple: 'bg-accent-purple',
  red:    'bg-accent-red',
} as const;

export const Tabs = memo(function Tabs({
  items, activeId, onChange, variant = 'underline', instanceId, className,
}: Props) {
  const fallbackId = useId();
  const layoutId = `tabs-indicator-${instanceId ?? fallbackId}`;
  const listRef = useRef<HTMLDivElement>(null);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const enabled = items.filter((it) => !it.disabled);
    if (enabled.length === 0) {return;}
    let nextIdx = index;
    if (e.key === 'ArrowRight') {nextIdx = (index + 1) % items.length;}
    else if (e.key === 'ArrowLeft') {nextIdx = (index - 1 + items.length) % items.length;}
    else if (e.key === 'Home') {nextIdx = 0;}
    else if (e.key === 'End') {nextIdx = items.length - 1;}
    else {return;}
    e.preventDefault();
    while (items[nextIdx]?.disabled) {
      nextIdx = (nextIdx + 1) % items.length;
      if (nextIdx === index) {return;}
    }
    onChange(items[nextIdx].id);
    // Move focus to the newly selected tab.
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    buttons?.[nextIdx]?.focus();
  };

  if (variant === 'pill') {
    return (
      <div
        role="tablist"
        ref={listRef}
        className={`inline-flex items-center gap-1 p-1 rounded-xl
                   bg-dark-surface/60 border border-th-border ${className ?? ''}`}
      >
        {items.map((it, i) => {
          const active = it.id === activeId;
          const accent = it.accent ?? 'blue';
          return (
            <button
              key={it.id}
              role="tab"
              aria-selected={active}
              aria-controls={`panel-${it.id}`}
              id={`tab-${it.id}`}
              disabled={it.disabled}
              tabIndex={active ? 0 : -1}
              onClick={() => !it.disabled && onChange(it.id)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`relative flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-sm font-medium
                          transition-colors disabled:opacity-40 disabled:cursor-not-allowed
                          ${active ? 'text-th' : 'text-th-muted hover:text-th-secondary'}`}
            >
              {active && (
                <motion.span
                  layoutId={layoutId}
                  className="absolute inset-0 rounded-lg bg-dark-tertiary shadow-sm"
                  transition={SPRING_SNAP}
                />
              )}
              <span className="relative flex items-center gap-1.5">
                {it.icon && <it.icon size={13} className={active ? ACCENT_TEXT[accent] : ''} />}
                <span>{it.label}</span>
                {it.count !== undefined && it.count > 0 && (
                  <span className="font-mono text-[10px] text-th-dim tabular-nums">{it.count}</span>
                )}
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  // Underline variant
  return (
    <div
      role="tablist"
      ref={listRef}
      className={`relative flex items-center gap-0 border-b border-th-border ${className ?? ''}`}
    >
      {items.map((it, i) => {
        const active = it.id === activeId;
        const accent = it.accent ?? 'blue';
        return (
          <button
            key={it.id}
            role="tab"
            aria-selected={active}
            aria-controls={`panel-${it.id}`}
            id={`tab-${it.id}`}
            disabled={it.disabled}
            tabIndex={active ? 0 : -1}
            onClick={() => !it.disabled && onChange(it.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={`relative flex items-center gap-2 px-4 py-2.5 text-sm font-medium
                        transition-colors disabled:opacity-40 disabled:cursor-not-allowed
                        ${active ? ACCENT_TEXT[accent] : 'text-th-muted hover:text-th-secondary'}`}
          >
            {it.icon && <it.icon size={14} />}
            <span>{it.label}</span>
            {it.count !== undefined && it.count > 0 && (
              <span className={`font-mono text-[10px] font-semibold tabular-nums
                               ${active ? 'opacity-80' : 'text-th-dim'}`}>
                {it.count}
              </span>
            )}
            {active && (
              <motion.span
                layoutId={layoutId}
                className={`absolute left-0 right-0 -bottom-px h-0.5 rounded-full ${ACCENT_BG[accent]}`}
                transition={SPRING_SNAP}
              />
            )}
          </button>
        );
      })}
    </div>
  );
});
