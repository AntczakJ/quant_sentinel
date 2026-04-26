/**
 * components/ui/Accordion.tsx — Animated, accessible disclosure panels.
 *
 * Two flavors:
 *   - <Accordion> wraps multiple <AccordionItem>s and controls single/multi.
 *   - <AccordionItem> can be used standalone for a one-off disclosure.
 *
 * Height animates via Motion `height: 'auto'` which is the smoothest
 * approach without ResizeObserver gymnastics; AnimatePresence handles the
 * enter/exit lifecycle on the panel itself.
 *
 * ARIA: button[aria-expanded] + region[aria-labelledby]. Fully keyboardable.
 */
import { memo, useCallback, useId, useState, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { ChevronDown } from 'lucide-react';
import { DUR_SM, EASE_OUT } from '../../lib/motion';

/* ── Standalone item ──────────────────────────────────────────────────── */

interface ItemProps {
  title: ReactNode;
  children: ReactNode;
  /** If provided, component is controlled by parent. */
  open?: boolean;
  defaultOpen?: boolean;
  onToggle?: (open: boolean) => void;
  /** Icon shown at the left of the title. */
  icon?: ReactNode;
  /** Subtle meta info on the right (e.g. count, status). */
  meta?: ReactNode;
  className?: string;
}

export const AccordionItem = memo(function AccordionItem({
  title, children, open: controlledOpen, defaultOpen = false, onToggle, icon, meta, className,
}: ItemProps) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolled;
  const panelId = useId();
  const headerId = useId();

  const toggle = useCallback(() => {
    const next = !open;
    if (controlledOpen === undefined) {setUncontrolled(next);}
    onToggle?.(next);
  }, [open, controlledOpen, onToggle]);

  return (
    <div className={`border-b border-th-border last:border-b-0 ${className ?? ''}`}>
      <button
        id={headerId}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
        className="w-full flex items-center gap-3 py-4 text-left
                   hover:bg-dark-surface/40 -mx-2 px-2 rounded-lg
                   transition-colors"
      >
        {icon && <span className="shrink-0 text-th-muted">{icon}</span>}
        <span className="flex-1 min-w-0 text-sm font-medium text-th">{title}</span>
        {meta && <span className="shrink-0 text-[11px] text-th-muted">{meta}</span>}
        <ChevronDown
          size={16}
          className={`shrink-0 text-th-dim transition-transform duration-200
                      ${open ? 'rotate-180 text-th-secondary' : ''}`}
          aria-hidden
        />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.section
            id={panelId}
            role="region"
            aria-labelledby={headerId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: DUR_SM, ease: EASE_OUT }}
            className="overflow-hidden"
          >
            <div className="pb-4 pt-1 text-sm text-th-secondary leading-relaxed">
              {children}
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  );
});

/* ── Group ────────────────────────────────────────────────────────────── */

interface GroupProps {
  children: ReactNode;
  /** Only one item open at a time. Default false (independent toggles). */
  exclusive?: boolean;
  className?: string;
}

/**
 * Accordion wrapper. Styling container + optional exclusive mode.
 *
 * For exclusive mode, each child must be a ReactElement with a unique `key`.
 * We manage open state centrally; AccordionItem becomes controlled.
 */
export const Accordion = memo(function Accordion({ children, exclusive = false, className }: GroupProps) {
  const [openKey, setOpenKey] = useState<string | null>(null);

  if (!exclusive) {
    return <div className={`divide-y divide-th-border/60 ${className ?? ''}`}>{children}</div>;
  }

  // Exclusive: clone children to wire open/onToggle.
  return (
    <div className={`divide-y divide-th-border/60 ${className ?? ''}`}>
      {Array.isArray(children)
        ? children.map((child, i) => {
            if (!child || typeof child !== 'object' || !('type' in child)) {return child;}
            const key = String(child.key ?? i);
            return (
              <AccordionItem
                key={key}
                {...(child.props as ItemProps)}
                open={openKey === key}
                onToggle={(next) => setOpenKey(next ? key : null)}
              />
            );
          })
        : children}
    </div>
  );
});
