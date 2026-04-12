/**
 * src/components/ui/KeyboardHint.tsx — Subtle "Ctrl+K" hint in bottom corner
 *
 * Fades out after the user opens the command palette once.
 * Persisted in localStorage so it doesn't reappear.
 */

import { memo, useState, useEffect } from 'react';
import { Command } from 'lucide-react';

const STORAGE_KEY = 'qs:hint-dismissed';

export const KeyboardHint = memo(function KeyboardHint() {
  const [visible, setVisible] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) !== 'true'; } catch { return true; }
  });

  // Listen for Ctrl+K to auto-dismiss
  useEffect(() => {
    if (!visible) {return;}
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        setVisible(false);
        localStorage.setItem(STORAGE_KEY, 'true');
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [visible]);

  // Auto-dismiss after 30s
  useEffect(() => {
    if (!visible) {return;}
    const t = setTimeout(() => {
      setVisible(false);
      localStorage.setItem(STORAGE_KEY, 'true');
    }, 30000);
    return () => clearTimeout(t);
  }, [visible]);

  if (!visible) {return null;}

  return (
    <div className="fixed bottom-20 md:bottom-4 right-4 z-30 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border shadow-lg text-[10px] font-medium animate-pulse"
      style={{
        background: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
        color: 'var(--color-text-muted)',
      }}
    >
      <Command size={10} />
      <kbd className="px-1 py-0.5 rounded text-[9px] font-mono border" style={{ borderColor: 'var(--color-border)' }}>Ctrl+K</kbd>
      <span>Command Palette</span>
    </div>
  );
});
