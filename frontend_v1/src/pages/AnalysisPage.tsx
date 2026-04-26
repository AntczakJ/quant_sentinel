/**
 * pages/AnalysisPage.tsx — QUANT PRO Analysis + Signal History + Pattern Analytics
 * Uses DraggableGrid for customizable panel layout.
 */

import { useMemo } from 'react';
import { AnalysisPanel, SignalHistory, PatternAnalytics } from '../components/dashboard';
import { DraggableGrid, type GridWidget } from '../components/layout/DraggableGrid';
import { PageHeader } from '../components/ui';

export default function AnalysisPage() {
  const widgets: GridWidget[] = useMemo(() => [
    {
      id: 'analysis',
      title: 'Quant Pro Analysis',
      content: <AnalysisPanel />,
      defaultLayout: { x: 0, y: 0, w: 8, h: 7, minW: 5, minH: 4 },
    },
    {
      id: 'signal-history',
      title: 'Signal History',
      content: <SignalHistory />,
      defaultLayout: { x: 8, y: 0, w: 4, h: 7, minW: 3, minH: 3 },
    },
    {
      id: 'pattern-analytics',
      title: 'Pattern Performance',
      content: <PatternAnalytics />,
      defaultLayout: { x: 0, y: 7, w: 12, h: 5, minW: 6, minH: 3 },
    },
  ], []);

  return (
    <div className="max-w-[1600px] mx-auto">
      <PageHeader
        eyebrow="Quant Pro"
        title="Analysis"
        subtitle="Market narrative, signal history, and pattern performance in one board."
      />
      <DraggableGrid pageKey="analysis" widgets={widgets} rowHeight={70} />
    </div>
  );
}
