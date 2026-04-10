/**
 * useFullscreen.ts — Toggle fullscreen mode on an element
 */

import { useCallback, useState, useEffect, type RefObject } from 'react';

export function useFullscreen(ref: RefObject<HTMLElement | null>) {
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  const toggle = useCallback(() => {
    if (!ref.current) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void ref.current.requestFullscreen();
    }
  }, [ref]);

  return { isFullscreen, toggle };
}
