/**
 * useFaviconBadge.ts — Draw a notification dot on the favicon
 *
 * When active=true, overlays a red dot on the existing favicon.
 * When active=false, restores the original favicon.
 */

import { useEffect, useRef } from 'react';

const DOT_SIZE = 8;
const CANVAS_SIZE = 32;

export function useFaviconBadge(active: boolean) {
  const originalRef = useRef<string | null>(null);

  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!link) return;

    // Store original favicon once
    if (!originalRef.current) {
      originalRef.current = link.href;
    }

    if (!active) {
      // Restore original
      if (originalRef.current) link.href = originalRef.current;
      return;
    }

    // Draw badge on canvas
    const canvas = document.createElement('canvas');
    canvas.width = CANVAS_SIZE;
    canvas.height = CANVAS_SIZE;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => {
      ctx.drawImage(img, 0, 0, CANVAS_SIZE, CANVAS_SIZE);

      // Red dot with white border
      const x = CANVAS_SIZE - DOT_SIZE / 2 - 1;
      const y = DOT_SIZE / 2 + 1;

      ctx.beginPath();
      ctx.arc(x, y, DOT_SIZE / 2 + 1, 0, 2 * Math.PI);
      ctx.fillStyle = '#ffffff';
      ctx.fill();

      ctx.beginPath();
      ctx.arc(x, y, DOT_SIZE / 2, 0, 2 * Math.PI);
      ctx.fillStyle = '#ef4444';
      ctx.fill();

      link.href = canvas.toDataURL('image/png');
    };
    img.src = originalRef.current ?? '/qs-logo.svg';

    return () => {
      if (originalRef.current && link) link.href = originalRef.current;
    };
  }, [active]);
}
