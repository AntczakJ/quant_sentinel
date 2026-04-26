/**
 * components/ui/PageHeader.tsx — Unified page header.
 *
 * Every top-level page uses this to present its title + optional subtitle
 * and action slot. Shared spacing and typography scale across pages is what
 * makes the app feel designed rather than assembled.
 *
 * Structure:
 *   <h1>  —  Display serif-ish tracking-tight semibold
 *   <p>   —  Small secondary-colored description
 *   actions slot — refresh buttons, filters, etc.
 *
 * The header animates in on mount (fade + subtle rise). Pair with Reveal on
 * the content below for a cohesive enter sequence.
 */
import { memo, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { DUR_MD, EASE_OUT } from '../../lib/motion';

interface Props {
  title: string;
  /** One-line description — sits under the title in muted color. */
  subtitle?: string;
  /** Right-side slot for buttons, filter chips, etc. */
  actions?: ReactNode;
  /** Optional small element ABOVE the title (breadcrumb, badge). */
  eyebrow?: ReactNode;
  /** Override bottom margin in rem. Default 1.25. */
  mb?: number;
}

export const PageHeader = memo(function PageHeader({
  title, subtitle, actions, eyebrow, mb = 1.25,
}: Props) {
  return (
    <motion.header
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DUR_MD, ease: EASE_OUT }}
      style={{ marginBottom: `${mb}rem` }}
      className="flex items-end justify-between gap-4 flex-wrap"
    >
      <div className="min-w-0 flex-1">
        {eyebrow && (
          <div className="mb-1.5 text-[10px] uppercase tracking-[0.14em] text-th-dim font-medium">
            {eyebrow}
          </div>
        )}
        <h1 className="text-2xl sm:text-[28px] font-display font-semibold tracking-tight text-th leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1.5 text-sm text-th-muted max-w-2xl leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0">
          {actions}
        </div>
      )}
    </motion.header>
  );
});
