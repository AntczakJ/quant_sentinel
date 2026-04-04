/**
 * src/components/ui/Button.tsx - Reusable button component
 */

import { ReactNode } from 'react';
import { clsx } from 'clsx';

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'danger' | 'success';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  className?: string;
  type?: 'button' | 'submit' | 'reset';
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled = false,
  className = '',
  type = 'button',
}: ButtonProps) {
  const baseStyles =
    'font-medium rounded transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed';

  const variantStyles = {
    primary: 'bg-accent-blue text-white hover:bg-blue-600',
    secondary: 'bg-dark-secondary text-gray-300 hover:bg-dark-surface',
    danger: 'bg-accent-red text-white hover:bg-red-600',
    success: 'bg-accent-green text-white hover:bg-green-600',
  };

  const sizeStyles = {
    sm: 'px-2 py-1 text-xs',
    md: 'px-4 py-2 text-sm',
    lg: 'px-6 py-3 text-base',
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={clsx(baseStyles, variantStyles[variant], sizeStyles[size], className)}
    >
      {children}
    </button>
  );
}

