/**
 * src/components/ui/Toast.tsx — Lightweight toast notification system
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
  success: { bg: 'bg-accent-green/12', border: 'border-accent-green/30', icon: CheckCircle },
  error:   { bg: 'bg-accent-red/12',   border: 'border-accent-red/30',   icon: AlertCircle },
  warning: { bg: 'bg-accent-orange/12', border: 'border-accent-orange/30', icon: AlertTriangle },
  info:    { bg: 'bg-accent-blue/12',  border: 'border-accent-blue/30',  icon: Info },
};

const TYPE_COLORS: Record<ToastType, string> = {
  success: 'text-accent-green',
  error:   'text-accent-red',
  warning: 'text-accent-orange',
  info:    'text-accent-blue',
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
      className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} backdrop-blur-md shadow-lg max-w-sm animate-slide-in`}
      role="alert"
    >
      <Icon size={16} className={`${color} mt-0.5 shrink-0`} />
      <span className="text-[13px] text-th leading-snug flex-1">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="text-th-muted hover:text-th transition-colors shrink-0"
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
