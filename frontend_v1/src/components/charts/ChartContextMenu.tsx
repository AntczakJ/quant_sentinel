/**
 * src/components/charts/ChartContextMenu.tsx — Right-click context menu for chart
 *
 * Actions: Set alert, Copy price, Screenshot, Toggle SMC/Sessions
 */

import { memo } from 'react';
import { Bell, Copy, Camera, Layers, Clock } from 'lucide-react';

interface Props {
  x: number;
  y: number;
  price: number | null;
  onClose: () => void;
  onSetAlert: (price: number) => void;
  onCopyPrice: (price: number) => void;
  onScreenshot: () => void;
  onToggleSmc: () => void;
  onToggleSessions: () => void;
}

export const ChartContextMenu = memo(function ChartContextMenu({
  x, y, price, onClose, onSetAlert, onCopyPrice, onScreenshot, onToggleSmc, onToggleSessions,
}: Props) {
  const items = [
    ...(price ? [
      {
        icon: Bell, label: `Set Alert at $${price.toFixed(2)}`,
        action: () => { onSetAlert(price); onClose(); },
      },
      {
        icon: Copy, label: `Copy Price ($${price.toFixed(2)})`,
        action: () => { onCopyPrice(price); onClose(); },
      },
      { divider: true as const },
    ] : []),
    { icon: Camera, label: 'Screenshot', action: () => { onScreenshot(); onClose(); } },
    { divider: true as const },
    { icon: Layers, label: 'Toggle SMC', action: () => { onToggleSmc(); onClose(); } },
    { icon: Clock, label: 'Toggle Sessions', action: () => { onToggleSessions(); onClose(); } },
  ];

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        className="fixed z-50 py-1 rounded-lg border shadow-xl min-w-[180px]"
        style={{
          left: Math.min(x, window.innerWidth - 200),
          top: Math.min(y, window.innerHeight - 250),
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
        }}
      >
        {items.map((item, i) => {
          if ('divider' in item) {
            return <div key={`d${i}`} className="my-1 border-t" style={{ borderColor: 'var(--color-border)' }} />;
          }
          const Icon = item.icon;
          return (
            <button
              key={item.label}
              onClick={item.action}
              className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[11px] hover:bg-[var(--color-secondary)] transition-colors text-left"
              style={{ color: 'var(--color-text-primary)' }}
            >
              <Icon size={12} className="text-th-muted flex-shrink-0" />
              {item.label}
            </button>
          );
        })}
      </div>
    </>
  );
});
