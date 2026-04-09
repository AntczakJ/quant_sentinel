/**
 * src/components/ui/Toast.tsx — Lightweight toast notification system
 *
 * Zero external dependencies. Manages a queue of notifications
 * that auto-dismiss after a configurable duration.
 *
 * Usage:
 *   import { useToast, ToastContainer } from '../ui/Toast';
 *
 *   function MyComponent() {
 *     const toast = useToast();
 *     toast.error('Trade failed');
 *     toast.success('Trade executed');
 *     toast.info('Market session changed');
 *     return <ToastContainer />;
 *   }
 */

import { useState, useCallback, createContext, useContext, useRef, useEffect, type ReactNode } from 'react';
import { X, CheckCircle, AlertTriangle, Info, AlertCircle } from 'lucide-react';

// ── Types ──

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration: number;
}

interface ToastContextValue {
  success: (message: string, duration?: number) => void;
  error: (message: string, duration?: number) => void;
  warning: (message: string, duration?: number) => void;
  info: (message: string, duration?: number) => void;
}

// ── Context ──

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Fallback: no-op when used outside provider (prevents crashes)
    return {
      success: () => {},
      error: () => {},
      warning: () => {},
      info: () => {},
    };
  }
  return ctx;
}

// ── Styles ──

const TYPE_STYLES: Record<ToastType, { bg: string; border: string; icon: typeof CheckCircle }> = {
  success: { bg: 'bg-green-950/90', border: 'border-green-600/30', icon: CheckCircle },
  error:   { bg: 'bg-red-950/90',   border: 'border-red-600/30',   icon: AlertCircle },
  warning: { bg: 'bg-amber-950/90', border: 'border-amber-600/30', icon: AlertTriangle },
  info:    { bg: 'bg-blue-950/90',  border: 'border-blue-600/30',  icon: Info },
};

const TYPE_COLORS: Record<ToastType, string> = {
  success: 'text-green-400',
  error:   'text-red-400',
  warning: 'text-amber-400',
  info:    'text-blue-400',
};

// ── Single Toast Item ──

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: string) => void }) {
  const style = TYPE_STYLES[toast.type];
  const color = TYPE_COLORS[toast.type];
  const Icon = style.icon;

  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), toast.duration);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onDismiss]);

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} backdrop-blur-sm shadow-lg max-w-sm animate-slide-in`}
      role="alert"
    >
      <Icon size={16} className={`${color} mt-0.5 shrink-0`} />
      <span className="text-[13px] text-gray-200 leading-snug flex-1">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-gray-500 hover:text-gray-300 transition-colors shrink-0"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// ── Toast Container + Provider ──

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counterRef = useRef(0);

  const addToast = useCallback((type: ToastType, message: string, duration = 5000) => {
    const id = `toast-${++counterRef.current}`;
    setToasts(prev => [...prev.slice(-4), { id, type, message, duration }]); // max 5 visible
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const value: ToastContextValue = {
    success: (msg, dur) => addToast('success', msg, dur),
    error:   (msg, dur) => addToast('error', msg, dur ?? 8000),
    warning: (msg, dur) => addToast('warning', msg, dur ?? 6000),
    info:    (msg, dur) => addToast('info', msg, dur),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Toast container — fixed bottom-right */}
      <div className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-auto">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
