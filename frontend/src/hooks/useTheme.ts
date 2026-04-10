/**
 * src/hooks/useTheme.ts — Theme management (dark/light/system mode)
 *
 * Priority: localStorage override > system preference > dark default.
 * Applies 'light' class to <html> element for CSS variable switching.
 * Adds temporary 'transitioning' class for smooth color transitions.
 */

import { useState, useEffect, useCallback } from 'react';

type ThemePref = 'dark' | 'light' | 'system';
type ResolvedTheme = 'dark' | 'light';

const STORAGE_KEY = 'qs-theme';

function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function getInitialPref(): ThemePref {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return 'dark';
}

function resolve(pref: ThemePref): ResolvedTheme {
  return pref === 'system' ? getSystemTheme() : pref;
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(getInitialPref);
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolve(pref));

  // Listen for system theme changes
  useEffect(() => {
    if (pref !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const handler = () => setResolved(getSystemTheme());
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [pref]);

  // Apply theme class
  useEffect(() => {
    const theme = resolve(pref);
    setResolved(theme);
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light');
    } else {
      root.classList.remove('light');
    }
    localStorage.setItem(STORAGE_KEY, pref);
  }, [pref]);

  const toggle = useCallback(() => {
    const root = document.documentElement;
    root.classList.add('transitioning');
    // Cycle: dark → light → system → dark
    setPref(prev => {
      if (prev === 'dark') return 'light';
      if (prev === 'light') return 'system';
      return 'dark';
    });
    setTimeout(() => root.classList.remove('transitioning'), 300);
  }, []);

  return { theme: resolved, pref, toggle, isDark: resolved === 'dark' };
}
