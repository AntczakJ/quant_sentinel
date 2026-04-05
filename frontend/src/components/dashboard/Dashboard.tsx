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
import { AgentChat } from './AgentChat';

export function Dashboard() {
  return (
    <div className="min-h-screen bg-dark-bg text-gray-200 font-sans flex flex-col">
      <Header />

      <div className="flex-1 w-full px-4 py-4 lg:px-6 lg:py-6 max-w-[1600px] mx-auto space-y-4">
        {/* Top: Chart + Sidebar */}
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

        {/* Middle: Analysis + Signal History */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2">
            <AnalysisPanel />
          </div>
          <div className="card">
            <h2 className="section-title mb-3">Signal History</h2>
            <SignalHistory />
          </div>
        </div>

        {/* Bottom: Trades + Models */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="card">
            <h2 className="section-title mb-3">Trade History <span className="text-xs text-gray-500 font-normal">— ostatnie 10</span></h2>
            <TradeHistory />
          </div>
          <div className="card">
            <h2 className="section-title mb-3">ML Models</h2>
            <ModelStats />
          </div>
        </div>

        {/* Agent Chat */}
        <div className="card">
          <h2 className="section-title mb-3">
            AI Agent
            {' '}
            <span className="text-xs text-green-500 font-normal ml-1">● memory</span>
          </h2>
          <AgentChat />
        </div>
      </div>
    </div>
  );
}
