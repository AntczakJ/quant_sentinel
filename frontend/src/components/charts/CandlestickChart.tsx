/**
 * src/components/charts/CandlestickChart.tsx
 *
 * Professional TradingView-style chart using lightweight-charts v4.
 *
 * Features:
 *  - Real OHLC candlesticks with wicks
 *  - Volume histogram overlay (bottom 15 %)
 *  - EMA 21 overlay line
 *  - Bollinger Bands (upper / middle / lower)
 *  - Synced RSI sub-chart with 30 / 70 reference lines
 *  - Current-price tracking line
 *  - SL / TP / Entry price lines from latest scanner signal
 *  - Interval selector toolbar
 *  - Crosshair with OHLCV legend
 *  - Mouse-wheel zoom / drag scroll (built-in)
 *  - Responsive via ResizeObserver
 *  - 60 s auto-refresh (matches backend cache TTL)
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import {
  createChart,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type UTCTimestamp,
  type MouseEventParams,
} from 'lightweight-charts';
import { RefreshCw, AlertCircle, Layers, Trash2 } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';
import { marketAPI, signalsAPI } from '../../api/client';
import type { Candle } from '../../types/trading';
import { detectAllSmcZones, buildPositionZones } from './smcDetector';
import { SmcZonesOverlay } from './SmcOverlay';
import {
  DrawingToolbar, DrawingsOverlay, InteractionManager,
  DrawingPropertiesPanel,
  saveDrawings, loadDrawings, clearDrawings,
  DEFAULT_STYLE,
} from './drawings';
import type { Drawing, DrawingTool, DrawingStyle } from './drawings';

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  TECHNICAL INDICATOR MATH (client-side, avoids extra API calls)           */
/* ═══════════════════════════════════════════════════════════════════════════ */

function calcEMA(closes: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1);
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += closes[i];
  out[period - 1] = sum / period;
  for (let i = period; i < closes.length; i++) {
    out[i] = closes[i] * k + (out[i - 1] as number) * (1 - k);
  }
  return out;
}

function calcRSI(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return out;
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gainSum += d;
    else lossSum -= d;
  }
  let avgGain = gainSum / period;
  let avgLoss = lossSum / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + (d > 0 ? d : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (d < 0 ? -d : 0)) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

function calcSMA(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  out[period - 1] = sum / period;
  for (let i = period; i < values.length; i++) {
    sum += values[i] - values[i - period];
    out[i] = sum / period;
  }
  return out;
}

function calcBollingerBands(
  closes: number[],
  period = 20,
  mult = 2,
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calcSMA(closes, period);
  const upper: (number | null)[] = new Array(closes.length).fill(null);
  const lower: (number | null)[] = new Array(closes.length).fill(null);
  for (let i = period - 1; i < closes.length; i++) {
    const m = middle[i];
    if (m === null) continue;
    let sqSum = 0;
    for (let j = i - period + 1; j <= i; j++) sqSum += (closes[j] - m) ** 2;
    const std = Math.sqrt(sqSum / period);
    upper[i] = m + mult * std;
    lower[i] = m - mult * std;
  }
  return { upper, middle, lower };
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  COLOR PALETTE (matches CSS vars / TradingView dark theme)                */
/* ═══════════════════════════════════════════════════════════════════════════ */

const COLORS = {
  bg: '#0d1117',
  gridLines: '#1a2030',
  text: '#6b7280',
  crosshair: '#4b5563',
  candleUp: '#22c55e',
  candleDown: '#ef4444',
  wickUp: '#22c55e',
  wickDown: '#ef4444',
  volumeUp: 'rgba(34,197,94,0.25)',
  volumeDown: 'rgba(239,68,68,0.20)',
  ema21: '#f59e0b',
  bbUpper: 'rgba(59,130,246,0.45)',
  bbMiddle: 'rgba(59,130,246,0.70)',
  bbLower: 'rgba(59,130,246,0.45)',
  rsiLine: '#8b5cf6',
  rsiOverbought: 'rgba(239,68,68,0.35)',
  rsiOversold: 'rgba(34,197,94,0.35)',
  priceLine: '#e2e8f0',
  slLine: '#ef4444',
  tpLine: '#22c55e',
  entryLine: '#3b82f6',
  eqLine: '#f59e0b',
} as const;

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  OHLCV LEGEND (top-left overlay like TradingView)                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

interface LegendData {
  o: number; h: number; l: number; c: number; v: number; change: number;
}

function OHLCVLegend({ data, interval }: { data: LegendData | null; interval: string }) {
  if (!data) return null;
  const up = data.c >= data.o;
  const col = up ? 'text-green-400' : 'text-red-400';
  return (
    <div className="absolute top-1 left-2 z-20 flex items-center gap-2 text-[10px] font-mono pointer-events-none select-none">
      <span className="text-gray-500 font-semibold">XAU/USD · {interval}</span>
      <span className="text-gray-500">O</span><span className={col}>{data.o.toFixed(2)}</span>
      <span className="text-gray-500">H</span><span className={col}>{data.h.toFixed(2)}</span>
      <span className="text-gray-500">L</span><span className={col}>{data.l.toFixed(2)}</span>
      <span className="text-gray-500">C</span><span className={col}>{data.c.toFixed(2)}</span>
      <span className={`ml-1 ${col}`}>{data.change >= 0 ? '+' : ''}{data.change.toFixed(2)}%</span>
      {data.v > 0 && <span className="text-gray-600 ml-1">Vol {data.v.toLocaleString()}</span>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  INTERVAL TOOLBAR                                                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

const INTERVALS = ['5m', '15m', '1h', '4h'] as const;

function IntervalToolbar({
  selected, onSelect, refreshing, onRefresh, smcVisible, onToggleSmc,
  drawingCount, onClearDrawings,
}: {
  selected: string; onSelect: (v: string) => void; refreshing: boolean; onRefresh: () => void;
  smcVisible: boolean; onToggleSmc: () => void;
  drawingCount: number; onClearDrawings: () => void;
}) {
  return (
    <div className="flex items-center gap-1.5 mb-1">
      {INTERVALS.map((tf) => (
        <button
          key={tf}
          onClick={() => onSelect(tf)}
          className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors ${
            selected === tf
              ? 'bg-blue-600/90 text-white'
              : 'bg-[#1a2030] text-gray-500 hover:text-gray-300 hover:bg-[#222a3a]'
          }`}
        >
          {tf}
        </button>
      ))}
      <div className="flex-1" />
      {drawingCount > 0 && (
        <button
          onClick={onClearDrawings}
          className="p-1.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 bg-red-500/15 text-red-400 hover:bg-red-500/25"
          title={`Clear all ${drawingCount} drawings`}
        >
          <Trash2 size={11} />
          <span className="hidden sm:inline">{drawingCount}</span>
        </button>
      )}
      <button
        onClick={onToggleSmc}
        className={`p-1.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 ${
          smcVisible
            ? 'bg-amber-600/30 text-amber-400 hover:bg-amber-600/40'
            : 'bg-[#1a2030] text-gray-600 hover:text-gray-400 hover:bg-[#222a3a]'
        }`}
        title={smcVisible ? 'Ukryj SMC overlay' : 'Pokaż SMC overlay (FVG, OB, S/D, EQ)'}
      >
        <Layers size={11} />
        <span className="hidden sm:inline">SMC</span>
      </button>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="p-1.5 rounded text-gray-500 hover:text-gray-300 hover:bg-[#1a2030] transition-colors disabled:opacity-40"
        title="Refresh"
      >
        <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
      </button>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN CHART COMPONENT                                                     */
/* ═══════════════════════════════════════════════════════════════════════════ */

export function CandlestickChart() {
  const { selectedInterval, setSelectedInterval } = useTradingStore();

  // Refs for chart DOM containers
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);

  // Chart API refs
  const mainChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);

  // Series refs
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbUpperRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbMiddleRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbLowerRef = useRef<ISeriesApi<'Line'> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Track signal price lines so we can remove them before re-creating
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const signalPriceLinesRef = useRef<any[]>([]);

  // SMC overlay primitive
  const smcOverlayRef = useRef<SmcZonesOverlay | null>(null);
  const [smcVisible, setSmcVisible] = useState(true);

  // Drawing tools
  const drawingsOverlayRef = useRef<DrawingsOverlay | null>(null);
  const interactionRef = useRef<InteractionManager | null>(null);
  const [activeTool, setActiveTool] = useState<DrawingTool>('cursor');
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawColor, setDrawColor] = useState(DEFAULT_STYLE.color);
  const drawingsRef = useRef<Drawing[]>([]);
  const [showPropertiesPanel, setShowPropertiesPanel] = useState(false);

  // Inline text input state
  const [textInput, setTextInput] = useState<{ x: number; y: number; point: { time: number; price: number } } | null>(null);
  const textInputRef = useRef<HTMLInputElement>(null);

  // State
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [legendData, setLegendData] = useState<LegendData | null>(null);
  const isFirstLoad = useRef(true);
  const rawCandlesRef = useRef<CandlestickData[]>([]);

  /* ── Create charts on mount ────────────────────────────────────────────── */
  useEffect(() => {
    if (!mainContainerRef.current || !rsiContainerRef.current) return;

    const commonLayout = {
      background: { color: COLORS.bg },
      textColor: COLORS.text,
      fontSize: 11,
      fontFamily: "'JetBrains Mono', 'Inter', monospace",
    };

    const commonGrid = {
      vertLines: { color: COLORS.gridLines },
      horzLines: { color: COLORS.gridLines },
    };

    const commonTimeScale = {
      borderColor: COLORS.gridLines,
      timeVisible: true,
      secondsVisible: false,
    };

    // ─── Main chart ───
    const mainChart = createChart(mainContainerRef.current, {
      autoSize: true,          // ← fills container automatically via internal ResizeObserver
      layout: commonLayout,
      grid: commonGrid,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a2030' },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a2030' },
      },
      rightPriceScale: {
        borderColor: COLORS.gridLines,
        scaleMargins: { top: 0.05, bottom: 0.18 },
        autoScale: true,
      },
      timeScale: { ...commonTimeScale, barSpacing: 8 },
      handleScroll: { vertTouchDrag: false },
    });
    mainChartRef.current = mainChart;

    // Candlestick series
    const candleSeries = mainChart.addCandlestickSeries({
      upColor: COLORS.candleUp,
      downColor: COLORS.candleDown,
      wickUpColor: COLORS.wickUp,
      wickDownColor: COLORS.wickDown,
      borderVisible: false,
    });
    candleSeriesRef.current = candleSeries;

    // Volume histogram (overlaid at bottom)
    const volumeSeries = mainChart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    mainChart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeriesRef.current = volumeSeries;

    // EMA 21 overlay
    const emaSeries = mainChart.addLineSeries({
      color: COLORS.ema21,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    emaSeriesRef.current = emaSeries;

    // Bollinger Bands
    const bbUpper = mainChart.addLineSeries({
      color: COLORS.bbUpper, lineWidth: 1, lineStyle: LineStyle.Dotted,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    bbUpperRef.current = bbUpper;

    const bbMiddle = mainChart.addLineSeries({
      color: COLORS.bbMiddle, lineWidth: 1, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    bbMiddleRef.current = bbMiddle;

    const bbLower = mainChart.addLineSeries({
      color: COLORS.bbLower, lineWidth: 1, lineStyle: LineStyle.Dotted,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    bbLowerRef.current = bbLower;

    // ─── RSI sub-chart ───
    const rsiChart = createChart(rsiContainerRef.current, {
      autoSize: true,          // ← fills 90px container automatically
      layout: commonLayout,
      grid: commonGrid,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a2030' },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#1a2030' },
      },
      rightPriceScale: {
        borderColor: COLORS.gridLines,
        scaleMargins: { top: 0.08, bottom: 0.08 },
        autoScale: true,
      },
      timeScale: { ...commonTimeScale, barSpacing: 8, visible: false },
      handleScroll: { vertTouchDrag: false },
    });
    rsiChartRef.current = rsiChart;

    const rsiSeries = rsiChart.addLineSeries({
      color: COLORS.rsiLine,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });
    rsiSeriesRef.current = rsiSeries;

    // RSI reference lines
    rsiSeries.createPriceLine({ price: 70, color: COLORS.rsiOverbought, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
    rsiSeries.createPriceLine({ price: 30, color: COLORS.rsiOversold, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
    rsiSeries.createPriceLine({ price: 50, color: 'rgba(107,114,128,0.25)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' });

    // ─── Attach SMC zones overlay to candle series ───
    const smcOverlay = new SmcZonesOverlay();
    candleSeries.attachPrimitive(smcOverlay);
    smcOverlayRef.current = smcOverlay;

    // ─── Attach user drawings overlay (renders on top of SMC) ───
    const drawingsOverlay = new DrawingsOverlay();
    candleSeries.attachPrimitive(drawingsOverlay);
    drawingsOverlayRef.current = drawingsOverlay;

    // ─── Sync time scales ───
    let isSyncing = false;
    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (isSyncing || !range) return;
      isSyncing = true;
      rsiChart.timeScale().setVisibleLogicalRange(range);
      isSyncing = false;
    });
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (isSyncing || !range) return;
      isSyncing = true;
      mainChart.timeScale().setVisibleLogicalRange(range);
      isSyncing = false;
    });

    // ─── OHLCV Legend on crosshair ───
    mainChart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (!param.time) {
        const last = rawCandlesRef.current[rawCandlesRef.current.length - 1];
        if (last) {
          setLegendData({
            o: last.open, h: last.high, l: last.low, c: last.close,
            v: 0, change: ((last.close - last.open) / last.open) * 100,
          });
        }
        return;
      }
      const cs = param.seriesData?.get(candleSeries) as CandlestickData | undefined;
      const vs = param.seriesData?.get(volumeSeries) as HistogramData | undefined;
      if (cs) {
        setLegendData({
          o: cs.open, h: cs.high, l: cs.low, c: cs.close,
          v: vs?.value ?? 0,
          change: ((cs.close - cs.open) / cs.open) * 100,
        });
      }
    });

    return () => {
      // Detach overlays before removing chart
      try { candleSeries.detachPrimitive(smcOverlay); } catch { /* ok */ }
      try { candleSeries.detachPrimitive(drawingsOverlay); } catch { /* ok */ }
      mainChart.remove();
      rsiChart.remove();
      mainChartRef.current = null;
      rsiChartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── InteractionManager for drawing tools ──────────────────────────────── */
  useEffect(() => {
    const chart = mainChartRef.current;
    const series = candleSeriesRef.current;
    const container = mainContainerRef.current;
    if (!chart || !series || !container) return;

    const mgr = new InteractionManager(chart, series as any, container, {
      onDrawingComplete: (d: Drawing) => {
        const next = [...drawingsRef.current, d];
        drawingsRef.current = next;
        setDrawings(next);
        drawingsOverlayRef.current?.setDrawings(next);
        mgr.setDrawings(next);
        saveDrawings('XAU/USD', selectedInterval, next);
        drawingsOverlayRef.current?.setPreview(null);
      },
      onDrawingMoved: () => {
        // Drawings were mutated in-place by drag — force re-render + save
        const current = [...drawingsRef.current];
        drawingsRef.current = current;
        setDrawings(current);
        drawingsOverlayRef.current?.setDrawings(current);
        saveDrawings('XAU/USD', selectedInterval, current);
      },
      onPreviewUpdate: (d: Drawing | null) => {
        drawingsOverlayRef.current?.setPreview(d);
      },
      onSelectionChange: (id: string | null) => {
        setSelectedDrawingId(id);
        drawingsOverlayRef.current?.setSelectedId(id);
        setShowPropertiesPanel(id !== null);
      },
      onDeleteSelected: () => {
        handleDeleteSelected();
      },
      onToolAutoReset: () => {
        setActiveTool('cursor');
      },
      onTextInput: (pixelX: number, pixelY: number, point) => {
        setTextInput({ x: pixelX, y: pixelY, point });
      },
      onOpenProperties: (id: string) => {
        setSelectedDrawingId(id);
        drawingsOverlayRef.current?.setSelectedId(id);
        setShowPropertiesPanel(true);
      },
    });
    interactionRef.current = mgr;

    // Load saved drawings
    const saved = loadDrawings('XAU/USD', selectedInterval);
    drawingsRef.current = saved;
    setDrawings(saved);
    drawingsOverlayRef.current?.setDrawings(saved);
    mgr.setDrawings(saved);

    return () => {
      mgr.destroy();
      interactionRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedInterval]);

  /* ── Sync active tool to InteractionManager ────────────────────────────── */
  useEffect(() => {
    interactionRef.current?.setActiveTool(activeTool);
    // Disable chart pan/zoom when a tool is active
    if (mainChartRef.current) {
      const isDrawing = activeTool !== 'cursor';
      mainChartRef.current.applyOptions({
        handleScroll: { mouseWheel: true, pressedMouseMove: !isDrawing, horzTouchDrag: !isDrawing, vertTouchDrag: false },
        handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: !isDrawing, axisDoubleClickReset: { time: !isDrawing, price: !isDrawing } },
      });
    }
  }, [activeTool]);

  /* ── Drawing helper callbacks ──────────────────────────────────────────── */
  const handleDeleteSelected = useCallback(() => {
    if (!selectedDrawingId) return;
    const next = drawingsRef.current.filter(d => d.id !== selectedDrawingId);
    drawingsRef.current = next;
    setDrawings(next);
    setSelectedDrawingId(null);
    setShowPropertiesPanel(false);
    drawingsOverlayRef.current?.setDrawings(next);
    drawingsOverlayRef.current?.setSelectedId(null);
    interactionRef.current?.setDrawings(next);
    saveDrawings('XAU/USD', selectedInterval, next);
  }, [selectedDrawingId, selectedInterval]);

  const handleClearAll = useCallback(() => {
    drawingsRef.current = [];
    setDrawings([]);
    setSelectedDrawingId(null);
    setShowPropertiesPanel(false);
    drawingsOverlayRef.current?.setDrawings([]);
    drawingsOverlayRef.current?.setSelectedId(null);
    interactionRef.current?.setDrawings([]);
    clearDrawings('XAU/USD', selectedInterval);
  }, [selectedInterval]);

  const handleStyleChange = useCallback((style: Partial<DrawingStyle>) => {
    if (style.color) setDrawColor(style.color);
    interactionRef.current?.setStyle(style);
  }, []);

  const handleUpdateDrawing = useCallback((id: string, patch: Partial<Drawing>) => {
    const next = drawingsRef.current.map(d => d.id === id ? { ...d, ...patch } : d);
    drawingsRef.current = next;
    setDrawings(next);
    drawingsOverlayRef.current?.setDrawings(next);
    interactionRef.current?.setDrawings(next);
    saveDrawings('XAU/USD', selectedInterval, next);
  }, [selectedInterval]);

  const handleTextSubmit = useCallback((text: string) => {
    if (textInput && text.trim()) {
      interactionRef.current?.finalizeText(text, textInput.point);
    }
    setTextInput(null);
  }, [textInput]);

  /* ── Data fetching ─────────────────────────────────────────────────────── */
  const fetchData = useCallback(async () => {
    try {
      if (isFirstLoad.current) setLoading(true);
      else setRefreshing(true);
      setError(null);

      const rawCandles: Candle[] = await marketAPI.getCandles('XAU/USD', selectedInterval, 200);
      if (!rawCandles?.length) throw new Error('No candle data');

      // Sort ascending by time & deduplicate (lightweight-charts requires strictly ascending times)
      const candleData = rawCandles
        .map((c) => ({ ...c, _ts: Math.floor(new Date(c.timestamp).getTime() / 1000) }))
        .sort((a, b) => a._ts - b._ts)
        .filter((c, i, arr) => i === 0 || c._ts > arr[i - 1]._ts);

      const closes = candleData.map((c) => c.close);

      // ── Build series data ──
      const candleSd: CandlestickData[] = [];
      const volumeSd: HistogramData[] = [];
      const ema21 = calcEMA(closes, 21);
      const rsi14 = calcRSI(closes, 14);
      const bb = calcBollingerBands(closes, 20, 2);
      const emaSd: LineData[] = [];
      const rsiSd: LineData[] = [];
      const bbUpperSd: LineData[] = [];
      const bbMiddleSd: LineData[] = [];
      const bbLowerSd: LineData[] = [];

      for (let i = 0; i < candleData.length; i++) {
        const c = candleData[i];
        const t = c._ts as UTCTimestamp;
        const up = c.close >= c.open;

        candleSd.push({ time: t, open: c.open, high: c.high, low: c.low, close: c.close });
        volumeSd.push({ time: t, value: c.volume, color: up ? COLORS.volumeUp : COLORS.volumeDown });

        if (ema21[i] !== null) emaSd.push({ time: t, value: ema21[i]! });
        if (rsi14[i] !== null) rsiSd.push({ time: t, value: rsi14[i]! });
        if (bb.upper[i] !== null) bbUpperSd.push({ time: t, value: bb.upper[i]! });
        if (bb.middle[i] !== null) bbMiddleSd.push({ time: t, value: bb.middle[i]! });
        if (bb.lower[i] !== null) bbLowerSd.push({ time: t, value: bb.lower[i]! });
      }

      rawCandlesRef.current = candleSd;

      // ── Apply data to series ──
      candleSeriesRef.current?.setData(candleSd);
      volumeSeriesRef.current?.setData(volumeSd);
      emaSeriesRef.current?.setData(emaSd);
      rsiSeriesRef.current?.setData(rsiSd);
      bbUpperRef.current?.setData(bbUpperSd);
      bbMiddleRef.current?.setData(bbMiddleSd);
      bbLowerRef.current?.setData(bbLowerSd);

      // ── Clear old price lines before creating new ones ──
      if (candleSeriesRef.current) {
        for (const pl of signalPriceLinesRef.current) {
          try { candleSeriesRef.current.removePriceLine(pl); } catch { /* already removed */ }
        }
      }
      signalPriceLinesRef.current = [];

      // ── SMC Zones overlay ──
      if (smcVisible && smcOverlayRef.current) {
        const smcResult = detectAllSmcZones(candleSd as Array<{ time: number; open: number; high: number; low: number; close: number }>);

        // Equilibrium price line
        if (smcResult.eqLevel !== null && candleSeriesRef.current) {
          signalPriceLinesRef.current.push(
            candleSeriesRef.current.createPriceLine({
              price: smcResult.eqLevel,
              color: COLORS.eqLine,
              lineWidth: 1,
              lineStyle: LineStyle.Dotted,
              axisLabelVisible: true,
              title: 'EQ',
            })
          );
        }

        smcOverlayRef.current.setZones(smcResult.zones);
      } else if (smcOverlayRef.current) {
        smcOverlayRef.current.setZones([]);
      }

      // ── SL / TP / Entry lines from latest scanner signal ──
      try {
        const signals = await signalsAPI.getScannerHistory(1);
        if (signals?.length && candleSeriesRef.current) {
          const sig = signals[0];
          const cs = candleSeriesRef.current;
          if (sig.entry_price) {
            signalPriceLinesRef.current.push(cs.createPriceLine({
              price: sig.entry_price, color: COLORS.entryLine,
              lineWidth: 1, lineStyle: LineStyle.LargeDashed,
              axisLabelVisible: true, title: 'ENTRY',
            }));
          }
          if (sig.sl) {
            signalPriceLinesRef.current.push(cs.createPriceLine({
              price: sig.sl, color: COLORS.slLine,
              lineWidth: 1, lineStyle: LineStyle.Solid,
              axisLabelVisible: true, title: 'SL',
            }));
          }
          if (sig.tp) {
            signalPriceLinesRef.current.push(cs.createPriceLine({
              price: sig.tp, color: COLORS.tpLine,
              lineWidth: 1, lineStyle: LineStyle.Solid,
              axisLabelVisible: true, title: 'TP',
            }));
          }

          // Position tool rectangles (TP/SL zones)
          if (sig.entry_price && sig.sl && sig.tp && smcVisible && smcOverlayRef.current) {
            const posTime = candleSd.length > 10
              ? (candleSd[candleSd.length - 10].time as number)
              : (candleSd[0]?.time as number ?? 0);
            const posZones = buildPositionZones(sig.entry_price, sig.sl, sig.tp, posTime);
            const smcResult2 = smcVisible ? detectAllSmcZones(candleSd as any) : { zones: [] };
            smcOverlayRef.current.setZones([...smcResult2.zones, ...posZones]);
          }
        }
      } catch {
        // non-critical — signal overlay is best-effort
      }

      // ── Fit content on first load ──
      if (isFirstLoad.current) {
        mainChartRef.current?.timeScale().fitContent();
        rsiChartRef.current?.timeScale().fitContent();
      }

      // ── Set last candle as legend ──
      const last = candleSd[candleSd.length - 1];
      if (last) {
        setLegendData({
          o: last.open, h: last.high, l: last.low, c: last.close,
          v: volumeSd[volumeSd.length - 1]?.value ?? 0,
          change: ((last.close - last.open) / last.open) * 100,
        });
      }

      isFirstLoad.current = false;
    } catch (err) {
      console.error('Chart data error:', err);
      if (isFirstLoad.current) setError('Failed to load chart data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedInterval, smcVisible]);

  /* ── Fetch on mount + interval change + 60s auto-refresh ───────────────── */
  useEffect(() => {
    void fetchData();
    const timer = setInterval(() => void fetchData(), 60_000);
    return () => clearInterval(timer);
  }, [fetchData]);


  /* ── Render ──────────────────────────────────────────────────────────── */
  return (
    <div className="flex flex-col h-full w-full">
      <IntervalToolbar
        selected={selectedInterval}
        onSelect={setSelectedInterval}
        refreshing={refreshing}
        onRefresh={() => void fetchData()}
        smcVisible={smcVisible}
        onToggleSmc={() => setSmcVisible(v => !v)}
        drawingCount={drawings.length}
        onClearDrawings={handleClearAll}
      />

      {/* Main candlestick + volume chart */}
      <div className="relative flex-1 min-h-0">
        {/* Drawing Toolbar (left vertical strip) */}
        <DrawingToolbar
          activeTool={activeTool}
          onSelectTool={setActiveTool}
          onStyleChange={handleStyleChange}
          currentColor={drawColor}
          onDeleteSelected={handleDeleteSelected}
          onClearAll={handleClearAll}
          hasSelection={!!selectedDrawingId}
        />

        <OHLCVLegend data={legendData} interval={selectedInterval} />
        {refreshing && (
          <div className="absolute top-1 right-2 z-20 flex items-center gap-1 text-[10px] text-gray-600">
            <RefreshCw size={9} className="animate-spin" /> updating…
          </div>
        )}
        {/* Loading / error overlays – container always in DOM so refs attach on first render */}
        {loading && isFirstLoad.current && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#0d1117]/80 text-gray-500 text-sm gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading chart…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#0d1117]/80 text-red-400 text-xs gap-2">
            <AlertCircle size={16} /> {error}
          </div>
        )}
        <div ref={mainContainerRef} className="w-full h-full" style={{ paddingLeft: 42 }} />

        {/* Properties panel – appears when a drawing is selected */}
        {showPropertiesPanel && selectedDrawingId && (() => {
          const sel = drawings.find(d => d.id === selectedDrawingId);
          return sel ? (
            <DrawingPropertiesPanel
              drawing={sel}
              onUpdate={handleUpdateDrawing}
              onDelete={(id) => {
                setShowPropertiesPanel(false);
                setSelectedDrawingId(null);
                const next = drawingsRef.current.filter(d => d.id !== id);
                drawingsRef.current = next;
                setDrawings(next);
                drawingsOverlayRef.current?.setDrawings(next);
                drawingsOverlayRef.current?.setSelectedId(null);
                interactionRef.current?.setDrawings(next);
                saveDrawings('XAU/USD', selectedInterval, next);
              }}
              onClose={() => {
                setShowPropertiesPanel(false);
                setSelectedDrawingId(null);
                drawingsOverlayRef.current?.setSelectedId(null);
              }}
            />
          ) : null;
        })()}

        {/* Inline text input for text drawing tool */}
        {textInput && (
          <div
            className="absolute z-40"
            style={{ left: textInput.x + 42, top: textInput.y }}
          >
            <input
              ref={textInputRef}
              autoFocus
              type="text"
              placeholder="Enter text..."
              className="bg-[#1a2030] border border-blue-500/60 text-white text-xs px-2 py-1 rounded outline-none w-40 shadow-lg"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleTextSubmit((e.target as HTMLInputElement).value);
                } else if (e.key === 'Escape') {
                  setTextInput(null);
                  setActiveTool('cursor');
                }
              }}
              onBlur={(e) => {
                if (e.target.value.trim()) {
                  handleTextSubmit(e.target.value);
                } else {
                  setTextInput(null);
                }
              }}
            />
          </div>
        )}
      </div>

      {/* RSI sub-chart */}
      <div className="relative shrink-0">
        <span className="absolute top-0.5 left-2 z-20 text-[10px] text-gray-600 font-mono pointer-events-none">
          RSI(14)
        </span>
        <div ref={rsiContainerRef} className="w-full" style={{ height: 120 }} />
      </div>
    </div>
  );
}
