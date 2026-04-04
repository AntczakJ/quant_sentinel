/**
 * src/components/ui/Alert.tsx - Alert notification component
 */

import { ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, CheckCircle, AlertTriangle, Info } from 'lucide-react';

interface AlertProps {
  children: ReactNode;
  variant?: 'success' | 'error' | 'warning' | 'info';
  className?: string;
  dismissible?: boolean;
  onDismiss?: () => void;
}

export function Alert({
  children,
  variant = 'info',
  className = '',
  dismissible = false,
  onDismiss,
}: AlertProps) {
  const variantStyles = {
    success: 'bg-accent-green/10 border border-accent-green/50 text-accent-green',
    error: 'bg-accent-red/10 border border-accent-red/50 text-accent-red',
    warning: 'bg-yellow-500/10 border border-yellow-500/50 text-yellow-400',
    info: 'bg-accent-blue/10 border border-accent-blue/50 text-accent-blue',
  };

  const icons = {
    success: CheckCircle,
    error: AlertCircle,
    warning: AlertTriangle,
    info: Info,
  };

  const Icon = icons[variant];

  return (
    <div
      className={clsx(
        'rounded-lg p-4 flex items-start gap-3',
        variantStyles[variant],
        className
      )}
    >
      <Icon className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <div className="flex-1">{children}</div>
      {dismissible && (
        <button
          onClick={onDismiss}
          className="text-current opacity-50 hover:opacity-100 transition-opacity flex-shrink-0"
        >
          ✕
        </button>
      )}
    </div>
  );
}

