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

  draw(target: { useBitmapCoordinateSpace: Function; useMediaCoordinateSpace: Function }) {
    if (!this.rects.length) return;

    // Use media coordinate space (CSS pixels — matches timeToCoordinate / priceToCoordinate)
    target.useMediaCoordinateSpace((scope: { context: CanvasRenderingContext2D }) => {
      const ctx = scope.context;
      for (const r of this.rects) {
        const w = r.x2 - r.x1;
        const h = r.y2 - r.y1;
        if (w <= 0 || h <= 0) continue;

        // Filled rectangle
        ctx.fillStyle = r.color;
        ctx.fillRect(r.x1, r.y1, w, h);

        // Crisp top/bottom border lines (solid, higher opacity)
        const borderColor = r.color.replace(/[\d.]+\)$/, '0.7)');
        ctx.strokeStyle = borderColor;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(r.x1, r.y1);
        ctx.lineTo(r.x2, r.y1);
        ctx.moveTo(r.x1, r.y2);
        ctx.lineTo(r.x2, r.y2);
        ctx.stroke();

        // Subtle left edge line
        ctx.strokeStyle = r.color.replace(/[\d.]+\)$/, '0.45)');
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(r.x1, r.y1);
        ctx.lineTo(r.x1, r.y2);
        ctx.stroke();

        // Label with background pill for readability
        if (r.label && w > 30) {
          ctx.font = 'bold 10px monospace';
          const textMetrics = ctx.measureText(r.label);
          const textW = textMetrics.width;
          const pillH = 16;
          const pillW = textW + 12;
          const pillX = r.x1 + 6;

          // Vertically center pill in zone; if zone is too thin, place above it
          let pillY: number;
          if (h >= pillH + 6) {
            // Enough room → center vertically inside the zone
            pillY = r.y1 + Math.round((h - pillH) / 2);
          } else {
            // Zone too thin → place pill just above the top border
            pillY = r.y1 - pillH - 3;
          }

          // Semi-transparent background pill
          ctx.fillStyle = 'rgba(0,0,0,0.60)';
          ctx.beginPath();
          ctx.roundRect(pillX, pillY, pillW, pillH, 4);
          ctx.fill();

          // Thin border matching zone color for context
          ctx.strokeStyle = r.color.replace(/[\d.]+\)$/, '0.8)');
          ctx.lineWidth = 1;
          ctx.setLineDash([]);
          ctx.beginPath();
          ctx.roundRect(pillX, pillY, pillW, pillH, 4);
          ctx.stroke();

          // Label text — vertically centered in pill
          ctx.fillStyle = 'rgba(255,255,255,0.92)';
          ctx.fillText(r.label, pillX + 6, pillY + 11.5);
        }
      }
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

      if (x1 === null || y1 === null || y2 === null) continue;
      if (x2 <= x1) continue; // skip fully off-screen or zero-width zones

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
  }

  paneViews() {
    return [this._paneView];
  }
}

