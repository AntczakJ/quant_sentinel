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

import { useEffect, useRef, useState, useCallback, useDeferredValue, memo, startTransition } from 'react';
import { useToast } from '../ui/Toast';
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
import { get as idbGet, set as idbSet } from 'idb-keyval';
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
import { useIndicatorWorker } from '../../hooks/useIndicatorWorker';

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  IndexedDB candle cache — instant chart render on reload (< 5 ms)         */
/* ═══════════════════════════════════════════════════════════════════════════ */

const IDB_CANDLE_TTL = 90_000; // 90s — slightly longer than refresh interval

interface CachedCandles { candles: Candle[]; ts: number }

async function getCachedCandles(interval: string): Promise<Candle[] | null> {
  try {
    const entry = await idbGet<CachedCandles>(`qs:candles:${interval}`);
    if (entry && Date.now() - entry.ts < IDB_CANDLE_TTL) {return entry.candles;}
  } catch { /* IndexedDB unavailable */ }
  return null;
}

async function setCachedCandles(interval: string, candles: Candle[]): Promise<void> {
  try {
    await idbSet(`qs:candles:${interval}`, { candles, ts: Date.now() } satisfies CachedCandles);
  } catch { /* ignore */ }
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  COLOR PALETTE (matches CSS vars / TradingView dark theme)                */
/* ═══════════════════════════════════════════════════════════════════════════ */

const COLORS = {
  bg: '#131722',
  gridLines: '#1e222d',
  text: '#787b86',
  crosshair: '#758696',
  candleUp: '#26a69a',
  candleDown: '#ef5350',
  wickUp: '#26a69a',
  wickDown: '#ef5350',
  volumeUp: 'rgba(38,166,154,0.28)',
  volumeDown: 'rgba(239,83,80,0.22)',
  ema21: '#f0b90b',
  bbUpper: 'rgba(33,150,243,0.45)',
  bbMiddle: 'rgba(33,150,243,0.70)',
  bbLower: 'rgba(33,150,243,0.45)',
  rsiLine: '#7e57c2',
  rsiOverbought: 'rgba(239,83,80,0.35)',
  rsiOversold: 'rgba(38,166,154,0.35)',
  priceLine: '#d1d4dc',
  slLine: '#ef5350',
  tpLine: '#26a69a',
  entryLine: '#2196f3',
  eqLine: '#f0b90b',
  border: '#2a2e39',
} as const;

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  OHLCV LEGEND (top-left overlay like TradingView)                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

interface LegendData {
  o: number; h: number; l: number; c: number; v: number; change: number;
}

const OHLCVLegend = memo(function OHLCVLegend({ data, interval }: { data: LegendData | null; interval: string }) {
  if (!data) {return null;}
  const up = data.c >= data.o;
  const col = up ? 'text-[#26a69a]' : 'text-[#ef5350]';
  return (
    <div className="absolute top-1 left-12 z-20 flex items-center gap-2 text-[11px] font-sans pointer-events-none select-none">
      <span className="text-[#d1d4dc] font-semibold text-[12px]">XAU/USD</span>
      <span className="text-[#787b86]">·</span>
      <span className="text-[#787b86] font-medium">{interval}</span>
      <span className="text-[#787b86] ml-1">O</span><span className={col}>{data.o.toFixed(2)}</span>
      <span className="text-[#787b86]">H</span><span className={col}>{data.h.toFixed(2)}</span>
      <span className="text-[#787b86]">L</span><span className={col}>{data.l.toFixed(2)}</span>
      <span className="text-[#787b86]">C</span><span className={col}>{data.c.toFixed(2)}</span>
      <span className={`ml-1 ${col} font-medium`}>{data.change >= 0 ? '+' : ''}{data.change.toFixed(2)}%</span>
      {data.v > 0 && <span className="text-[#787b86] ml-1">Vol {data.v.toLocaleString()}</span>}
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  INTERVAL TOOLBAR                                                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

const INTERVALS = ['5m', '15m', '1h', '4h'] as const;

const IntervalToolbar = memo(function IntervalToolbar({
  selected, onSelect, refreshing, onRefresh, smcVisible, onToggleSmc,
  drawingCount, onClearDrawings,
}: {
  selected: string; onSelect: (v: string) => void; refreshing: boolean; onRefresh: () => void;
  smcVisible: boolean; onToggleSmc: () => void;
  drawingCount: number; onClearDrawings: () => void;
}) {
  return (
    <div className="flex items-center gap-0.5 px-2 py-1 bg-[#131722] border-b border-[#1e222d]">
      {INTERVALS.map((tf) => (
        <button
          key={tf}
          onClick={() => onSelect(tf)}
          className={`px-3 py-1.5 rounded-md text-[11px] font-semibold transition-all duration-150 ${
            selected === tf
              ? 'bg-[#2962ff]/15 text-[#2962ff]'
              : 'text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#1e222d]'
          }`}
        >
          {tf}
        </button>
      ))}
      <div className="w-px h-4 bg-[#1e222d] mx-1.5" />
      <div className="flex-1" />
      {drawingCount > 0 && (
        <button
          onClick={onClearDrawings}
          className="p-1.5 rounded-md text-[11px] font-medium transition-all duration-150 flex items-center gap-1 bg-[#ef5350]/10 text-[#ef5350] hover:bg-[#ef5350]/20"
          title={`Clear all ${drawingCount} drawings`}
        >
          <Trash2 size={11} />
          <span className="hidden sm:inline">{drawingCount}</span>
        </button>
      )}
      <button
        onClick={onToggleSmc}
        className={`p-1.5 rounded-md text-[11px] font-medium transition-all duration-150 flex items-center gap-1 ${
          smcVisible
            ? 'bg-[#f0b90b]/12 text-[#f0b90b] hover:bg-[#f0b90b]/20'
            : 'text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#1e222d]'
        }`}
        title={smcVisible ? 'Ukryj SMC overlay' : 'Pokaż SMC overlay (FVG, OB, S/D, EQ)'}
      >
        <Layers size={11} />
        <span className="hidden sm:inline">SMC</span>
      </button>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="p-1.5 rounded-md text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#1e222d] transition-all duration-150 disabled:opacity-40"
        title="Refresh"
      >
        <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
      </button>
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN CHART COMPONENT                                                     */
/* ═══════════════════════════════════════════════════════════════════════════ */

export function CandlestickChart() {
  const toast = useToast();
  const { selectedInterval, setSelectedInterval } = useTradingStore();
  const { compute: computeIndicators } = useIndicatorWorker();

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

  // Magnetic snap and undo/redo state
  const [magneticMode, setMagneticMode] = useState(true);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  // Inline text input state
  const [textInput, setTextInput] = useState<{ x: number; y: number; point: { time: number; price: number } } | null>(null);
  const textInputRef = useRef<HTMLInputElement>(null);

  // State
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [legendData, setLegendData] = useState<LegendData | null>(null);
  const deferredLegend = useDeferredValue(legendData);
  const isFirstLoad = useRef(true);
  const rawCandlesRef = useRef<CandlestickData[]>([]);

  /* ── Create charts on mount ────────────────────────────────────────────── */
  useEffect(() => {
    if (!mainContainerRef.current || !rsiContainerRef.current) {return;}

    const commonLayout = {
      background: { color: COLORS.bg },
      textColor: COLORS.text,
      fontSize: 11,
      fontFamily: "'Trebuchet MS', 'Roboto', sans-serif",
    };

    const commonGrid = {
      vertLines: { color: COLORS.gridLines, style: 4 as const },
      horzLines: { color: COLORS.gridLines, style: 4 as const },
    };

    const commonTimeScale = {
      borderColor: COLORS.border,
      timeVisible: true,
      secondsVisible: false,
    };

    // ─── Main chart ───
    const mainChart = createChart(mainContainerRef.current, {
      autoSize: true,
      layout: commonLayout,
      grid: commonGrid,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#2a2e39' },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#2a2e39' },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.05, bottom: 0.18 },
        autoScale: true,
        entireTextOnly: true,
      },
      timeScale: { ...commonTimeScale, barSpacing: 7, minBarSpacing: 2 },
      handleScroll: { vertTouchDrag: false },
      watermark: {
        visible: true,
        text: 'XAU/USD',
        fontSize: 52,
        color: 'rgba(120, 123, 134, 0.06)',
        horzAlign: 'center',
        vertAlign: 'center',
      },
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
      autoSize: true,
      layout: commonLayout,
      grid: commonGrid,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#2a2e39' },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: '#2a2e39' },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.08, bottom: 0.08 },
        autoScale: true,
      },
      timeScale: { ...commonTimeScale, barSpacing: 7, minBarSpacing: 2, visible: false },
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
      if (isSyncing || !range) {return;}
      isSyncing = true;
      rsiChart.timeScale().setVisibleLogicalRange(range);
      isSyncing = false;
    });
    rsiChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (isSyncing || !range) {return;}
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
  }, []);

  /* ── InteractionManager for drawing tools ──────────────────────────────── */
  useEffect(() => {
    const chart = mainChartRef.current;
    const series = candleSeriesRef.current;
    const container = mainContainerRef.current;
    if (!chart || !series || !container) {return;}

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
    if (!selectedDrawingId) {return;}
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
    if (style.color) {setDrawColor(style.color);}
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

  const handleUndo = useCallback(() => {
    const prev = interactionRef.current?.undo();
    if (prev) {
      drawingsRef.current = prev;
      setDrawings(prev);
      drawingsOverlayRef.current?.setDrawings(prev);
      interactionRef.current?.setDrawings(prev);
      saveDrawings('XAU/USD', selectedInterval, prev);
      setCanUndo(true); // Will be rechecked
      setCanRedo(true);
    }
  }, [selectedInterval]);

  const handleRedo = useCallback(() => {
    const next = interactionRef.current?.redo();
    if (next) {
      drawingsRef.current = next;
      setDrawings(next);
      drawingsOverlayRef.current?.setDrawings(next);
      interactionRef.current?.setDrawings(next);
      saveDrawings('XAU/USD', selectedInterval, next);
      setCanUndo(true);
    }
  }, [selectedInterval]);

  const handleToggleMagnetic = useCallback(() => {
    const newMode = !magneticMode;
    setMagneticMode(newMode);
    interactionRef.current?.setMagneticMode(newMode);
  }, [magneticMode]);

  /* ── Data fetching ─────────────────────────────────────────────────────── */
  const fetchData = useCallback(async (signal?: AbortSignal) => {
    try {
      if (isFirstLoad.current) {setLoading(true);}
      else {setRefreshing(true);}
      setError(null);

      // ── Try IndexedDB cache first for instant render ──
      let rawCandles: Candle[] | null = null;
      if (isFirstLoad.current) {
        rawCandles = await getCachedCandles(selectedInterval);
      }

      // ── Fetch fresh data from API ──
      const freshCandles: Candle[] = await marketAPI.getCandles('XAU/USD', selectedInterval, 200);
      if (signal?.aborted) {return;}
      if (freshCandles?.length) {
        rawCandles = freshCandles;
        // Store to IndexedDB in background (non-blocking)
        void setCachedCandles(selectedInterval, freshCandles);
      }

      if (!rawCandles?.length) {throw new Error('No candle data');}

      // Sort ascending by time & deduplicate (lightweight-charts requires strictly ascending times)
      const candleData = rawCandles
        .map((c) => ({ ...c, _ts: Math.floor(new Date(c.timestamp).getTime() / 1000) }))
        .sort((a, b) => a._ts - b._ts)
        .filter((c, i, arr) => i === 0 || c._ts > arr[i - 1]._ts);

      const closes = candleData.map((c) => c.close);

      // ── Compute indicators off main thread via Web Worker ──
      let ema21: (number | null)[];
      let rsi14: (number | null)[];
      let bb: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] };
      try {
        const result = await computeIndicators(closes, { emaPeriod: 21, rsiPeriod: 14, bbPeriod: 20, bbMult: 2 });
        if (signal?.aborted) {return;}
        ema21 = result.ema;
        rsi14 = result.rsi;
        bb = result.bb;
      } catch (err) {
        // Worker superseded or crashed — skip this cycle
        if ((err as Error).message === 'superseded') {return;}
        throw err;
      }

      // ── Build series data ──
      const candleSd: CandlestickData[] = [];
      const volumeSd: HistogramData[] = [];
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

        if (ema21[i] !== null) {emaSd.push({ time: t, value: ema21[i]! });}
        if (rsi14[i] !== null) {rsiSd.push({ time: t, value: rsi14[i]! });}
        if (bb.upper[i] !== null) {bbUpperSd.push({ time: t, value: bb.upper[i]! });}
        if (bb.middle[i] !== null) {bbMiddleSd.push({ time: t, value: bb.middle[i]! });}
        if (bb.lower[i] !== null) {bbLowerSd.push({ time: t, value: bb.lower[i]! });}
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

      // ── Feed candle data to InteractionManager for magnetic snap ──
      interactionRef.current?.setCandleData(
        candleSd.map(c => ({ time: c.time as number, open: c.open, high: c.high, low: c.low, close: c.close }))
      );

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
        if (signal?.aborted) {return;}
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

      // ── Volume Profile price lines (POC / VAH / VAL) ──
      // Deferred by 3s to avoid simultaneous Twelve Data API credit usage
      // with candles (which already consumed 1 credit above).
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      void setTimeout(async () => {
        if (signal?.aborted) return;
        try {
          const vp = await marketAPI.getVolumeProfile('XAU/USD', selectedInterval, 100);
          if (!signal?.aborted && vp && candleSeriesRef.current) {
            const cs = candleSeriesRef.current;
            if (vp.poc) {
              signalPriceLinesRef.current.push(cs.createPriceLine({
                price: vp.poc, color: 'rgba(251,191,36,0.85)',
                lineWidth: 1, lineStyle: LineStyle.LargeDashed,
                axisLabelVisible: true, title: 'POC',
              }));
            }
            if (vp.vah && vp.vah !== vp.poc) {
              signalPriceLinesRef.current.push(cs.createPriceLine({
                price: vp.vah, color: 'rgba(251,191,36,0.45)',
                lineWidth: 1, lineStyle: LineStyle.Dotted,
                axisLabelVisible: true, title: 'VAH',
              }));
            }
            if (vp.val && vp.val !== vp.poc) {
              signalPriceLinesRef.current.push(cs.createPriceLine({
                price: vp.val, color: 'rgba(251,191,36,0.45)',
                lineWidth: 1, lineStyle: LineStyle.Dotted,
                axisLabelVisible: true, title: 'VAL',
              }));
            }
          }
        } catch {
          // VP is optional
        }
      }, isFirstLoad.current ? 3000 : 500);

      // ── Scroll to latest candle on first load (show last ~80 bars) ──
      if (isFirstLoad.current) {
        const totalBars = candleSd.length;
        const barsToShow = Math.min(80, totalBars);
        const range = { from: totalBars - barsToShow, to: totalBars + 5 };
        mainChartRef.current?.timeScale().setVisibleLogicalRange(range);
        rsiChartRef.current?.timeScale().setVisibleLogicalRange(range);
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
      if (isFirstLoad.current) {
        setError('Failed to load chart data');
        toast.error('Chart data unavailable');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedInterval, computeIndicators]);

  /* ── Fetch on mount + interval change + 30s auto-refresh ───────────────── */
  useEffect(() => {
    const controller = new AbortController();
    void fetchData(controller.signal);
    const timer = setInterval(() => void fetchData(controller.signal), 30_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [fetchData]);

  /* ── Toggle SMC overlay without refetching data ───────────────────────── */
  useEffect(() => {
    if (!smcOverlayRef.current || !rawCandlesRef.current.length) {return;}
    if (smcVisible) {
      const smcResult = detectAllSmcZones(
        rawCandlesRef.current as Array<{ time: number; open: number; high: number; low: number; close: number }>
      );
      smcOverlayRef.current.setZones(smcResult.zones);
    } else {
      smcOverlayRef.current.setZones([]);
    }
  }, [smcVisible]);


  /* ── Render ──────────────────────────────────────────────────────────── */
  return (
    <div className="flex flex-col h-full w-full">
      <IntervalToolbar
        selected={selectedInterval}
        onSelect={(v) => startTransition(() => setSelectedInterval(v))}
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
          hasSelection={Boolean(selectedDrawingId)}
          magneticMode={magneticMode}
          onToggleMagnetic={handleToggleMagnetic}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={canUndo}
          canRedo={canRedo}
        />

        <OHLCVLegend data={deferredLegend} interval={selectedInterval} />
        {refreshing && (
          <div className="absolute top-1 right-2 z-20 flex items-center gap-1 text-[10px] text-[#787b86]">
            <RefreshCw size={9} className="animate-spin" /> updating…
          </div>
        )}
        {/* Loading / error overlays – container always in DOM so refs attach on first render */}
        {loading && isFirstLoad.current && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#131722]/80 text-[#787b86] text-sm gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading chart…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#131722]/80 text-[#ef5350] text-xs gap-2">
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
              className="bg-[#2a2e39] border border-[#2962ff]/60 text-[#d1d4dc] text-xs px-2 py-1 rounded outline-none w-40 shadow-lg"
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
      <div className="relative shrink-0 border-t border-[#2a2e39]">
        <span className="absolute top-0.5 left-2 z-20 text-[10px] text-[#787b86] font-sans pointer-events-none">
          RSI(14)
        </span>
        <div ref={rsiContainerRef} className="w-full" style={{ height: 120 }} />
      </div>
    </div>
  );
}
