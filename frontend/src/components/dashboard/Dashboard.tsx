/**
 * src/components/dashboard/Dashboard.tsx - Main dashboard component
 */

import { Header } from './Header';
import { SignalPanel } from './SignalPanel';
import { AnalysisPanel } from './AnalysisPanel';
import { PortfolioStats } from './PortfolioStats';
import { ModelStats } from './ModelStats';
import { CandlestickChart } from '../charts/CandlestickChart';
import { SignalHistory } from './SignalHistory';
import { TradeHistory } from './TradeHistory';

export function Dashboard() {
  return (
    <div className="min-h-screen bg-dark-bg text-white font-mono flex flex-col">
      {/* Header - Full width */}
      <Header />

      {/* Main Content Container */}
      <div className="flex-1 w-full px-4 py-6 lg:px-6 lg:py-8 max-w-full">
        {/* Main Grid Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 auto-rows-max">

          {/* Large Chart - Takes 2/3 width */}
          <div className="lg:col-span-3">
            <div className="card">
              <h2 className="section-title mb-4">📊 CANDLESTICK CHART</h2>
              <div className="chart-container h-[400px] lg:h-[500px]">
                <CandlestickChart />
              </div>
            </div>
          </div>

          {/* Right Sidebar - Takes 1/3 width */}
          <div className="flex flex-col gap-6">
            {/* Signal Panel */}
            <div className="card">
              <h2 className="section-title mb-4">⚡ SIGNALS</h2>
              <div className="space-y-4">
                <SignalPanel />
              </div>
            </div>

            {/* Portfolio Stats */}
            <div className="card">
              <h2 className="section-title mb-4">💰 PORTFOLIO</h2>
              <PortfolioStats />
            </div>
          </div>
        </div>

        {/* Bottom Section - Full Width Stats & Analysis */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">

          {/* QUANT PRO Analysis */}
          <div className="lg:col-span-2">
            <AnalysisPanel />
          </div>

          {/* Signal History */}
          <div className="card">
            <h2 className="section-title mb-4">📜 SIGNAL HISTORY</h2>
            <SignalHistory />
          </div>
        </div>

        {/* Trade History & Model Stats */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
          {/* Trade History */}
          <div className="card">
            <h2 className="section-title mb-4">💹 TRADE HISTORY</h2>
            <TradeHistory />
          </div>

          {/* Model Stats */}
          <div className="card">
            <h2 className="section-title mb-4">🤖 MODEL STATS</h2>
            <ModelStats />
          </div>
        </div>
      </div>
    </div>
  );
}

