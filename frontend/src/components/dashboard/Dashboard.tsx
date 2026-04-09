/**
 * src/components/dashboard/Dashboard.tsx — Layout shell with Header + routed content
 */

import { Outlet } from 'react-router-dom';
import { Header } from './Header';

export function Dashboard() {
  return (
    <div className="min-h-screen font-sans flex flex-col" style={{ background: 'var(--color-bg)', color: 'var(--color-text-primary)' }}>
      <Header />
      <main className="flex-1 w-full px-4 py-4 lg:px-6 lg:py-6">
        <Outlet />
      </main>
    </div>
  );
}
