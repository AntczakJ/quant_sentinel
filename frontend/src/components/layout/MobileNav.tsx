/**
 * src/components/layout/MobileNav.tsx — Bottom navigation bar for mobile
 *
 * Shown only on screens < 768px. Replaces top nav links.
 * Fixed to bottom with safe-area padding for iOS notch.
 */

import { memo } from 'react';
import { NavLink } from 'react-router-dom';
import { BarChart3, LineChart, Repeat, Brain, Newspaper, Bot, Settings } from 'lucide-react';

const NAV_ITEMS = [
  { to: '/',         label: 'Chart',    icon: BarChart3 },
  { to: '/analysis', label: 'Analysis', icon: LineChart },
  { to: '/trades',   label: 'Trades',   icon: Repeat },
  { to: '/models',   label: 'Models',   icon: Brain },
  { to: '/news',     label: 'News',     icon: Newspaper },
  { to: '/agent',    label: 'Agent',    icon: Bot },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const;

export const MobileNav = memo(function MobileNav() {
  return (
    <nav aria-label="Mobile navigation" className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t backdrop-blur-md pb-[env(safe-area-inset-bottom)]"
      style={{ background: 'color-mix(in srgb, var(--color-surface) 96%, transparent)', borderColor: 'var(--color-border)' }}>
      <div className="flex items-center justify-around px-1 py-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex flex-col items-center gap-0.5 px-2 py-1.5 rounded-lg transition-all text-[9px] font-medium min-w-[48px] ${
                isActive
                  ? 'text-[var(--color-accent-green)]'
                  : 'text-[var(--color-text-muted)] opacity-60'
              }`
            }
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  );
});
