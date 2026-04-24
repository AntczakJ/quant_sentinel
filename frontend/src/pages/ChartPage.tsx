/**
 * ChartPage — rewritten 2026-04-25 (Quantum Editorial).
 *
 * Hero title block with live sentinel status pill → full-width chart in
 * elevated hero-card → dense metrics strip → paired Signal + Portfolio
 * hero-cards → scanner insight. Generous spacing, gradient borders on
 * hero surfaces, reveal-stagger on mount.
 */

import { motion } from 'motion/react';
import { CandlestickChart } from '../components/charts/CandlestickChart';
import { SignalPanel } from '../components/dashboard/SignalPanel';
import { PortfolioStats } from '../components/dashboard/PortfolioStats';
import { OverviewStrip } from '../components/dashboard/OverviewStrip';
import { ScannerInsight } from '../components/dashboard/ScannerInsight';
import { MacroContext } from '../components/dashboard/MacroContext';
import { WeekendBanner } from '../components/dashboard/WeekendBanner';
import { OrbStatus } from '../components/dashboard/OrbStatus';

function SectionHeader({
  eyebrow,
  title,
  right,
}: {
  eyebrow?: string;
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4 mb-4">
      <div>
        {eyebrow && <div className="t-eyebrow mb-1">{eyebrow}</div>}
        <h2 className="t-h2">{title}</h2>
      </div>
      {right && <div>{right}</div>}
    </div>
  );
}

export default function ChartPage() {
  return (
    <div className="space-y-8 lg:space-y-12">
      {/* Weekend banner — auto-hides when market open */}
      <WeekendBanner />

      {/* Hero title block */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="flex flex-wrap items-end justify-between gap-4"
      >
        <div>
          <div className="t-eyebrow mb-2">Live market</div>
          <h1 className="t-display">
            <span className="glow-text">XAU/USD</span>
          </h1>
          <p className="t-body mt-2" style={{ color: 'var(--color-text-secondary)' }}>
            Autonomous gold scanner · multi-timeframe cascade · regime-aware ensemble
          </p>
        </div>

        {/* Macro + ORB pills stack */}
        <div className="flex flex-col gap-2 min-w-0">
          <MacroContext />
          <OrbStatus />
        </div>
      </motion.div>

      {/* Hero chart card — gradient border, oversized radius */}
      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1], delay: 0.1 }}
        className="hero-card p-0 overflow-hidden"
        style={{ minHeight: 560 }}
      >
        <div
          className="relative flex flex-col"
          style={{
            height: 'calc(100vh - 280px)',
            minHeight: 560,
            background: 'var(--chart-bg)',
            borderRadius: 'var(--radius-4xl)',
          }}
          data-no-theme-transition
        >
          <CandlestickChart />
        </div>
      </motion.div>

      {/* Metrics strip — light container, reveal-stagger children */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
      >
        <OverviewStrip />
      </motion.div>

      {/* Paired hero cards — Signals × Portfolio */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: 0.3 }}
        className="grid grid-cols-1 lg:grid-cols-2 gap-6 lg:gap-8"
      >
        <section className="hero-card">
          <SectionHeader eyebrow="Latest" title="Signals" />
          <SignalPanel />
        </section>

        <section className="hero-card">
          <SectionHeader eyebrow="Account" title="Portfolio" />
          <PortfolioStats />
        </section>
      </motion.div>

      {/* Scanner insight — why the scanner is (not) trading */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: 0.4 }}
      >
        <SectionHeader
          eyebrow="Scanner"
          title="Why the system is (not) trading"
        />
        <ScannerInsight />
      </motion.div>
    </div>
  );
}
