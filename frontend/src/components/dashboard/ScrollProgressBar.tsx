/**
 * ScrollProgressBar.tsx – cienki pasek na dole headera pokazujący postęp scrolla.
 * Osadzony wewnątrz <header> (sticky), więc pozycja jest automatycznie właściwa.
 * Uses RAF-throttled scroll listener for smooth 60fps updates.
 */

import { useEffect, useState, memo, useRef } from 'react';

export const ScrollProgressBar = memo(function ScrollProgressBar() {
  const [progress, setProgress] = useState(0);
  const rafRef = useRef(0);

  useEffect(() => {
    const handleScroll = () => {
      if (rafRef.current) {return;} // already scheduled
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
          background: 'linear-gradient(90deg, #00d4ff 0%, #00ff88 60%, #7c3aed 100%)',
          boxShadow: progress > 1 ? '0 0 8px rgba(0,212,255,0.6)' : 'none',
          willChange: 'width',
        }}
      />
    </div>
  );
});
