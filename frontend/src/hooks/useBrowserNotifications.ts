/**
 * useBrowserNotifications.ts — Browser Notification API integration
 *
 * Requests permission on first use, sends notifications for:
 * - Price alerts triggered
 * - New trading signals
 * - Risk halts
 *
 * Falls back silently if notifications are denied or unavailable.
 */

import { useCallback, useState } from 'react';

type Permission = 'default' | 'granted' | 'denied';

export function useBrowserNotifications() {
  const [permission, setPermission] = useState<Permission>(
    () => typeof Notification !== 'undefined' ? Notification.permission : 'denied'
  );
  const supported = typeof Notification !== 'undefined';

  const requestPermission = useCallback(async () => {
    if (!supported) return 'denied' as Permission;
    const result = await Notification.requestPermission();
    setPermission(result);
    return result;
  }, [supported]);

  const notify = useCallback((title: string, options?: NotificationOptions) => {
    if (!supported || permission !== 'granted') return null;
    try {
      const n = new Notification(title, {
        icon: '/qs-logo.svg',
        badge: '/qs-logo.svg',
        tag: options?.tag ?? 'qs-notification',
        ...options,
      });
      // Auto-close after 8 seconds
      setTimeout(() => n.close(), 8000);
      return n;
    } catch {
      return null;
    }
  }, [supported, permission]);

  /** Convenience: price alert notification */
  const notifyPriceAlert = useCallback((price: number, direction: 'above' | 'below') => {
    return notify(`Price Alert: $${price.toFixed(2)}`, {
      body: `XAU/USD crossed ${direction === 'above' ? 'above' : 'below'} $${price.toFixed(2)}`,
      tag: `price-alert-${price}`,
    });
  }, [notify]);

  /** Convenience: new signal notification */
  const notifySignal = useCallback((direction: string, entry?: number) => {
    return notify(`New Signal: ${direction}`, {
      body: entry ? `Entry: $${entry.toFixed(2)}` : 'Check dashboard for details',
      tag: 'new-signal',
    });
  }, [notify]);

  /** Convenience: risk halt notification */
  const notifyHalt = useCallback((reason?: string) => {
    return notify('Trading HALTED', {
      body: reason ?? 'Manual halt activated',
      tag: 'risk-halt',
      requireInteraction: true,
    });
  }, [notify]);

  return {
    supported,
    permission,
    requestPermission,
    notify,
    notifyPriceAlert,
    notifySignal,
    notifyHalt,
  };
}
