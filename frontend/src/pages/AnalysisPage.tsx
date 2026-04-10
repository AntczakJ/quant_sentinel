/**
 * pages/AnalysisPage.tsx — QUANT PRO Analysis + MTF Confluence + Signal History + Pattern Analytics
 */

import { AnalysisPanel, SignalHistory, PatternAnalytics } from '../components/dashboard';

export default function AnalysisPage() {
  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <AnalysisPanel />
        </div>
        <div className="card">
          <h2 className="section-title mb-3">Signal History</h2>
          <SignalHistory />
        </div>
      </div>

      {/* Pattern Performance Analytics */}
      <div className="card">
        <h2 className="section-title mb-3">
          Pattern Performance
          <span className="text-xs text-th-muted font-normal ml-2">— win rate by pattern, session x direction heatmap</span>
        </h2>
        <PatternAnalytics />
      </div>
    </div>
  );
}
