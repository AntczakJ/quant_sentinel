/**
 * ScrollProgressBar.tsx – cienki pasek na dole headera pokazujący postęp scrolla.
 * Osadzony wewnątrz <header> (sticky), więc pozycja jest automatycznie właściwa.
 */

import { useEffect, useState } from 'react';

export function ScrollProgressBar() {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const handleScroll = () => {
      const scrollTop = window.scrollY;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      const pct = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
      setProgress(Math.min(100, pct));
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <div className="h-[3px] w-full bg-dark-secondary/40">
      <div
        className="h-full transition-[width] duration-75 ease-linear"
        style={{
          width: `${progress}%`,
          background: 'linear-gradient(90deg, #00d4ff 0%, #00ff88 60%, #7c3aed 100%)',
          boxShadow: progress > 1 ? '0 0 8px rgba(0,212,255,0.6)' : 'none',
        }}
      />
    </div>
  );
}
