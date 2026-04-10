/**
 * src/components/ui/ConfirmDialog.tsx — Reusable confirmation modal
 *
 * Usage:
 *   <ConfirmDialog
 *     open={showConfirm}
 *     title="Halt Trading?"
 *     description="This will block all new trades until you manually resume."
 *     confirmLabel="HALT"
 *     variant="danger"
 *     onConfirm={() => { halt(); setShowConfirm(false); }}
 *     onCancel={() => setShowConfirm(false)}
 *   />
 */

import { memo, useEffect, useRef } from 'react';
import { AlertTriangle, Info } from 'lucide-react';

interface Props {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning' | 'info';
  onConfirm: () => void;
  onCancel: () => void;
}

const VARIANT_STYLES = {
  danger: {
    icon: AlertTriangle,
    iconColor: 'text-accent-red',
    iconBg: 'bg-accent-red/10',
    btnBg: 'bg-accent-red/15 text-accent-red border-accent-red/30 hover:bg-accent-red/25',
  },
  warning: {
    icon: AlertTriangle,
    iconColor: 'text-accent-orange',
    iconBg: 'bg-accent-orange/10',
    btnBg: 'bg-accent-orange/15 text-accent-orange border-accent-orange/30 hover:bg-accent-orange/25',
  },
  info: {
    icon: Info,
    iconColor: 'text-accent-blue',
    iconBg: 'bg-accent-blue/10',
    btnBg: 'bg-accent-blue/15 text-accent-blue border-accent-blue/30 hover:bg-accent-blue/25',
  },
};

export const ConfirmDialog = memo(function ConfirmDialog({
  open, title, description, confirmLabel = 'Confirm', cancelLabel = 'Anuluj',
  variant = 'danger', onConfirm, onCancel,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const style = VARIANT_STYLES[variant];
  const Icon = style.icon;

  // Focus cancel button on open (safer default)
  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm" onClick={onCancel} />

      {/* Dialog */}
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby={description ? 'confirm-desc' : undefined}
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[61] w-80 max-w-[90vw] rounded-xl border shadow-2xl p-5"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-start gap-3 mb-4">
          <div className={`w-9 h-9 rounded-full ${style.iconBg} flex items-center justify-center flex-shrink-0`}>
            <Icon size={18} className={style.iconColor} />
          </div>
          <div>
            <h3 id="confirm-title" className="text-sm font-bold" style={{ color: 'var(--color-text-primary)' }}>
              {title}
            </h3>
            {description && (
              <p id="confirm-desc" className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                {description}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 justify-end">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={`px-4 py-1.5 rounded-lg text-xs font-bold border transition-colors ${style.btnBg}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </>
  );
});
