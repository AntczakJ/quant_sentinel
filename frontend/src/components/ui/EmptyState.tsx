/**
 * src/components/ui/EmptyState.tsx — Illustrated empty state placeholder
 *
 * Shows a subtle icon + message when there's no data to display.
 */

import { memo, type ReactNode } from 'react';
import { Inbox, BarChart3, TrendingUp, FileText, type LucideIcon } from 'lucide-react';

const ICONS: Record<string, LucideIcon> = {
  trades: TrendingUp,
  chart: BarChart3,
  report: FileText,
  default: Inbox,
};

interface Props {
  /** Icon type preset */
  icon?: keyof typeof ICONS;
  /** Custom icon component */
  customIcon?: ReactNode;
  /** Main message */
  message: string;
  /** Optional secondary description */
  description?: string;
  /** Optional action button */
  action?: ReactNode;
}

export const EmptyState = memo(function EmptyState({
  icon = 'default', customIcon, message, description, action,
}: Props) {
  const Icon = ICONS[icon] ?? ICONS.default;

  return (
    <div className="flex flex-col items-center justify-center py-8 px-4 text-center">
      {customIcon ?? (
        <div className="w-12 h-12 rounded-full bg-[var(--color-secondary)] flex items-center justify-center mb-3">
          <Icon size={20} className="text-th-muted" />
        </div>
      )}
      <div className="text-xs font-medium text-th-secondary mb-1">{message}</div>
      {description && (
        <div className="text-[10px] text-th-dim max-w-[240px]">{description}</div>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
});
