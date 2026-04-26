/**
 * SmcOverlay.ts — lightweight-charts v4 Primitive that draws
 * semi-transparent rectangles for SMC zones (FVG, OB, S/D, position tool).
 *
 * Usage:
 *   const overlay = new SmcZonesOverlay();
 *   candleSeries.attachPrimitive(overlay);
 *   overlay.setZones(zones);  // update zones on each data refresh
 *   candleSeries.detachPrimitive(overlay);  // cleanup
 */

import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  IChartApi,
  ISeriesApi,
  SeriesType,
} from 'lightweight-charts';
import type { SmcZone } from './smcDetector';

/* ── Renderer: draws rectangles on the canvas ──────────────────────────── */

interface RectDraw {
  x1: number; y1: number; x2: number; y2: number;
  color: string;
  label: string;
}

class ZonesPaneRenderer implements ISeriesPrimitivePaneRenderer {
  rects: RectDraw[] = [];

  draw(target: {
    useBitmapCoordinateSpace: (cb: (scope: { context: CanvasRenderingContext2D }) => void) => void;
    useMediaCoordinateSpace: (cb: (scope: { context: CanvasRenderingContext2D }) => void) => void;
  }) {
    if (!this.rects.length) {return;}

    // Use media coordinate space (CSS pixels — matches timeToCoordinate / priceToCoordinate)
    target.useMediaCoordinateSpace((scope: { context: CanvasRenderingContext2D }) => {
      const ctx = scope.context;
      for (const r of this.rects) {
        const w = r.x2 - r.x1;
        const h = r.y2 - r.y1;
        if (w <= 0 || h <= 0) {continue;}

        // Filled rectangle — subtle zone fill
        const softColor = r.color.replace(/[\d.]+\)$/, '0.10)');
        ctx.fillStyle = softColor;
        ctx.fillRect(r.x1, r.y1, w, h);
      }

      // Labels rendered via HTML overlay (see CandlestickChart.tsx)
      // Canvas primitives always render under candles in lightweight-charts
    });
  }
}

/* ── Pane View: bridges renderer with the chart ─────────────────────────── */

class ZonesPaneView implements ISeriesPrimitivePaneView {
  _renderer = new ZonesPaneRenderer();

  renderer() {
    return this._renderer;
  }

  // Draw below candles
  zOrder(): 'bottom' | 'normal' | 'top' {
    return 'bottom';
  }
}

/* ── Main Primitive: manages zones and coordinate conversion ─────────────── */

export class SmcZonesOverlay implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | null = null;
  private _series: ISeriesApi<SeriesType, Time> | null = null;
  private _requestUpdate: (() => void) | null = null;
  private _zones: SmcZone[] = [];
  private _labels: Array<{ x: number; y: number; label: string; color: string }> = [];
  private _paneView = new ZonesPaneView();

  attached(param: SeriesAttachedParameter<Time>) {
    this._chart = param.chart;
    this._series = param.series;
    this._requestUpdate = param.requestUpdate;
  }

  detached() {
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  /** Call this whenever zones change (after each data fetch). */
  setZones(zones: SmcZone[]) {
    this._zones = zones;
    this._requestUpdate?.();
  }

  /** Called by lightweight-charts before each render frame. */
  updateAllViews() {
    const rects: RectDraw[] = [];
    if (!this._chart || !this._series || !this._zones.length) {
      this._paneView._renderer.rects = rects;
      return;
    }

    const ts = this._chart.timeScale();
    const series = this._series;
    const chartWidth = ts.width();

    for (const z of this._zones) {
      const x1 = ts.timeToCoordinate(z.startTime as unknown as Time);
      // endTime === 0 means "extend to right edge" (position tool zones)
      const x2raw = z.endTime
        ? ts.timeToCoordinate(z.endTime as unknown as Time)
        : null;
      const x2 = x2raw ?? chartWidth;

      const y1 = series.priceToCoordinate(z.upper);
      const y2 = series.priceToCoordinate(z.lower);

      if (x1 === null || y1 === null || y2 === null) {continue;}
      if (x2 <= x1) {continue;} // skip fully off-screen or zero-width zones

      rects.push({
        x1: Math.max(0, x1),
        y1: Math.min(y1, y2),
        x2,
        y2: Math.max(y1, y2),
        color: z.color,
        label: z.label,
      });
    }

    this._paneView._renderer.rects = rects;
    // Store labels for HTML overlay (rendered above candles)
    this._labels = rects.filter(r => r.label && (r.x2 - r.x1) > 20).map(r => ({
      x: Math.max(0, r.x1) + 4,
      y: Math.min(r.y1, r.y2) + 3,
      label: r.label,
      color: r.color,
    }));
  }

  /** Get label positions for HTML overlay (call after updateAllViews) */
  getLabels(): Array<{ x: number; y: number; label: string; color: string }> {
    return this._labels;
  }

  paneViews() {
    return [this._paneView];
  }
}

