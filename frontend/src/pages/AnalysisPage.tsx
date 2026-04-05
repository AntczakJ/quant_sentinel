/**
 * pages/AnalysisPage.tsx — QUANT PRO Analysis + MTF Confluence + Signal History
 */

import { AnalysisPanel, SignalHistory } from '../components/dashboard';

export default function AnalysisPage() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <AnalysisPanel />
        </div>
        <div className="card">
          <h2 className="section-title mb-3">Signal History</h2>
          <SignalHistory />
        </div>
      </div>
    </div>
  );
}


