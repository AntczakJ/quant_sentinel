/**
 * src/components/dashboard/Dashboard.tsx — Layout shell with Header + routed content
 */

import { Outlet } from 'react-router-dom';
import { Header } from './Header';

export function Dashboard() {
  return (
    <div className="min-h-screen bg-dark-bg text-gray-200 font-sans flex flex-col">
      <Header />
      <main className="flex-1 w-full px-4 py-4 lg:px-6 lg:py-6 max-w-[1600px] mx-auto">
        <Outlet />
      </main>
    </div>
  );
}
