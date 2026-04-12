/**
 * hooks/useRevealOnScroll.ts — IntersectionObserver-based scroll reveal.
 *
 * Returns a ref + boolean. Element reveals once it crosses the viewport
 * threshold, then stays revealed (no re-hide on scroll-up — that would be
 * jarring in a data dashboard).
 *
 * Respects prefers-reduced-motion: returns `isVisible=true` immediately.
 *
 * Usage:
 *   const [ref, visible] = useRevealOnScroll<HTMLDivElement>();
 *   <motion.div ref={ref} animate={visible ? 'show' : 'hidden'} ... />
 */
import { useEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from '../lib/motion';

interface Options {
  /** 0-1, how much of the element must be visible. Default 0.15 (early reveal). */
  threshold?: number;
  /** CSS margin trigger box offset — e.g. "0px 0px -80px 0px" delays reveal. */
  rootMargin?: string;
  /** If false, element re-hides when leaving viewport. Default true. */
  once?: boolean;
}

export function useRevealOnScroll<T extends Element = HTMLDivElement>({
  threshold = 0.15,
  rootMargin = '0px 0px -40px 0px',
  once = true,
}: Options = {}) {
  const ref = useRef<T | null>(null);
  const [visible, setVisible] = useState(() => prefersReducedMotion());

  useEffect(() => {
    if (prefersReducedMotion()) { setVisible(true); return; }
    const el = ref.current;
    if (!el) {return;}
    // IntersectionObserver is widely supported; no fallback needed in modern apps.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          if (once) {observer.disconnect();}
        } else if (!once) {
          setVisible(false);
        }
      },
      { threshold, rootMargin },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold, rootMargin, once]);

  return [ref, visible] as const;
}
