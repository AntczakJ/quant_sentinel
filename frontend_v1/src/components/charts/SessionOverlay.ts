/**
 * SessionOverlay.ts — lightweight-charts v4 Primitive that draws
 * semi-transparent background bands for trading sessions (Asian/London/NY)
 * and highlights killzone periods.
 *
 * Usage:
 *   const overlay = new SessionOverlay();
 *   candleSeries.attachPrimitive(overlay);
 *   overlay.setCandles(candleData);  // pass candle timestamps
 *   overlay.setVisible(true/false);
 *   candleSeries.detachPrimitive(overlay);
 */

import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  IChartApi,
} from 'lightweight-charts';

/* ── Session definitions (UTC hours) ─────────────────────────────────── */

interface SessionDef {
  name: string;
  /** UTC hour range [start, end). Wraps at midnight if start > end. */
  startH: number;
  endH: number;
  color: string;
  label: string;
}

const SESSIONS: SessionDef[] = [
  { name: 'asian',    startH: 0,  endH: 8,  color: 'rgba(245,158,11,0.06)',  label: 'ASIAN' },
  { name: 'london',   startH: 7,  endH: 16, color: 'rgba(59,130,246,0.06)',  label: 'LONDON' },
  { name: 'new_york', startH: 13, endH: 22, color: 'rgba(34,197,94,0.06)',   label: 'NY' },
];

/** Killzone = high-volatility overlap windows */
const KILLZONES = [
  { startH: 7,  endH: 9,  color: 'rgba(245,158,11,0.10)' }, // Asian/London overlap
  { startH: 13, endH: 16, color: 'rgba(139,92,246,0.10)' },  // London/NY overlap
];

function isLight(): boolean {
  return document.documentElement.classList.contains('light');
}

/* ── Detect session boundaries from candle timestamps ────────────────── */

interface SessionBand {
  startTime: number;  // UTC timestamp
  endTime: number;
  color: string;
  label: string;
  isKillzone: boolean;
}

function detectSessionBands(timestamps: number[]): SessionBand[] {
  if (!timestamps.length) {return [];}

  const bands: SessionBand[] = [];
  const light = isLight();
  // Boost opacity slightly in light mode for visibility
  const opacityMul = light ? 1.6 : 1;

  // Group consecutive candles by session
  let currentSession: string | null = null;
  let bandStart = 0;
  let bandColor = '';
  let bandLabel = '';

  for (let i = 0; i < timestamps.length; i++) {
    const ts = timestamps[i];
    const date = new Date(ts * 1000);
    const utcH = date.getUTCHours();

    // Find which session this candle belongs to
    let session = 'off_hours';
    let color = 'rgba(107,114,128,0.03)';
    let label = '';

    for (const s of SESSIONS) {
      if (s.startH <= s.endH) {
        if (utcH >= s.startH && utcH < s.endH) {
          session = s.name;
          color = s.color;
          label = s.label;
          break;
        }
      }
    }

    // Check killzone overlay
    let isKz = false;
    for (const kz of KILLZONES) {
      if (utcH >= kz.startH && utcH < kz.endH) {
        isKz = true;
        // Layer killzone color on top
        color = kz.color;
        break;
      }
    }

    // Apply light mode multiplier
    if (opacityMul !== 1) {
      color = color.replace(/[\d.]+\)$/, (m) => {
        const val = Math.min(parseFloat(m) * opacityMul, 0.15);
        return val.toFixed(3) + ')';
      });
    }

    if (session !== currentSession || i === 0) {
      // Close previous band
      if (currentSession !== null && i > 0) {
        bands.push({
          startTime: bandStart,
          endTime: timestamps[i - 1],
          color: bandColor,
          label: bandLabel,
          isKillzone: false,
        });
      }
      currentSession = session;
      bandStart = ts;
      bandColor = color;
      bandLabel = label;
    }

    // On last candle, close the band
    if (i === timestamps.length - 1 && currentSession !== null) {
      bands.push({
        startTime: bandStart,
        endTime: ts,
        color: bandColor,
        label: bandLabel,
        isKillzone: isKz,
      });
    }
  }

  return bands;
}

/* ── Renderer ────────────────────────────────────────────────────────── */

interface BandDraw {
  x1: number; x2: number;
  color: string;
  label: string;
}

class SessionPaneRenderer implements ISeriesPrimitivePaneRenderer {
  bands: BandDraw[] = [];
  height: number = 0;

  draw(target: { useMediaCoordinateSpace: (cb: (scope: { context: CanvasRenderingContext2D; mediaSize: { height: number } }) => void) => void }) {
    if (!this.bands.length) {return;}

    target.useMediaCoordinateSpace((scope: { context: CanvasRenderingContext2D; mediaSize: { height: number } }) => {
      const ctx = scope.context;
      const h = scope.mediaSize.height;

      for (const b of this.bands) {
        const w = b.x2 - b.x1;
        if (w <= 0) {continue;}

        // Full-height background band
        ctx.fillStyle = b.color;
        ctx.fillRect(b.x1, 0, w, h);

        // Session label at top (only for wider bands)
        if (b.label && w > 40) {
          ctx.font = '600 8px Inter, sans-serif';
          ctx.fillStyle = b.color.replace(/[\d.]+\)$/, '0.35)');
          ctx.fillText(b.label, b.x1 + 4, 12);
        }
      }
    });
  }
}

/* ── Pane View ───────────────────────────────────────────────────────── */

class SessionPaneView implements ISeriesPrimitivePaneView {
  _renderer = new SessionPaneRenderer();

  renderer() { return this._renderer; }

  zOrder(): 'bottom' | 'normal' | 'top' {
    return 'bottom';
  }
}

/* ── Main Primitive ──────────────────────────────────────────────────── */

export class SessionOverlay implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | null = null;
  private _requestUpdate: (() => void) | null = null;
  private _bands: SessionBand[] = [];
  private _paneView = new SessionPaneView();
  private _visible = true;

  attached(param: SeriesAttachedParameter<Time>) {
    this._chart = param.chart;
    this._requestUpdate = param.requestUpdate;
  }

  detached() {
    this._chart = null;
    this._requestUpdate = null;
  }

  /** Pass candle timestamps to detect session boundaries */
  setCandles(timestamps: number[]) {
    this._bands = this._visible ? detectSessionBands(timestamps) : [];
    this._requestUpdate?.();
  }

  /** Toggle visibility */
  setVisible(visible: boolean) {
    this._visible = visible;
    if (!visible) {
      this._bands = [];
    }
    this._requestUpdate?.();
  }

  /** Rebuild bands (e.g., after theme change) */
  rebuild(timestamps: number[]) {
    this._bands = this._visible ? detectSessionBands(timestamps) : [];
    this._requestUpdate?.();
  }

  updateAllViews() {
    const draws: BandDraw[] = [];
    if (!this._chart || !this._bands.length) {
      this._paneView._renderer.bands = draws;
      return;
    }

    const ts = this._chart.timeScale();

    for (const b of this._bands) {
      const x1 = ts.timeToCoordinate(b.startTime as unknown as Time);
      const x2 = ts.timeToCoordinate(b.endTime as unknown as Time);

      if (x1 === null || x2 === null) {continue;}
      if (x2 <= x1) {continue;}

      draws.push({
        x1: Math.max(0, x1),
        x2,
        color: b.color,
        label: b.label,
      });
    }

    this._paneView._renderer.bands = draws;
  }

  paneViews() {
    return [this._paneView];
  }
}
