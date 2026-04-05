/**
 * drawings/InteractionManager.ts — State-machine for drawing interaction.
 *
 * Handles click-to-place, rubber-band preview, hit-testing for selection,
 * drag-move, and keyboard shortcuts (Delete, Escape).
 */

import type { IChartApi, ISeriesApi, SeriesType, Time } from 'lightweight-charts';
import type { Drawing, DrawingPoint, DrawingStyle, DrawingTool } from './types';
import { requiredPoints, uid, DEFAULT_STYLE } from './types';

export interface InteractionCallbacks {
  onDrawingComplete: (d: Drawing) => void;
  onDrawingMoved: () => void;
  onPreviewUpdate: (d: Drawing | null) => void;
  onSelectionChange: (id: string | null) => void;
  onDeleteSelected: () => void;
  /** Called after a drawing is finalized so the parent can reset to cursor. */
  onToolAutoReset: () => void;
  /** Called when text tool needs input. Provides pixel position for inline input. */
  onTextInput: (pixelX: number, pixelY: number, point: DrawingPoint) => void;
  /** Called when user double-clicks an existing drawing — open properties panel. */
  onOpenProperties: (id: string) => void;
}

type State = 'idle' | 'placing' | 'dragging';

export class InteractionManager {
  private chart: IChartApi;
  private series: ISeriesApi<SeriesType, Time>;
  private container: HTMLElement;
  private cb: InteractionCallbacks;

  private state: State = 'idle';
  private activeTool: DrawingTool = 'cursor';
  private style: DrawingStyle = { ...DEFAULT_STYLE };
  private pendingPoints: DrawingPoint[] = [];
  private pathPoints: DrawingPoint[] = [];
  private isDrawingPath = false;

  // Dragging
  private dragDrawingId: string | null = null;
  private dragStartPt: DrawingPoint | null = null;
  private dragOriginalPoints: DrawingPoint[] = [];

  // Stored drawings for hit-testing
  private _drawings: Drawing[] = [];

  // Double-click detection (track last pointer-down hit)
  private _lastClickId: string | null = null;
  private _lastClickTime = 0;
  private readonly DBL_CLICK_MS = 350;

  // bound handlers for cleanup
  private _onPointerDown: (e: PointerEvent) => void;
  private _onPointerMove: (e: PointerEvent) => void;
  private _onPointerUp: (e: PointerEvent) => void;
  private _onKeyDown: (e: KeyboardEvent) => void;

  constructor(
    chart: IChartApi,
    series: ISeriesApi<SeriesType, Time>,
    container: HTMLElement,
    callbacks: InteractionCallbacks,
  ) {
    this.chart = chart;
    this.series = series;
    this.container = container;
    this.cb = callbacks;

    this._onPointerDown = this.onPointerDown.bind(this);
    this._onPointerMove = this.onPointerMove.bind(this);
    this._onPointerUp = this.onPointerUp.bind(this);
    this._onKeyDown = this.onKeyDown.bind(this);

    container.addEventListener('pointerdown', this._onPointerDown);
    container.addEventListener('pointermove', this._onPointerMove);
    container.addEventListener('pointerup', this._onPointerUp);
    window.addEventListener('keydown', this._onKeyDown);
  }

  destroy() {
    this.container.removeEventListener('pointerdown', this._onPointerDown);
    this.container.removeEventListener('pointermove', this._onPointerMove);
    this.container.removeEventListener('pointerup', this._onPointerUp);
    window.removeEventListener('keydown', this._onKeyDown);
  }

  setActiveTool(tool: DrawingTool) {
    this.activeTool = tool;
    this.cancel();
    this.container.style.cursor = tool === 'cursor' ? '' : 'crosshair';
  }

  setStyle(style: Partial<DrawingStyle>) {
    Object.assign(this.style, style);
  }

  setDrawings(drawings: Drawing[]) {
    this._drawings = drawings;
  }

  getStyle() { return { ...this.style }; }

  /** Convert pointer event to time/price point */
  private eventToPoint(e: PointerEvent | MouseEvent): DrawingPoint | null {
    const rect = this.container.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const time = this.chart.timeScale().coordinateToTime(x);
    const price = this.series.coordinateToPrice(y);
    if (time === null || price === null) return null;
    return { time: time as unknown as number, price };
  }

  private cancel() {
    this.state = 'idle';
    this.pendingPoints = [];
    this.pathPoints = [];
    this.isDrawingPath = false;
    this.dragDrawingId = null;
    this.dragStartPt = null;
    this.dragOriginalPoints = [];
    this.cb.onPreviewUpdate(null);
  }

  /* ── Hit-testing: find drawing near a point ───────────────────────────── */

  private hitTest(pt: DrawingPoint): string | null {
    const THRESHOLD = 8;

    const px = this.chart.timeScale().timeToCoordinate(pt.time as unknown as Time);
    const py = this.series.priceToCoordinate(pt.price);
    if (px === null || py === null) return null;

    for (let i = this._drawings.length - 1; i >= 0; i--) {
      const d = this._drawings[i];
      if (!d.visible) continue;

      const pixPts = d.points.map(p => ({
        x: this.chart.timeScale().timeToCoordinate(p.time as unknown as Time),
        y: this.series.priceToCoordinate(p.price),
      }));

      // Check handle proximity
      for (const pp of pixPts) {
        if (pp.x === null || pp.y === null) continue;
        if (Math.sqrt((px - pp.x) ** 2 + (py - pp.y) ** 2) <= THRESHOLD) return d.id;
      }

      // Line segments
      if (pixPts.length >= 2) {
        for (let j = 0; j < pixPts.length - 1; j++) {
          const a = pixPts[j];
          const b = pixPts[j + 1];
          if (a.x === null || a.y === null || b.x === null || b.y === null) continue;
          if (pointToSegmentDist(px, py, a.x, a.y, b.x, b.y) <= THRESHOLD) return d.id;
        }
      }

      // Rectangles / position tools
      if (['rect', 'measure', 'longposition', 'shortposition', 'fib'].includes(d.tool) && pixPts.length >= 2) {
        const a = pixPts[0];
        const b = pixPts[1];
        if (a.x !== null && a.y !== null && b.x !== null && b.y !== null) {
          const minX = Math.min(a.x, b.x) - 4;
          const maxX = Math.max(a.x, b.x) + 4;
          const minY = Math.min(a.y, b.y) - 4;
          const maxY = Math.max(a.y, b.y) + 4;
          if (px >= minX && px <= maxX && py >= minY && py <= maxY) return d.id;
        }
      }

      // hline
      if (d.tool === 'hline' && pixPts[0]?.y !== null) {
        if (Math.abs(py - pixPts[0].y!) <= THRESHOLD) return d.id;
      }

      // vline
      if (d.tool === 'vline' && pixPts[0]?.x !== null) {
        if (Math.abs(px - pixPts[0].x!) <= THRESHOLD) return d.id;
      }

      // text
      if (d.tool === 'text' && pixPts[0]?.x !== null && pixPts[0]?.y !== null) {
        if (Math.abs(px - pixPts[0].x!) < 60 && Math.abs(py - pixPts[0].y!) < 20) return d.id;
      }
    }
    return null;
  }

  /* ── Pointer handlers ─────────────────────────────────────────────────── */

  private onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const pt = this.eventToPoint(e);
    if (!pt) return;

    // ── Cursor mode: hit-test for selection / start drag ──
    if (this.activeTool === 'cursor') {
      const hitId = this.hitTest(pt);
      if (hitId) {
        const now = Date.now();
        const isDoubleClick = hitId === this._lastClickId && (now - this._lastClickTime) < this.DBL_CLICK_MS;

        this._lastClickId = hitId;
        this._lastClickTime = now;

        if (isDoubleClick) {
          // Double-click → open properties panel
          this._lastClickId = null;
          this._lastClickTime = 0;
          this.cb.onSelectionChange(hitId);
          this.cb.onOpenProperties(hitId);
          e.stopPropagation();
          return;
        }

        // Single click → select + start potential drag (unless locked)
        this.cb.onSelectionChange(hitId);
        const drawing = this._drawings.find(d => d.id === hitId);
        if (drawing && !drawing.locked) {
          this.state = 'dragging';
          this.dragDrawingId = hitId;
          this.dragStartPt = pt;
          this.dragOriginalPoints = drawing.points.map(p => ({ ...p }));
          this.container.style.cursor = 'grabbing';
        }
        e.stopPropagation();
      } else {
        this._lastClickId = null;
        this._lastClickTime = 0;
        this.cb.onSelectionChange(null);
      }
      return;
    }

    // ── Text tool: show inline input ──
    if (this.activeTool === 'text' && this.pendingPoints.length === 0) {
      const rect = this.container.getBoundingClientRect();
      this.cb.onTextInput(e.clientX - rect.left, e.clientY - rect.top, pt);
      e.stopPropagation();
      return;
    }

    // ── Path tool ──
    if (this.activeTool === 'path') {
      this.isDrawingPath = true;
      this.pathPoints = [pt];
      this.state = 'placing';
      e.stopPropagation();
      return;
    }

    const req = requiredPoints(this.activeTool);
    this.pendingPoints.push(pt);
    this.state = 'placing';

    if (this.pendingPoints.length >= req && req > 0) {
      this.finalize();
    }

    e.stopPropagation();
  }

  private onPointerMove(e: PointerEvent) {
    const pt = this.eventToPoint(e);
    if (!pt) return;

    // ── Dragging ──
    if (this.state === 'dragging' && this.dragDrawingId && this.dragStartPt) {
      const dTime = pt.time - this.dragStartPt.time;
      const dPrice = pt.price - this.dragStartPt.price;
      const drawing = this._drawings.find(d => d.id === this.dragDrawingId);
      if (drawing) {
        drawing.points = this.dragOriginalPoints.map(p => ({
          time: p.time + dTime,
          price: p.price + dPrice,
        }));
        this.cb.onDrawingMoved();
      }
      return;
    }

    // ── Cursor hover cursor ──
    if (this.activeTool === 'cursor' && this.state === 'idle') {
      const hitId = this.hitTest(pt);
      if (hitId) {
        const drawing = this._drawings.find(d => d.id === hitId);
        this.container.style.cursor = drawing?.locked ? 'pointer' : 'grab';
      } else {
        this.container.style.cursor = '';
      }
      return;
    }

    if (this.state !== 'placing') return;

    // Path accumulate
    if (this.activeTool === 'path' && this.isDrawingPath) {
      this.pathPoints.push(pt);
      this.cb.onPreviewUpdate(this.makeDrawing(this.pathPoints));
      return;
    }

    // Rubber-band
    if (this.pendingPoints.length > 0) {
      this.cb.onPreviewUpdate(this.makeDrawing([...this.pendingPoints, pt]));
    }
  }

  private onPointerUp(_e: PointerEvent) {
    // ── End drag ──
    if (this.state === 'dragging' && this.dragDrawingId) {
      this.container.style.cursor = this.activeTool === 'cursor' ? '' : 'crosshair';
      this.state = 'idle';
      this.dragDrawingId = null;
      this.dragStartPt = null;
      this.dragOriginalPoints = [];
      this.cb.onDrawingMoved();
      return;
    }

    // Path finalize
    if (this.activeTool === 'path' && this.isDrawingPath) {
      if (this.pathPoints.length >= 2) {
        this.cb.onDrawingComplete(this.makeDrawing(this.pathPoints));
        this.cb.onToolAutoReset();
      }
      this.cancel();
    }
  }

  private onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Escape') { this.cancel(); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      this.cb.onDeleteSelected();
    }
  }

  /* ── Drawing creation ─────────────────────────────────────────────────── */

  private makeDrawing(points: DrawingPoint[]): Drawing {
    return { id: uid(), tool: this.activeTool, points: [...points], style: { ...this.style }, visible: true };
  }

  /** Finalize text from inline input */
  finalizeText(text: string, point: DrawingPoint) {
    if (!text.trim()) return;
    this.cb.onDrawingComplete({
      id: uid(), tool: 'text', points: [point],
      style: { ...this.style, text }, visible: true,
    });
    this.cb.onToolAutoReset();
  }

  private finalize() {
    const drawing = this.makeDrawing(this.pendingPoints);
    if (drawing.tool === 'hline') drawing.style.text = drawing.points[0].price.toFixed(2);
    this.cb.onDrawingComplete(drawing);
    this.cancel();
    this.cb.onToolAutoReset();
  }
}

/* ── Geometry helper ────────────────────────────────────────────────────── */

function pointToSegmentDist(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return Math.sqrt((px - ax) ** 2 + (py - ay) ** 2);
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lenSq));
  return Math.sqrt((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2);
}
