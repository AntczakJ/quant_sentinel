/**
 * src/components/charts/AlertManager.tsx — Price alert management panel
 *
 * Lists active and triggered alerts with delete buttons.
 * Opens from chart toolbar.
 */

import { memo } from 'react';
import { Bell, BellOff, Trash2, X } from 'lucide-react';
import type { PriceAlert } from '../../hooks/usePriceAlerts';

interface Props {
  alerts: PriceAlert[];
  onRemove: (id: string) => void;
  onClearTriggered: () => void;
  onClose: () => void;
}

export const AlertManager = memo(function AlertManager({ alerts, onRemove, onClearTriggered, onClose }: Props) {
  const active = alerts.filter(a => !a.triggered);
  const triggered = alerts.filter(a => a.triggered);

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[61] w-80 max-w-[90vw] rounded-xl border shadow-2xl overflow-hidden"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-2">
            <Bell size={14} className="text-accent-orange" />
            <span className="text-sm font-bold" style={{ color: 'var(--color-text-primary)' }}>Price Alerts</span>
            <span className="text-[10px] text-th-muted">({active.length} active)</span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-dark-secondary transition-colors" style={{ color: 'var(--color-text-muted)' }}>
            <X size={14} />
          </button>
        </div>

        {/* Active alerts */}
        <div className="max-h-[40vh] overflow-y-auto">
          {active.length === 0 && triggered.length === 0 ? (
            <div className="text-center text-xs py-8" style={{ color: 'var(--color-text-muted)' }}>
              Brak alertow — uzyj Alt+Click lub PPM na wykresie
            </div>
          ) : (
            <>
              {active.map(a => (
                <div key={a.id} className="flex items-center gap-3 px-4 py-2.5 border-b" style={{ borderColor: 'var(--color-border)' }}>
                  <Bell size={10} className={a.direction === 'above' ? 'text-accent-green' : 'text-accent-red'} />
                  <div className="flex-1">
                    <div className="text-xs font-bold font-mono" style={{ color: 'var(--color-text-primary)' }}>
                      ${a.price.toFixed(2)}
                    </div>
                    <div className="text-[9px]" style={{ color: 'var(--color-text-muted)' }}>
                      {a.direction === 'above' ? '▲ powyzej' : '▼ ponizej'}
                    </div>
                  </div>
                  <button onClick={() => onRemove(a.id)}
                    className="p-1 rounded text-th-dim hover:text-accent-red transition-colors">
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}

              {/* Triggered */}
              {triggered.length > 0 && (
                <>
                  <div className="flex items-center justify-between px-4 py-1.5 bg-[var(--color-secondary)]">
                    <span className="text-[9px] text-th-muted uppercase tracking-wider font-medium">
                      Wywolane ({triggered.length})
                    </span>
                    <button onClick={onClearTriggered} className="text-[9px] text-accent-red hover:underline">
                      Wyczysc
                    </button>
                  </div>
                  {triggered.map(a => (
                    <div key={a.id} className="flex items-center gap-3 px-4 py-2 opacity-50">
                      <BellOff size={10} className="text-th-dim" />
                      <div className="flex-1">
                        <div className="text-xs font-mono line-through" style={{ color: 'var(--color-text-muted)' }}>
                          ${a.price.toFixed(2)}
                        </div>
                      </div>
                      <button onClick={() => onRemove(a.id)}
                        className="p-1 rounded text-th-dim hover:text-accent-red transition-colors">
                        <Trash2 size={10} />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
});
