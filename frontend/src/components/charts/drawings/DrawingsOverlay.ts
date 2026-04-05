/**
 * drawings/DrawingsOverlay.ts — lightweight-charts v4 ISeriesPrimitive
 * that renders all user-drawn objects on the canvas.
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
import type { Drawing, DrawingPoint } from './types';
import {
  renderTrendLine, renderRay, renderExtendedLine,
  renderHLine, renderVLine, renderChannel, renderFib,
  renderRect, renderPath, renderText, renderMeasure,
  renderPosition, renderHandles,
} from './renderFns';

/* ── Pixel-space representation ─────────────────────────────────────────── */

interface PixelDrawing {
  drawing: Drawing;
  pts: { x: number; y: number }[];
}

/* ── Renderer ───────────────────────────────────────────────────────────── */

class DrawingsPaneRenderer implements ISeriesPrimitivePaneRenderer {
  items: PixelDrawing[] = [];
  selectedId: string | null = null;
  chartW = 0;
  chartH = 0;
  /** Preview drawing currently being placed (rubber-band). */
  preview: PixelDrawing | null = null;

  draw(target: { useBitmapCoordinateSpace: Function; useMediaCoordinateSpace: Function }) {
    target.useMediaCoordinateSpace((scope: { context: CanvasRenderingContext2D; mediaSize: { width: number; height: number } }) => {
      const ctx = scope.context;
      const w = this.chartW || scope.mediaSize.width;
      const h = this.chartH || scope.mediaSize.height;

      const all = [...this.items];
      if (this.preview) all.push(this.preview);

      for (const item of all) {
        const d = item.drawing;
        if (!d.visible) continue;
        const pts = item.pts;

        switch (d.tool) {
          case 'trendline':    renderTrendLine(ctx, pts, d.style); break;
          case 'ray':          renderRay(ctx, pts, d.style, w, h); break;
          case 'extendedline': renderExtendedLine(ctx, pts, d.style, w, h); break;
          case 'hline':        renderHLine(ctx, pts, d.style, w); break;
          case 'vline':        renderVLine(ctx, pts, d.style, h); break;
          case 'channel':      renderChannel(ctx, pts, d.style, w, h); break;
          case 'fib':          renderFib(ctx, pts, d.style, w); break;
          case 'rect':         renderRect(ctx, pts, d.style); break;
          case 'path':         renderPath(ctx, pts, d.style); break;
          case 'text':         renderText(ctx, pts, d.style); break;
          case 'measure':
            renderMeasure(ctx, pts, d.style,
              d.points[0]?.price, d.points[1]?.price);
            break;
          case 'longposition':
            renderPosition(ctx, pts, d.style, 'long', w,
              d.points[0]?.price, d.points[1]?.price);
            break;
          case 'shortposition':
            renderPosition(ctx, pts, d.style, 'short', w,
              d.points[0]?.price, d.points[1]?.price);
            break;
        }

        // Selection handles
        if (d.id === this.selectedId) {
          renderHandles(ctx, pts, d.style.color);
        }
      }
    });
  }
}

/* ── Pane View ──────────────────────────────────────────────────────────── */

class DrawingsPaneView implements ISeriesPrimitivePaneView {
  _renderer = new DrawingsPaneRenderer();
  renderer() { return this._renderer; }
  zOrder(): 'bottom' | 'normal' | 'top' { return 'top'; }
}

/* ── Main Primitive ─────────────────────────────────────────────────────── */

export class DrawingsOverlay implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | null = null;
  private _series: ISeriesApi<SeriesType, Time> | null = null;
  private _requestUpdate: (() => void) | null = null;
  private _drawings: Drawing[] = [];
  private _selectedId: string | null = null;
  private _preview: { drawing: Drawing; previewPt?: DrawingPoint } | null = null;
  private _paneView = new DrawingsPaneView();

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

  setDrawings(drawings: Drawing[]) {
    this._drawings = drawings;
    this._requestUpdate?.();
  }

  setSelectedId(id: string | null) {
    this._selectedId = id;
    this._requestUpdate?.();
  }

  setPreview(drawing: Drawing | null) {
    if (drawing) {
      this._preview = { drawing };
    } else {
      this._preview = null;
    }
    this._requestUpdate?.();
  }

  /** Convert DrawingPoint (time/price) → pixel (x/y) */
  private toPixel(p: DrawingPoint): { x: number; y: number } | null {
    if (!this._chart || !this._series) return null;
    const x = this._chart.timeScale().timeToCoordinate(p.time as unknown as Time);
    const y = this._series.priceToCoordinate(p.price);
    if (x === null || y === null) return null;
    return { x, y };
  }

  updateAllViews() {
    const renderer = this._paneView._renderer;
    renderer.items = [];
    renderer.preview = null;
    renderer.selectedId = this._selectedId;

    if (!this._chart || !this._series) return;

    renderer.chartW = this._chart.timeScale().width();
    renderer.chartH = (this._chart as any).chartElement?.().clientHeight ?? 600;

    // Convert all drawings
    for (const d of this._drawings) {
      const pts = d.points.map(p => this.toPixel(p)).filter(Boolean) as { x: number; y: number }[];
      if (pts.length === 0) continue;
      renderer.items.push({ drawing: d, pts });
    }

    // Convert preview
    if (this._preview) {
      const d = this._preview.drawing;
      const pts = d.points.map(p => this.toPixel(p)).filter(Boolean) as { x: number; y: number }[];
      if (pts.length > 0) {
        renderer.preview = { drawing: d, pts };
      }
    }
  }

  paneViews() {
    return [this._paneView];
  }
}

