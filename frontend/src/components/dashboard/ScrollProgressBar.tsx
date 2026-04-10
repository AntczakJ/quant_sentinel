/**
 * ScrollProgressBar.tsx – cienki pasek na dole headera pokazujacy postep scrolla.
 */

import { useEffect, useState, memo, useRef } from 'react';

export const ScrollProgressBar = memo(function ScrollProgressBar() {
  const [progress, setProgress] = useState(0);
  const rafRef = useRef(0);

  useEffect(() => {
    const handleScroll = () => {
      if (rafRef.current) {return;}
      rafRef.current = requestAnimationFrame(() => {
        const scrollTop = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        const pct = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
        setProgress(Math.min(100, pct));
        rafRef.current = 0;
      });
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => {
      window.removeEventListener('scroll', handleScroll);
      if (rafRef.current) {cancelAnimationFrame(rafRef.current);}
    };
  }, []);

  return (
    <div className="h-[3px] w-full bg-dark-secondary/40">
      <div
        className="h-full"
        style={{
          width: `${progress}%`,
          background: `linear-gradient(90deg, rgb(var(--c-cyan)) 0%, rgb(var(--c-green)) 60%, rgb(var(--c-purple)) 100%)`,
          boxShadow: progress > 1 ? `0 0 8px rgb(var(--c-cyan) / 0.6)` : 'none',
          willChange: 'width',
        }}
      />
    </div>
  );
});
