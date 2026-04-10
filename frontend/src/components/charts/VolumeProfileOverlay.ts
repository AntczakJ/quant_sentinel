/**
 * VolumeProfileOverlay.ts — lightweight-charts v4 Primitive
 *
 * Renders horizontal volume bars on the right side of the chart.
 * POC highlighted in gold, Value Area in blue, rest in gray.
 *
 * Price-to-coordinate mapping uses a stored series reference.
 */

import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  Time,
  IChartApi,
  ISeriesApi,
} from 'lightweight-charts';

interface VPBar {
  price: number;
  volume: number;
  pct: number;
}

export interface VPData {
  poc: number;
  vah: number;
  val: number;
  histogram: VPBar[];
}

class VPRenderer implements ISeriesPrimitivePaneRenderer {
  bars: { y: number; h: number; w: number; isPoc: boolean; isVA: boolean }[] = [];

  draw(target: { useMediaCoordinateSpace: Function }) {
    if (!this.bars.length) return;

    target.useMediaCoordinateSpace((scope: { context: CanvasRenderingContext2D; mediaSize: { width: number } }) => {
      const ctx = scope.context;
      const chartW = scope.mediaSize.width;
      const maxBarW = chartW * 0.10;

      for (const bar of this.bars) {
        const barW = bar.w * maxBarW;
        const x = chartW - barW - 2;

        ctx.fillStyle = bar.isPoc
          ? 'rgba(251,191,36,0.30)'
          : bar.isVA
          ? 'rgba(59,130,246,0.12)'
          : 'rgba(107,114,128,0.07)';

        ctx.fillRect(x, bar.y, barW, Math.max(bar.h, 1));

        if (bar.isPoc) {
          ctx.strokeStyle = 'rgba(251,191,36,0.5)';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(x, bar.y, barW, Math.max(bar.h, 1));
        }
      }
    });
  }
}

class VPPaneView implements ISeriesPrimitivePaneView {
  _renderer = new VPRenderer();
  renderer() { return this._renderer; }
  zOrder(): 'bottom' | 'normal' | 'top' { return 'bottom'; }
}

export class VolumeProfileOverlay implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | null = null;
  private _requestUpdate: (() => void) | null = null;
  private _data: VPData | null = null;
  private _paneView = new VPPaneView();
  private _visible = true;
  private _series: ISeriesApi<'Candlestick'> | null = null;

  /** Call after attaching to store the series reference for price→coordinate */
  setSeries(series: ISeriesApi<'Candlestick'>) {
    this._series = series;
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this._chart = param.chart;
    this._requestUpdate = param.requestUpdate;
  }

  detached() {
    this._chart = null;
    this._requestUpdate = null;
    this._series = null;
  }

  setData(data: VPData | null) {
    this._data = data;
    this._requestUpdate?.();
  }

  setVisible(visible: boolean) {
    this._visible = visible;
    this._requestUpdate?.();
  }

  updateAllViews() {
    const draws: VPRenderer['bars'] = [];

    if (!this._chart || !this._series || !this._data || !this._visible || !this._data.histogram?.length) {
      this._paneView._renderer.bars = draws;
      return;
    }

    const { poc, vah, val, histogram } = this._data;
    const series = this._series;

    const maxVol = Math.max(...histogram.map(b => b.volume));
    if (maxVol <= 0) {
      this._paneView._renderer.bars = draws;
      return;
    }

    // Sort by price ascending
    const sorted = [...histogram].sort((a, b) => a.price - b.price);
    const priceStep = sorted.length > 1 ? Math.abs(sorted[1].price - sorted[0].price) : 1;

    for (const bar of sorted) {
      const y1 = series.priceToCoordinate(bar.price + priceStep / 2);
      const y2 = series.priceToCoordinate(bar.price - priceStep / 2);

      if (y1 === null || y2 === null) continue;

      const yTop = Math.min(y1, y2);
      const h = Math.abs(y2 - y1);
      const w = bar.volume / maxVol; // 0..1 normalized width

      const isPoc = Math.abs(bar.price - poc) < priceStep;
      const isVA = bar.price >= val && bar.price <= vah;

      draws.push({ y: yTop, h, w, isPoc, isVA });
    }

    this._paneView._renderer.bars = draws;
  }

  paneViews() {
    return [this._paneView];
  }
}
