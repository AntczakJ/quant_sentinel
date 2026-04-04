/**
 * src/components/ui/Badge.tsx - Reusable badge component
 */

import { ReactNode } from 'react';
import { clsx } from 'clsx';

interface BadgeProps {
  children: ReactNode;
  variant?: 'success' | 'danger' | 'warning' | 'info';
  className?: string;
}

export function Badge({ children, variant = 'info', className = '' }: BadgeProps) {
  const variantStyles = {
    success: 'bg-accent-green/20 text-accent-green border border-accent-green/50',
    danger: 'bg-accent-red/20 text-accent-red border border-accent-red/50',
    warning: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/50',
    info: 'bg-accent-blue/20 text-accent-blue border border-accent-blue/50',
  };

  return (
    <span className={clsx('px-2 py-1 rounded text-xs font-medium', variantStyles[variant], className)}>
      {children}
    </span>
  );
}

