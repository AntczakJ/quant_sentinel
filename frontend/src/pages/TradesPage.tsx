/**
 * pages/TradesPage.tsx — Trade History + Portfolio + Risk Metrics
 */

import { TradeHistory, PortfolioStats, SignalHistory, RiskMetrics } from '../components/dashboard';

export default function TradesPage() {
  return (
    <div className="space-y-4">
      {/* Portfolio summary row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card">
          <h2 className="section-title mb-3">Portfolio</h2>
          <PortfolioStats />
        </div>
        <div className="lg:col-span-2 card">
          <h2 className="section-title mb-3">
            Trade History
            <span className="text-xs text-gray-500 font-normal ml-2">— wszystkie</span>
          </h2>
          <TradeHistory />
        </div>
      </div>

      {/* Risk Metrics */}
      <div className="card">
        <h2 className="section-title mb-3">
          Risk & Performance Metrics
          <span className="text-xs text-gray-500 font-normal ml-2">— drawdown, profit factor, expectancy</span>
        </h2>
        <RiskMetrics />
      </div>

      {/* Signal History full */}
      <div className="card">
        <h2 className="section-title mb-3">Signal History</h2>
        <SignalHistory />
      </div>
    </div>
  );
}


