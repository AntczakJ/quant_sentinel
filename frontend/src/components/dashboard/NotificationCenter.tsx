/**
 * src/components/dashboard/NotificationCenter.tsx — Bell icon with notification dropdown
 *
 * Aggregates price alerts, signals, and system events.
 * Badge count for unread. Click to mark as read.
 */

import { memo, useState, useCallback } from 'react';
import { Bell, TrendingUp, AlertTriangle, ShieldOff, X, Check } from 'lucide-react';

export interface AppNotification {
  id: string;
  type: 'signal' | 'alert' | 'halt' | 'info';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
}

// Global notification store (simple module-level state for cross-component access)
let _notifications: AppNotification[] = [];
let _listeners: Set<() => void> = new Set();

function notifyListeners() { _listeners.forEach(fn => fn()); }

export function pushNotification(n: Omit<AppNotification, 'id' | 'timestamp' | 'read'>) {
  _notifications = [
    { ...n, id: `notif-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`, timestamp: new Date(), read: false },
    ..._notifications,
  ].slice(0, 50); // Keep max 50
  notifyListeners();
}

function useNotifications() {
  const [, setTick] = useState(0);
  // Subscribe to changes
  useState(() => {
    const listener = () => setTick(t => t + 1);
    _listeners.add(listener);
    return () => { _listeners.delete(listener); };
  });
  return _notifications;
}

const ICON_MAP = {
  signal: TrendingUp,
  alert: AlertTriangle,
  halt: ShieldOff,
  info: Bell,
};

const COLOR_MAP = {
  signal: 'text-accent-green',
  alert: 'text-accent-orange',
  halt: 'text-accent-red',
  info: 'text-accent-blue',
};

export const NotificationCenter = memo(function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const notifications = useNotifications();
  const unreadCount = notifications.filter(n => !n.read).length;

  const markAllRead = useCallback(() => {
    _notifications = _notifications.map(n => ({ ...n, read: true }));
    notifyListeners();
  }, []);

  const clearAll = useCallback(() => {
    _notifications = [];
    notifyListeners();
  }, []);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="relative p-1.5 rounded-md transition-colors hover:bg-dark-secondary"
        style={{ color: unreadCount > 0 ? 'var(--color-accent-orange)' : 'var(--color-text-muted)' }}
        title="Powiadomienia"
      >
        <Bell size={14} />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-accent-red text-white text-[8px] font-bold flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 w-80 max-h-[60vh] bg-[var(--color-surface)] border rounded-xl shadow-2xl overflow-hidden"
            style={{ borderColor: 'var(--color-border)' }}>

            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--color-border)' }}>
              <span className="text-xs font-bold" style={{ color: 'var(--color-text-primary)' }}>
                Powiadomienia
                {unreadCount > 0 && <span className="text-accent-orange ml-1">({unreadCount})</span>}
              </span>
              <div className="flex items-center gap-1">
                {unreadCount > 0 && (
                  <button onClick={markAllRead} className="p-1 text-th-dim hover:text-accent-green transition-colors" title="Oznacz jako przeczytane">
                    <Check size={12} />
                  </button>
                )}
                {notifications.length > 0 && (
                  <button onClick={clearAll} className="p-1 text-th-dim hover:text-accent-red transition-colors" title="Wyczysc">
                    <X size={12} />
                  </button>
                )}
              </div>
            </div>

            {/* List */}
            <div className="overflow-y-auto max-h-[50vh]">
              {notifications.length === 0 ? (
                <div className="text-center text-xs py-8" style={{ color: 'var(--color-text-muted)' }}>
                  Brak powiadomien
                </div>
              ) : (
                notifications.map(n => {
                  const Icon = ICON_MAP[n.type] ?? Bell;
                  const color = COLOR_MAP[n.type] ?? 'text-th-muted';
                  return (
                    <div
                      key={n.id}
                      className={`flex items-start gap-2.5 px-3 py-2.5 border-b transition-colors ${
                        n.read ? 'opacity-50' : 'bg-[var(--color-secondary)]/30'
                      }`}
                      style={{ borderColor: 'var(--color-border)' }}
                      onClick={() => {
                        _notifications = _notifications.map(x => x.id === n.id ? { ...x, read: true } : x);
                        notifyListeners();
                      }}
                    >
                      <Icon size={12} className={`${color} mt-0.5 flex-shrink-0`} />
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] font-medium" style={{ color: 'var(--color-text-primary)' }}>
                          {n.title}
                        </div>
                        <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-muted)' }}>
                          {n.message}
                        </div>
                        <div className="text-[9px] mt-0.5" style={{ color: 'var(--color-text-muted)', opacity: 0.6 }}>
                          {n.timestamp.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                      {!n.read && (
                        <div className="w-1.5 h-1.5 rounded-full bg-accent-blue mt-1 flex-shrink-0" />
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
});
