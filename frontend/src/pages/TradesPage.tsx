/**
 * pages/TradesPage.tsx — Trade History + Portfolio + Risk Metrics
 * Uses DraggableGrid for customizable panel layout.
 */

import { useMemo } from 'react';
import { TradeHistory, PortfolioStats, SignalHistory, RiskMetrics, ExecutionQuality, EquityCurve, ExportButtons } from '../components/dashboard';
import { DraggableGrid, type GridWidget } from '../components/layout/DraggableGrid';

export default function TradesPage() {
  const widgets: GridWidget[] = useMemo(() => [
    {
      id: 'portfolio',
      title: 'Portfolio',
      content: <PortfolioStats />,
      defaultLayout: { x: 0, y: 0, w: 4, h: 5, minW: 3, minH: 3 },
    },
    {
      id: 'trade-history',
      title: 'Trade History',
      content: <TradeHistory />,
      defaultLayout: { x: 4, y: 0, w: 8, h: 5, minW: 4, minH: 3 },
    },
    {
      id: 'equity-curve',
      title: 'Equity Curve',
      content: <EquityCurve />,
      defaultLayout: { x: 0, y: 5, w: 12, h: 4, minW: 6, minH: 3 },
    },
    {
      id: 'risk-metrics',
      title: 'Risk & Performance',
      content: <RiskMetrics />,
      defaultLayout: { x: 0, y: 9, w: 6, h: 5, minW: 4, minH: 3 },
    },
    {
      id: 'execution-quality',
      title: 'Execution Quality',
      content: <ExecutionQuality />,
      defaultLayout: { x: 6, y: 9, w: 6, h: 5, minW: 4, minH: 3 },
    },
    {
      id: 'export',
      title: 'Export',
      content: <ExportButtons />,
      defaultLayout: { x: 0, y: 14, w: 12, h: 2, minW: 4, minH: 1 },
    },
    {
      id: 'signal-history',
      title: 'Signal History',
      content: <SignalHistory />,
      defaultLayout: { x: 0, y: 16, w: 12, h: 5, minW: 4, minH: 3 },
    },
  ], []);

  return (
    <div className="max-w-[1600px] mx-auto">
      <DraggableGrid
        pageKey="trades"
        widgets={widgets}
        rowHeight={70}
      />
    </div>
  );
}
