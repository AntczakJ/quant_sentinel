/**
 * src/components/ui/Card.tsx - Reusable card component
 */

import { ReactNode } from 'react';
import { clsx } from 'clsx';

interface CardProps {
  children: ReactNode;
  title?: string;
  className?: string;
  variant?: 'default' | 'elevated';
}

export function Card({ children, title, className = '', variant = 'default' }: CardProps) {
  const baseStyles = 'rounded-lg p-4 border';
  const variantStyles = {
    default: 'bg-dark-surface border-dark-secondary',
    elevated: 'bg-dark-bg border-accent-blue/30',
  };

  return (
    <div className={clsx(baseStyles, variantStyles[variant], className)}>
      {title && <h3 className="text-sm font-bold text-accent-green mb-3">{title}</h3>}
      {children}
    </div>
  );
}
