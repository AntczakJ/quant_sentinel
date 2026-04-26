/**
 * useKeyboardShortcuts.ts — Global keyboard shortcuts for the trading terminal
 *
 * Shortcuts:
 *   T       = toggle dark/light theme
 *   1-4     = switch interval (5m/15m/1h/4h)
 *   D       = toggle drawing mode (cursor ↔ line)
 *   Escape  = back to cursor mode
 *   Space   = toggle SMC overlay
 *   S       = toggle Sessions overlay
 *   ?       = show/hide help modal
 *
 * Shortcuts are disabled when focus is in an input/textarea/select.
 */

import { useEffect, useCallback } from 'react';

export interface ShortcutHandlers {
  onToggleTheme: () => void;
  onSelectInterval: (interval: string) => void;
  onToggleDrawing: () => void;
  onEscDrawing: () => void;
  onToggleSmc: () => void;
  onToggleSessions: () => void;
  onToggleHelp: () => void;
}

const INTERVAL_MAP: Record<string, string> = {
  '1': '5m',
  '2': '15m',
  '3': '1h',
  '4': '4h',
};

export function useKeyboardShortcuts(handlers: ShortcutHandlers) {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Skip when typing in form elements
    const target = e.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable) {
      return;
    }

    // Skip when modifier keys are held (except for ?)
    if (e.ctrlKey || e.metaKey || e.altKey) {return;}

    const key = e.key;

    switch (key) {
      case 't':
      case 'T':
        e.preventDefault();
        handlers.onToggleTheme();
        break;
      case '1':
      case '2':
      case '3':
      case '4':
        e.preventDefault();
        handlers.onSelectInterval(INTERVAL_MAP[key]);
        break;
      case 'd':
      case 'D':
        e.preventDefault();
        handlers.onToggleDrawing();
        break;
      case 'Escape':
        handlers.onEscDrawing();
        break;
      case ' ':
        e.preventDefault();
        handlers.onToggleSmc();
        break;
      case 's':
      case 'S':
        e.preventDefault();
        handlers.onToggleSessions();
        break;
      case '?':
        e.preventDefault();
        handlers.onToggleHelp();
        break;
    }
  }, [handlers]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}

export const SHORTCUT_LIST = [
  { key: 'T', description: 'Toggle dark/light theme' },
  { key: '1-4', description: 'Switch interval (5m/15m/1h/4h)' },
  { key: 'D', description: 'Toggle drawing mode' },
  { key: 'Esc', description: 'Back to cursor mode' },
  { key: 'Space', description: 'Toggle SMC overlay' },
  { key: 'S', description: 'Toggle Sessions overlay' },
  { key: '?', description: 'Show/hide shortcuts help' },
  { key: 'Alt+Click', description: 'Set price alert' },
] as const;
