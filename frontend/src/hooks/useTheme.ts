/**
 * src/hooks/useTheme.ts — Theme management (dark/light mode)
 *
 * Persists to localStorage. Defaults to dark.
 * Applies 'light' class to <html> element for CSS variable switching.
 * Adds temporary 'transitioning' class for smooth color transitions.
 */

import { useState, useEffect, useCallback } from 'react';

type Theme = 'dark' | 'light';

const STORAGE_KEY = 'qs-theme';

function getInitialTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'dark';
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light');
    } else {
      root.classList.remove('light');
    }
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    const root = document.documentElement;
    // Enable transition for smooth theme switch
    root.classList.add('transitioning');
    setThemeState(prev => prev === 'dark' ? 'light' : 'dark');
    // Remove transitioning class after animation completes
    setTimeout(() => root.classList.remove('transitioning'), 300);
  }, []);

  return { theme, toggle, isDark: theme === 'dark' };
}
