/**
 * pages/ChartPage.tsx — Primary trading view: Chart (full-width) + Signal/Portfolio panels below
 * This is the heaviest page (chart + drawings + SMC overlay), loaded first.
 */

import { CandlestickChart } from '../components/charts/CandlestickChart';
import { SignalPanel } from '../components/dashboard/SignalPanel';
import { PortfolioStats } from '../components/dashboard/PortfolioStats';
import { OverviewStrip } from '../components/dashboard/OverviewStrip';

export default function ChartPage() {
  return (
    <div className="space-y-0">
      {/* Chart: full-width, break out of container padding */}
      <div className="-mx-4 lg:-mx-6 -mt-4 lg:-mt-6">
        <div
          className="flex flex-col"
          style={{ background: 'var(--chart-bg)', height: 'calc(100vh - 110px)', minHeight: '500px' }}
        >
          <CandlestickChart />
        </div>
      </div>

      {/* Overview metrics strip */}
      <div className="-mx-4 lg:-mx-6">
        <OverviewStrip />
      </div>

      {/* Signal & Portfolio panels below chart */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
        <div className="card-elevated">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-4 rounded-full bg-accent-blue" />
            <h2 className="section-title mb-0">Signals</h2>
          </div>
          <SignalPanel />
        </div>
        <div className="card-elevated">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-1 h-4 rounded-full bg-accent-green" />
            <h2 className="section-title mb-0">Portfolio</h2>
          </div>
          <PortfolioStats />
        </div>
      </div>
    </div>
  );
}

