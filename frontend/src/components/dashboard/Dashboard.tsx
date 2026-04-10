/**
 * src/components/dashboard/Dashboard.tsx — Layout shell with Header + routed content
 * Mobile: bottom nav bar, reduced padding, safe-area margins
 */

import { Outlet } from 'react-router-dom';
import { Header } from './Header';
import { MobileNav } from '../layout/MobileNav';

export function Dashboard() {
  return (
    <div className="min-h-screen font-sans flex flex-col" style={{ background: 'var(--color-bg)', color: 'var(--color-text-primary)' }}>
      <Header />
      <main className="flex-1 w-full px-2 py-2 md:px-4 md:py-4 lg:px-6 lg:py-6 pb-20 md:pb-4">
        <Outlet />
      </main>
      <MobileNav />
    </div>
  );
}
