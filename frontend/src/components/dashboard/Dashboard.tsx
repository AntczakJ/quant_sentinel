/**
 * Dashboard.tsx — Quantum Editorial shell (rewritten 2026-04-25).
 *
 * Minimal chrome, centered 1600px content column with generous gutters,
 * AnimatePresence hero-motion page transitions (fade + subtle y-shift +
 * scale), full-width header with backdrop vibrancy.
 */

import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { Header } from './Header';
import { MobileNav } from '../layout/MobileNav';
import { OfflineBanner } from '../ui/OfflineBanner';
import { LoadingBar } from '../ui/LoadingBar';
import { CommandPalette } from '../ui/CommandPalette';
import { KeyboardHint } from '../ui/KeyboardHint';
import { QuickStatsBar } from './QuickStatsBar';
import { prefersReducedMotion } from '../../lib/motion';

export function Dashboard() {
  const location = useLocation();
  const reduceMotion = prefersReducedMotion();

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [location.pathname]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Skip-to-content for keyboard users */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-[100] focus:px-4 focus:py-2 focus:rounded-xl focus:text-sm focus:font-medium"
        style={{ background: 'rgb(var(--c-accent))', color: 'white' }}
      >
        Skip to content
      </a>

      <LoadingBar />
      <OfflineBanner />
      <Header />

      <main
        id="main-content"
        role="main"
        aria-label="Page content"
        className="flex-1 w-full pb-24 md:pb-12"
      >
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-10 py-6 lg:py-10">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={reduceMotion ? false : { opacity: 0, y: 16, scale: 0.99 }}
              animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
              exit={reduceMotion ? { opacity: 1 } : { opacity: 0, y: -8, scale: 0.99 }}
              transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      <QuickStatsBar />
      <MobileNav />
      <CommandPalette />
      <KeyboardHint />
    </div>
  );
}
