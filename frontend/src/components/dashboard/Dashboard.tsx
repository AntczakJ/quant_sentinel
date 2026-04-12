/**
 * src/components/dashboard/Dashboard.tsx — Layout shell with Header + routed content
 * Mobile: bottom nav bar, reduced padding, safe-area margins
 */

import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Header } from './Header';
import { MobileNav } from '../layout/MobileNav';
import { OfflineBanner } from '../ui/OfflineBanner';
import { LoadingBar } from '../ui/LoadingBar';
import { CommandPalette } from '../ui/CommandPalette';
import { KeyboardHint } from '../ui/KeyboardHint';
import { QuickStatsBar } from './QuickStatsBar';

export function Dashboard() {
  const location = useLocation();

  // Scroll to top on route change
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [location.pathname]);

  return (
    <div className="min-h-screen font-sans flex flex-col" style={{ background: 'var(--color-bg)', color: 'var(--color-text-primary)' }}>
      {/* Skip to content link — visible on focus for keyboard users */}
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:px-4 focus:py-2 focus:bg-accent-green focus:text-white focus:rounded-lg focus:text-sm focus:font-medium">
        Skip to content
      </a>
      <LoadingBar />
      <OfflineBanner />
      <Header />
      <main id="main-content" key={location.pathname} role="main" aria-label="Page content" className="flex-1 w-full px-3 py-3 md:px-6 md:py-5 lg:px-8 lg:py-6 pb-20 md:pb-8 page-transition">
        <Outlet />
      </main>
      <QuickStatsBar />
      <MobileNav />
      <CommandPalette />
      <KeyboardHint />
    </div>
  );
}
