/**
 * components/ui/Reveal.tsx — Drop-in reveal-on-scroll wrapper.
 *
 * Wraps children with scroll-triggered fade+rise. Zero config in the common
 * case; extend with `delay` to stagger multiple siblings without a full
 * Motion variant dance.
 *
 * Respects prefers-reduced-motion (immediate visibility).
 *
 * Usage:
 *   <Reveal><SomeCard /></Reveal>
 *   <Reveal delay={0.1}><Hero /></Reveal>
 */
import { memo, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { useRevealOnScroll } from '../../hooks/useRevealOnScroll';
import { DUR_MD, EASE_OUT } from '../../lib/motion';

interface Props {
  children: ReactNode;
  /** Extra delay before the animation starts (seconds). */
  delay?: number;
  /** Y-offset in pixels — larger = more dramatic. Default 14. */
  offset?: number;
  /** Additional className forwarded to the wrapper. */
  className?: string;
  /** Scroll threshold (0-1). Lower = reveals sooner. Default 0.15. */
  threshold?: number;
  /** Render as a different element (defaults to div). */
  as?: 'div' | 'section' | 'article';
}

export const Reveal = memo(function Reveal({
  children, delay = 0, offset = 14, className, threshold, as = 'div',
}: Props) {
  const [ref, visible] = useRevealOnScroll<HTMLDivElement>({ threshold });

  const Tag = motion[as] as typeof motion.div;
  return (
    <Tag
      ref={ref}
      initial={{ opacity: 0, y: offset }}
      animate={visible ? { opacity: 1, y: 0 } : { opacity: 0, y: offset }}
      transition={{ duration: DUR_MD, ease: EASE_OUT, delay }}
      className={className}
    >
      {children}
    </Tag>
  );
});
