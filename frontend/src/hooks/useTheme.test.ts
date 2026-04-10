import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTheme } from './useTheme';

describe('useTheme', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('light');
    localStorage.removeItem('qs-theme');
  });

  it('defaults to dark theme', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.isDark).toBe(true);
  });

  it('toggle switches to light', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    // After toggle, the class should be added
    expect(document.documentElement.classList.contains('light')).toBe(true);
  });

  it('persists theme in localStorage', () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(localStorage.getItem('qs-theme')).toBe('light');
  });
});
