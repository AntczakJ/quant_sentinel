import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useFullscreen } from './useFullscreen';

describe('useFullscreen', () => {
  it('starts with isFullscreen false', () => {
    const ref = { current: document.createElement('div') };
    const { result } = renderHook(() => useFullscreen(ref));
    expect(result.current.isFullscreen).toBe(false);
  });

  it('toggle calls requestFullscreen when not fullscreen', () => {
    const div = document.createElement('div');
    div.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    const ref = { current: div };

    const { result } = renderHook(() => useFullscreen(ref));
    act(() => result.current.toggle());

    expect(div.requestFullscreen).toHaveBeenCalled();
  });

  it('does nothing if ref is null', () => {
    const ref = { current: null };
    const { result } = renderHook(() => useFullscreen(ref));
    // Should not throw
    act(() => result.current.toggle());
  });
});
