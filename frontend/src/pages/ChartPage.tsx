/**
 * pages/ChartPage.tsx — Primary trading view: Chart + Signal sidebar + Portfolio
 * This is the heaviest page (chart + drawings + SMC overlay), loaded first.
 */

import { CandlestickChart } from '../components/charts/CandlestickChart';
import { SignalPanel } from '../components/dashboard/SignalPanel';
import { PortfolioStats } from '../components/dashboard/PortfolioStats';

export default function ChartPage() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <div className="lg:col-span-3 card p-3 flex flex-col" style={{ height: '750px' }}>
          <CandlestickChart />
        </div>

        <div className="flex flex-col gap-4">
          <div className="card">
            <h2 className="section-title mb-3">Signals</h2>
            <SignalPanel />
          </div>
          <div className="card">
            <h2 className="section-title mb-3">Portfolio</h2>
            <PortfolioStats />
          </div>
        </div>
      </div>
    </div>
  );
}

