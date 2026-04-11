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
import { useTheme } from '../../hooks/useTheme';
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
import { RefreshCw, AlertCircle, Layers, Trash2, Clock, BarChart2, Maximize2, Minimize2, Camera, Bell, Calculator } from 'lucide-react';
import { get as idbGet, set as idbSet } from 'idb-keyval';
import { useTradingStore } from '../../store/tradingStore';
import { marketAPI, signalsAPI, analysisAPI } from '../../api/client';
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
import { SessionOverlay } from './SessionOverlay';
import { VolumeProfileOverlay } from './VolumeProfileOverlay';
import { useIndicatorWorker } from '../../hooks/useIndicatorWorker';
import { usePriceAlerts } from '../../hooks/usePriceAlerts';
import type { PriceAlert } from '../../hooks/usePriceAlerts';
import { useBrowserNotifications } from '../../hooks/useBrowserNotifications';
import { useSoundAlerts } from '../../hooks/useSoundAlerts';
import { useKeyboardShortcuts, SHORTCUT_LIST } from '../../hooks/useKeyboardShortcuts';
import { ChartContextMenu } from './ChartContextMenu';
import { AlertManager } from './AlertManager';
import { RiskCalculator } from '../dashboard/RiskCalculator';
import { useFullscreen } from '../../hooks/useFullscreen';

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

/** Convert any CSS color (including modern `rgb(R G B)`) to hex for lightweight-charts compatibility */
function cssColorToHex(raw: string, fallback: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return fallback;
  // Already hex
  if (trimmed.startsWith('#')) return trimmed;
  // Match rgb(R G B) or rgb(R, G, B)
  const m = trimmed.match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/);
  if (m) {
    const [, r, g, b] = m;
    return '#' + [r, g, b].map(c => Number(c).toString(16).padStart(2, '0')).join('');
  }
  return fallback;
}

function getChartColors() {
  const style = getComputedStyle(document.documentElement);
  const isLight = document.documentElement.classList.contains('light');
  const v = (prop: string, fb: string) => cssColorToHex(style.getPropertyValue(prop), fb);
  return {
    bg: v('--chart-bg', isLight ? '#ffffff' : '#0b0e14'),
    gridLines: v('--chart-grid', isLight ? '#e5e7eb' : '#1e293b'),
    text: v('--chart-text', isLight ? '#4b5563' : '#9ca3af'),
    crosshair: v('--chart-crosshair', isLight ? '#9ca3af' : '#6b7280'),
    border: v('--chart-border', isLight ? '#e5e7eb' : '#263244'),
    candleUp: isLight ? '#3b82f6' : '#5b8def',
    candleDown: isLight ? '#94a3b8' : '#6b7280',
    wickUp: isLight ? '#3b82f6' : '#5b8def',
    wickDown: isLight ? '#94a3b8' : '#6b7280',
    volumeUp: isLight ? 'rgba(59,130,246,0.22)' : 'rgba(91,141,239,0.25)',
    volumeDown: isLight ? 'rgba(148,163,184,0.18)' : 'rgba(107,114,128,0.20)',
    ema21: isLight ? '#d97706' : '#f0b90b',
    bbUpper: isLight ? 'rgba(37,99,235,0.35)' : 'rgba(33,150,243,0.45)',
    bbMiddle: isLight ? 'rgba(37,99,235,0.55)' : 'rgba(33,150,243,0.70)',
    bbLower: isLight ? 'rgba(37,99,235,0.35)' : 'rgba(33,150,243,0.45)',
    rsiLine: isLight ? '#7c3aed' : '#7e57c2',
    rsiOverbought: isLight ? 'rgba(220,38,38,0.30)' : 'rgba(239,83,80,0.35)',
    rsiOversold: isLight ? 'rgba(22,163,74,0.30)' : 'rgba(38,166,154,0.35)',
    priceLine: isLight ? '#334155' : '#d1d4dc',
    slLine: '#ef5350',
    tpLine: '#26a69a',
    entryLine: '#2196f3',
    eqLine: '#f0b90b',
  };
}

// Chart colors — re-computed on every access to pick up theme changes
function COLORS_FN() { return getChartColors(); }
// Initial snapshot for chart creation (before any theme toggle)
const COLORS = getChartColors();

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  OHLCV LEGEND (top-left overlay like TradingView)                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

interface LegendData {
  o: number; h: number; l: number; c: number; v: number; change: number;
  // Indicator values at crosshair position
  ema21?: number | null;
  bbUpper?: number | null;
  bbMiddle?: number | null;
  bbLower?: number | null;
  rsi?: number | null;
  macdVal?: number | null;
  macdSignal?: number | null;
  macdHist?: number | null;
  atr?: number | null;
  stochK?: number | null;
  stochD?: number | null;
}

/** Indicator value chip — colored, compact */
function IndVal({ label, value, color, decimals = 2 }: { label: string; value: number | null | undefined; color: string; decimals?: number }) {
  if (value === null || value === undefined) return null;
  return (
    <span className="inline-flex items-center gap-0.5">
      <span className="text-[var(--chart-text)] opacity-60">{label}</span>
      <span className={`font-mono ${color}`}>{value.toFixed(decimals)}</span>
    </span>
  );
}

const OHLCVLegend = memo(function OHLCVLegend({ data, interval, visibleIndicators }: {
  data: LegendData | null;
  interval: string;
  visibleIndicators: { rsi: boolean; macd: boolean; atr: boolean; stoch: boolean };
}) {
  if (!data) {return null;}
  const up = data.c >= data.o;
  const col = up ? 'text-[#5b8def]' : 'text-[#6b7280]';
  return (
    <div className="absolute top-1 left-12 z-20 font-sans pointer-events-none select-none space-y-0">
      {/* Row 1: OHLCV */}
      <div className="flex items-center gap-2 text-[11px]">
        <span className="text-[var(--color-text-primary)] font-semibold text-[12px]">XAU/USD</span>
        <span className="text-[var(--chart-text)]">·</span>
        <span className="text-[var(--chart-text)] font-medium">{interval}</span>
        <span className="text-[var(--chart-text)] ml-1">O</span><span className={col}>{data.o.toFixed(2)}</span>
        <span className="text-[var(--chart-text)]">H</span><span className={col}>{data.h.toFixed(2)}</span>
        <span className="text-[var(--chart-text)]">L</span><span className={col}>{data.l.toFixed(2)}</span>
        <span className="text-[var(--chart-text)]">C</span><span className={col}>{data.c.toFixed(2)}</span>
        <span className={`ml-1 ${col} font-medium`}>{data.change >= 0 ? '+' : ''}{data.change.toFixed(2)}%</span>
        {data.v > 0 && <span className="text-[var(--chart-text)] ml-1">Vol {data.v.toLocaleString()}</span>}
      </div>
      {/* Row 2: Overlay indicators (EMA + BB) */}
      <div className="flex items-center gap-3 text-[10px]">
        <IndVal label="EMA(21)" value={data.ema21} color="text-[#f0b90b]" />
        <IndVal label="BB▲" value={data.bbUpper} color="text-[#2196f3]" />
        <IndVal label="BB▬" value={data.bbMiddle} color="text-[#2196f3]" />
        <IndVal label="BB▼" value={data.bbLower} color="text-[#2196f3]" />
        {visibleIndicators.atr && <IndVal label="ATR(14)" value={data.atr} color="text-[#ff9800]" />}
      </div>
    </div>
  );
});

/** Sub-chart label with indicator value */
const SubChartLabel = memo(function SubChartLabel({ label, value, color, decimals = 1 }: {
  label: string; value: number | null | undefined; color: string; decimals?: number;
}) {
  return (
    <span className="absolute top-0.5 left-2 z-20 text-[10px] font-sans pointer-events-none flex items-center gap-1.5">
      <span className="text-[var(--chart-text)]">{label}</span>
      {value !== null && value !== undefined && (
        <span className={`font-mono font-medium ${color}`}>{value.toFixed(decimals)}</span>
      )}
    </span>
  );
});

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  INTERVAL TOOLBAR                                                         */
/* ═══════════════════════════════════════════════════════════════════════════ */

const INTERVALS = ['5m', '15m', '1h', '4h'] as const;

interface VisibleIndicators { rsi: boolean; macd: boolean; atr: boolean; stoch: boolean }

const INDICATOR_ITEMS: { key: keyof VisibleIndicators; label: string; color: string }[] = [
  { key: 'rsi',   label: 'RSI(14)',      color: '#7e57c2' },
  { key: 'macd',  label: 'MACD(12,26,9)', color: '#26a69a' },
  { key: 'atr',   label: 'ATR(14)',      color: '#ff9800' },
  { key: 'stoch', label: 'Stoch(14,3,3)', color: '#e91e63' },
];

const IntervalToolbar = memo(function IntervalToolbar({
  selected, onSelect, refreshing, onRefresh, smcVisible, onToggleSmc,
  sessionsVisible, onToggleSessions,
  drawingCount, onClearDrawings,
  visibleIndicators, onToggleIndicator,
  isFullscreen, onToggleFullscreen, onScreenshot,
  alertCount, onOpenAlerts,
}: {
  selected: string; onSelect: (v: string) => void; refreshing: boolean; onRefresh: () => void;
  smcVisible: boolean; onToggleSmc: () => void;
  sessionsVisible: boolean; onToggleSessions: () => void;
  drawingCount: number; onClearDrawings: () => void;
  visibleIndicators: VisibleIndicators; onToggleIndicator: (key: keyof VisibleIndicators) => void;
  isFullscreen: boolean; onToggleFullscreen: () => void;
  onScreenshot: () => void;
  alertCount: number; onOpenAlerts: () => void;
}) {
  const [showIndMenu, setShowIndMenu] = useState(false);
  const activeCount = Object.values(visibleIndicators).filter(Boolean).length;
  return (
    <div className="flex items-center gap-0.5 px-2 py-1 bg-[var(--chart-bg)] border-b border-[var(--chart-border)]">
      {INTERVALS.map((tf) => (
        <button
          key={tf}
          onClick={() => onSelect(tf)}
          className={`px-3 py-1.5 rounded-md text-[11px] font-semibold transition-all duration-150 ${
            selected === tf
              ? 'bg-[#2962ff]/15 text-[#2962ff]'
              : 'text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)]'
          }`}
        >
          {tf}
        </button>
      ))}
      <div className="w-px h-4 bg-[var(--color-secondary)] mx-1.5" />
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
            : 'text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)]'
        }`}
        title={smcVisible ? 'Ukryj SMC overlay' : 'Pokaż SMC overlay (FVG, OB, S/D, EQ)'}
      >
        <Layers size={11} />
        <span className="hidden sm:inline">SMC</span>
      </button>
      {/* Indicators dropdown */}
      <div className="relative">
        <button
          onClick={() => setShowIndMenu(v => !v)}
          className={`p-1.5 rounded-md text-[11px] font-medium transition-all duration-150 flex items-center gap-1 ${
            activeCount > 0
              ? 'bg-[#7e57c2]/12 text-[#7e57c2] hover:bg-[#7e57c2]/20'
              : 'text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)]'
          }`}
          title="Toggle indicators"
        >
          <BarChart2 size={11} />
          <span className="hidden sm:inline">Ind</span>
          {activeCount > 0 && <span className="text-[9px] opacity-75">({activeCount})</span>}
        </button>
        {showIndMenu && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setShowIndMenu(false)} />
            <div className="absolute top-full right-0 mt-1 z-40 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg shadow-xl py-1 min-w-[160px]">
              {INDICATOR_ITEMS.map(({ key, label, color }) => (
                <button
                  key={key}
                  onClick={() => onToggleIndicator(key)}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] hover:bg-[var(--color-secondary)] transition-colors"
                >
                  <div className="w-3 h-3 rounded border flex items-center justify-center"
                    style={{
                      borderColor: color,
                      backgroundColor: visibleIndicators[key] ? color + '30' : 'transparent',
                    }}>
                    {visibleIndicators[key] && <span style={{ color }} className="text-[9px] font-bold">✓</span>}
                  </div>
                  <span style={{ color: visibleIndicators[key] ? color : 'var(--chart-text)' }}>{label}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
      <button
        onClick={onToggleSessions}
        className={`p-1.5 rounded-md text-[11px] font-medium transition-all duration-150 flex items-center gap-1 ${
          sessionsVisible
            ? 'bg-[#3b82f6]/12 text-[#3b82f6] hover:bg-[#3b82f6]/20'
            : 'text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)]'
        }`}
        title={sessionsVisible ? 'Ukryj sesje' : 'Pokaz sesje (Asian/London/NY)'}
      >
        <Clock size={11} />
        <span className="hidden sm:inline">Sessions</span>
      </button>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        className="p-1.5 rounded-md text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)] transition-all duration-150 disabled:opacity-40"
        title="Refresh"
      >
        <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
      </button>
      <button
        onClick={onOpenAlerts}
        className={`p-1.5 rounded-md text-[11px] font-medium transition-all duration-150 flex items-center gap-1 ${
          alertCount > 0
            ? 'bg-[#f59e0b]/12 text-[#f59e0b] hover:bg-[#f59e0b]/20'
            : 'text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)]'
        }`}
        title="Zarzadzaj alertami cenowymi"
      >
        <Bell size={11} />
        {alertCount > 0 && <span className="text-[9px]">{alertCount}</span>}
      </button>
      <button
        onClick={onScreenshot}
        className="p-1.5 rounded-md text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)] transition-all duration-150"
        title="Zapisz wykres jako PNG"
      >
        <Camera size={12} />
      </button>
      <button
        onClick={onToggleFullscreen}
        className="p-1.5 rounded-md text-[var(--chart-text)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-secondary)] transition-all duration-150"
        title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
      >
        {isFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
      </button>
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN CHART COMPONENT                                                     */
/* ═══════════════════════════════════════════════════════════════════════════ */

export function CandlestickChart() {
  const toast = useToast();
  const { isDark, toggle: toggleTheme } = useTheme();
  const { selectedInterval, setSelectedInterval } = useTradingStore();
  const { compute: computeIndicators } = useIndicatorWorker();

  // Fullscreen
  const chartWrapperRef = useRef<HTMLDivElement>(null);
  const { isFullscreen, toggle: toggleFullscreen } = useFullscreen(chartWrapperRef);

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

  // MACD series refs
  const macdChartRef = useRef<IChartApi | null>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const macdLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<'Line'> | null>(null);
  const macdHistRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // ATR series ref (shown on main chart as overlay value, no sub-chart)
  // We store ATR data for legend display

  // Stochastic series refs
  const stochChartRef = useRef<IChartApi | null>(null);
  const stochContainerRef = useRef<HTMLDivElement>(null);
  const stochKRef = useRef<ISeriesApi<'Line'> | null>(null);
  const stochDRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Indicator data arrays (for crosshair legend lookup)
  const indicatorDataRef = useRef<{
    ema: (number | null)[];
    bbUpper: (number | null)[];
    bbMiddle: (number | null)[];
    bbLower: (number | null)[];
    rsi: (number | null)[];
    macd: (number | null)[];
    macdSignal: (number | null)[];
    macdHist: (number | null)[];
    atr: (number | null)[];
    stochK: (number | null)[];
    stochD: (number | null)[];
  }>({
    ema: [], bbUpper: [], bbMiddle: [], bbLower: [],
    rsi: [], macd: [], macdSignal: [], macdHist: [],
    atr: [], stochK: [], stochD: [],
  });

  // Visible sub-chart indicators
  const [visibleIndicators, setVisibleIndicators] = useState<VisibleIndicators>({
    rsi: true, macd: false, atr: false, stoch: false,
  });

  // Price alerts + browser notifications + sound
  const alertPriceLinesRef = useRef<Map<string, any>>(new Map());
  const [showAlertManager, setShowAlertManager] = useState(false);
  const [showRiskCalc, setShowRiskCalc] = useState(false);
  const { notifyPriceAlert } = useBrowserNotifications();
  const { chimeUp, chimeDown } = useSoundAlerts();
  const { alerts: allAlerts, activeAlerts, addAlert, removeAlert, clearTriggered } = usePriceAlerts(
    useCallback((alert: PriceAlert) => {
      toast.info(`Price alert: $${alert.price.toFixed(2)} (${alert.direction})`);
      notifyPriceAlert(alert.price, alert.direction);
      if (alert.direction === 'above') chimeUp(); else chimeDown();
    }, [toast, notifyPriceAlert, chimeUp, chimeDown])
  );

  // Track signal price lines so we can remove them before re-creating
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const signalPriceLinesRef = useRef<any[]>([]);

  // SMC overlay primitive
  const smcOverlayRef = useRef<SmcZonesOverlay | null>(null);
  const [smcVisible, setSmcVisible] = useState(true);

  // Session overlay
  const sessionOverlayRef = useRef<SessionOverlay | null>(null);

  // Volume Profile overlay
  const vpOverlayRef = useRef<VolumeProfileOverlay | null>(null);
  const [sessionsVisible, setSessionsVisible] = useState(true);

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

  // Help modal
  const [showHelp, setShowHelp] = useState(false);

  // Context menu
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; price: number | null } | null>(null);

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
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: COLORS.bg },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: COLORS.bg },
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
        vertLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: COLORS.bg },
        horzLine: { color: COLORS.crosshair, style: LineStyle.Dashed, width: 1, labelBackgroundColor: COLORS.bg },
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

    // ─── Attach session background overlay (below everything) ───
    const sessionOverlay = new SessionOverlay();
    candleSeries.attachPrimitive(sessionOverlay);
    sessionOverlayRef.current = sessionOverlay;

    // ─── Attach Volume Profile overlay ───
    const vpOverlay = new VolumeProfileOverlay();
    candleSeries.attachPrimitive(vpOverlay);
    vpOverlay.setSeries(candleSeries);
    vpOverlayRef.current = vpOverlay;

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

    // ─── OHLCV + Indicator Legend on crosshair ───
    mainChart.subscribeCrosshairMove((param: MouseEventParams) => {
      const buildLegend = (idx: number, cs: { open: number; high: number; low: number; close: number }, vol: number): LegendData => {
        const ind = indicatorDataRef.current;
        return {
          o: cs.open, h: cs.high, l: cs.low, c: cs.close,
          v: vol,
          change: ((cs.close - cs.open) / cs.open) * 100,
          ema21: ind.ema[idx] ?? null,
          bbUpper: ind.bbUpper[idx] ?? null,
          bbMiddle: ind.bbMiddle[idx] ?? null,
          bbLower: ind.bbLower[idx] ?? null,
          rsi: ind.rsi[idx] ?? null,
          macdVal: ind.macd[idx] ?? null,
          macdSignal: ind.macdSignal[idx] ?? null,
          macdHist: ind.macdHist[idx] ?? null,
          atr: ind.atr[idx] ?? null,
          stochK: ind.stochK[idx] ?? null,
          stochD: ind.stochD[idx] ?? null,
        };
      };

      if (!param.time) {
        const candles = rawCandlesRef.current;
        const last = candles[candles.length - 1];
        if (last) {
          setLegendData(buildLegend(candles.length - 1, last, 0));
        }
        return;
      }
      const cs = param.seriesData?.get(candleSeries) as CandlestickData | undefined;
      const vs = param.seriesData?.get(volumeSeries) as HistogramData | undefined;
      if (cs) {
        // Find index by matching timestamp
        const candles = rawCandlesRef.current;
        const t = cs.time as number;
        let idx = candles.length - 1;
        for (let i = candles.length - 1; i >= 0; i--) {
          if ((candles[i].time as number) === t) { idx = i; break; }
        }
        setLegendData(buildLegend(idx, cs, vs?.value ?? 0));
      }
    });

    return () => {
      // Detach overlays before removing chart
      try { candleSeries.detachPrimitive(vpOverlay); } catch { /* ok */ }
      try { candleSeries.detachPrimitive(sessionOverlay); } catch { /* ok */ }
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
      const highs = candleData.map((c) => c.high);
      const lows = candleData.map((c) => c.low);

      // ── Compute indicators off main thread via Web Worker ──
      let ema21: (number | null)[];
      let rsi14: (number | null)[];
      let bb: { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] };
      let macdData: { macd: (number | null)[]; signal: (number | null)[]; histogram: (number | null)[] };
      let atrData: (number | null)[];
      let stochData: { k: (number | null)[]; d: (number | null)[] };
      try {
        const result = await computeIndicators(closes, highs, lows, { emaPeriod: 21, rsiPeriod: 14, bbPeriod: 20, bbMult: 2 });
        if (signal?.aborted) {return;}
        ema21 = result.ema;
        rsi14 = result.rsi;
        bb = result.bb;
        macdData = result.macd;
        atrData = result.atr;
        stochData = result.stoch;
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
        const currentColors = COLORS_FN();
        volumeSd.push({ time: t, value: c.volume, color: up ? currentColors.volumeUp : currentColors.volumeDown });

        if (ema21[i] !== null) {emaSd.push({ time: t, value: ema21[i]! });}
        if (rsi14[i] !== null) {rsiSd.push({ time: t, value: rsi14[i]! });}
        if (bb.upper[i] !== null) {bbUpperSd.push({ time: t, value: bb.upper[i]! });}
        if (bb.middle[i] !== null) {bbMiddleSd.push({ time: t, value: bb.middle[i]! });}
        if (bb.lower[i] !== null) {bbLowerSd.push({ time: t, value: bb.lower[i]! });}
      }

      rawCandlesRef.current = candleSd;

      // ── Store indicator data for legend lookup ──
      indicatorDataRef.current = {
        ema: ema21,
        bbUpper: bb.upper,
        bbMiddle: bb.middle,
        bbLower: bb.lower,
        rsi: rsi14,
        macd: macdData.macd,
        macdSignal: macdData.signal,
        macdHist: macdData.histogram,
        atr: atrData,
        stochK: stochData.k,
        stochD: stochData.d,
      };

      // ── Build MACD series data ──
      const macdLineSd: LineData[] = [];
      const macdSignalSd: LineData[] = [];
      const macdHistSd: HistogramData[] = [];
      for (let i = 0; i < candleData.length; i++) {
        const t = candleData[i]._ts as UTCTimestamp;
        if (macdData.macd[i] !== null) macdLineSd.push({ time: t, value: macdData.macd[i]! });
        if (macdData.signal[i] !== null) macdSignalSd.push({ time: t, value: macdData.signal[i]! });
        if (macdData.histogram[i] !== null) {
          const v = macdData.histogram[i]!;
          macdHistSd.push({ time: t, value: v, color: v >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)' });
        }
      }

      // ── Build Stochastic series data ──
      const stochKSd: LineData[] = [];
      const stochDSd: LineData[] = [];
      for (let i = 0; i < candleData.length; i++) {
        const t = candleData[i]._ts as UTCTimestamp;
        if (stochData.k[i] !== null) stochKSd.push({ time: t, value: stochData.k[i]! });
        if (stochData.d[i] !== null) stochDSd.push({ time: t, value: stochData.d[i]! });
      }

      // ── Apply MACD data ──
      macdLineRef.current?.setData(macdLineSd);
      macdSignalRef.current?.setData(macdSignalSd);
      macdHistRef.current?.setData(macdHistSd);

      // ── Apply Stochastic data ──
      stochKRef.current?.setData(stochKSd);
      stochDRef.current?.setData(stochDSd);

      // ── Feed session overlay ──
      if (sessionOverlayRef.current) {
        sessionOverlayRef.current.setCandles(candleSd.map(c => c.time as number));
      }

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
            // Feed volume profile overlay with histogram data
            if (vpOverlayRef.current && vp.histogram?.length) {
              vpOverlayRef.current.setData(vp);
            }
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

      // ── Trade markers — snap to nearest candle for accurate placement ──
      try {
        const tradesResp = await analysisAPI.getRecentTrades(30);
        if (!signal?.aborted && tradesResp?.trades?.length && candleSeriesRef.current) {
          // Build set of valid candle times for snapping
          const candleTimes = candleSd.map(c => c.time as number);

          const snapToCandle = (tradeTime: number): number => {
            let best = candleTimes[0];
            let bestDist = Math.abs(tradeTime - best);
            for (const ct of candleTimes) {
              const dist = Math.abs(tradeTime - ct);
              if (dist < bestDist) { best = ct; bestDist = dist; }
            }
            return best;
          };

          const markers = tradesResp.trades
            .filter((t: any) => t.timestamp && t.direction && (t.result?.includes('WIN') || t.result?.includes('LOSS')))
            .map((t: any) => {
              let ts = t.timestamp.trim();
              ts = ts.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/, '$1T$2');
              if (!/[Zz+-]/.test(ts.slice(-6))) ts += 'Z';
              const rawTime = Math.floor(new Date(ts).getTime() / 1000);
              const time = snapToCandle(rawTime) as UTCTimestamp;
              const isWin = t.result?.includes('WIN');
              const isLong = t.direction === 'LONG';
              return {
                time,
                position: isLong ? 'belowBar' as const : 'aboveBar' as const,
                color: isWin ? '#22c55e' : '#ef4444',
                shape: isLong ? 'arrowUp' as const : 'arrowDown' as const,
                text: isWin ? 'W' : 'L',
              };
            })
            .sort((a: any, b: any) => (a.time as number) - (b.time as number));
          if (markers.length) candleSeriesRef.current.setMarkers(markers);
        }
      } catch { /* trade markers are optional */ }

      // ── Scroll to latest candle on first load (show last ~80 bars) ──
      if (isFirstLoad.current) {
        const totalBars = candleSd.length;
        const barsToShow = Math.min(80, totalBars);
        const range = { from: totalBars - barsToShow, to: totalBars + 5 };
        mainChartRef.current?.timeScale().setVisibleLogicalRange(range);
        rsiChartRef.current?.timeScale().setVisibleLogicalRange(range);
      }

      // ── Set last candle as legend (with indicator values) ──
      const lastIdx = candleSd.length - 1;
      const last = candleSd[lastIdx];
      if (last) {
        const ind = indicatorDataRef.current;
        setLegendData({
          o: last.open, h: last.high, l: last.low, c: last.close,
          v: volumeSd[volumeSd.length - 1]?.value ?? 0,
          change: ((last.close - last.open) / last.open) * 100,
          ema21: ind.ema[lastIdx],
          bbUpper: ind.bbUpper[lastIdx],
          bbMiddle: ind.bbMiddle[lastIdx],
          bbLower: ind.bbLower[lastIdx],
          rsi: ind.rsi[lastIdx],
          macdVal: ind.macd[lastIdx],
          macdSignal: ind.macdSignal[lastIdx],
          macdHist: ind.macdHist[lastIdx],
          atr: ind.atr[lastIdx],
          stochK: ind.stochK[lastIdx],
          stochD: ind.stochD[lastIdx],
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

  /* ── Update chart colors on theme change ──────────────────────────────── */
  useEffect(() => {
    if (!mainChartRef.current || !rsiChartRef.current) return;
    // Small delay to let CSS variables settle after class toggle
    const timer = setTimeout(() => {
      const c = getChartColors();
      const layout = { background: { color: c.bg }, textColor: c.text };
      const grid = {
        vertLines: { color: c.gridLines, style: 4 as const },
        horzLines: { color: c.gridLines, style: 4 as const },
      };
      const crosshair = {
        vertLine: { color: c.crosshair, labelBackgroundColor: c.bg },
        horzLine: { color: c.crosshair, labelBackgroundColor: c.bg },
      };
      mainChartRef.current?.applyOptions({ layout, grid, crosshair, rightPriceScale: { borderColor: c.border }, timeScale: { borderColor: c.border } });
      rsiChartRef.current?.applyOptions({ layout, grid, crosshair, rightPriceScale: { borderColor: c.border }, timeScale: { borderColor: c.border } });

      // Update candlestick colors
      candleSeriesRef.current?.applyOptions({
        upColor: c.candleUp, downColor: c.candleDown,
        wickUpColor: c.wickUp, wickDownColor: c.wickDown,
      });

      // Update EMA + indicator line colors
      emaSeriesRef.current?.applyOptions({ color: c.ema21 });
      bbUpperRef.current?.applyOptions({ color: c.bbUpper });
      bbMiddleRef.current?.applyOptions({ color: c.bbMiddle });
      bbLowerRef.current?.applyOptions({ color: c.bbLower });
      rsiSeriesRef.current?.applyOptions({ color: c.rsiLine });

      // Rebuild session overlay with theme-adjusted opacity
      if (sessionOverlayRef.current && rawCandlesRef.current.length) {
        sessionOverlayRef.current.rebuild(rawCandlesRef.current.map(candle => candle.time as number));
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [isDark]);

  /* ── Price alert lines — sync with activeAlerts ──────────────────────── */
  useEffect(() => {
    const cs = candleSeriesRef.current;
    if (!cs) return;

    // Remove old alert lines that are no longer active
    for (const [id, pl] of alertPriceLinesRef.current) {
      if (!activeAlerts.find(a => a.id === id)) {
        try { cs.removePriceLine(pl); } catch { /* ok */ }
        alertPriceLinesRef.current.delete(id);
      }
    }

    // Add new alert lines
    for (const alert of activeAlerts) {
      if (!alertPriceLinesRef.current.has(alert.id)) {
        const pl = cs.createPriceLine({
          price: alert.price,
          color: alert.direction === 'above' ? '#26a69a' : '#ef5350',
          lineWidth: 1,
          lineStyle: LineStyle.SparseDotted,
          axisLabelVisible: true,
          title: `⏰ ${alert.direction === 'above' ? '▲' : '▼'}`,
        });
        alertPriceLinesRef.current.set(alert.id, pl);
      }
    }
  }, [activeAlerts]);

  /* ── Alt+Click on chart = create price alert ────────────────────────── */
  useEffect(() => {
    const container = mainContainerRef.current;
    const chart = mainChartRef.current;
    const series = candleSeriesRef.current;
    if (!container || !chart || !series) return;

    const handler = (e: MouseEvent) => {
      if (!e.altKey) return;
      // Get price at click position
      const rect = container.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const price = series.coordinateToPrice(y);
      if (price === null) return;

      const currentPrice = rawCandlesRef.current[rawCandlesRef.current.length - 1]?.close;
      if (!currentPrice) return;

      const priceNum = price as number;
      const alert = addAlert(priceNum, currentPrice);
      toast.success(`Alert set: $${priceNum.toFixed(2)} (${alert.direction})`);
    };

    container.addEventListener('click', handler);
    return () => container.removeEventListener('click', handler);
  }, [addAlert, toast]);

  /* ── Create/destroy MACD sub-chart when toggled ──────────────────────── */
  useEffect(() => {
    if (!visibleIndicators.macd || !macdContainerRef.current) {
      if (macdChartRef.current) { macdChartRef.current.remove(); macdChartRef.current = null; }
      return;
    }
    const c = COLORS_FN();
    const chart = createChart(macdContainerRef.current, {
      autoSize: true,
      layout: { background: { color: c.bg }, textColor: c.text, fontSize: 10, fontFamily: "'Trebuchet MS', sans-serif" },
      grid: { vertLines: { color: c.gridLines, style: 4 as const }, horzLines: { color: c.gridLines, style: 4 as const } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: c.crosshair, style: LineStyle.Dashed, width: 1 }, horzLine: { color: c.crosshair, style: LineStyle.Dashed, width: 1 } },
      rightPriceScale: { borderColor: c.border, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: c.border, timeVisible: true, visible: false, barSpacing: 7, minBarSpacing: 2 },
      handleScroll: { vertTouchDrag: false },
    });
    macdChartRef.current = chart;

    const macdLine = chart.addLineSeries({ color: '#26a69a', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false });
    const signalLine = chart.addLineSeries({ color: '#ef5350', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false });
    const histSeries = chart.addHistogramSeries({ priceFormat: { type: 'price', precision: 2, minMove: 0.01 }, priceLineVisible: false, lastValueVisible: false });
    macdLineRef.current = macdLine;
    macdSignalRef.current = signalLine;
    macdHistRef.current = histSeries;

    // Zero line
    macdLine.createPriceLine({ price: 0, color: 'rgba(107,114,128,0.25)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' });

    // Sync with main chart timescale
    let syncing = false;
    const mainTs = mainChartRef.current?.timeScale();
    if (mainTs) {
      mainTs.subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        chart.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      });
    }

    // Feed existing data
    void fetchData();

    return () => { chart.remove(); macdChartRef.current = null; macdLineRef.current = null; macdSignalRef.current = null; macdHistRef.current = null; };
  }, [visibleIndicators.macd]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Create/destroy Stochastic sub-chart when toggled ───────────────── */
  useEffect(() => {
    if (!visibleIndicators.stoch || !stochContainerRef.current) {
      if (stochChartRef.current) { stochChartRef.current.remove(); stochChartRef.current = null; }
      return;
    }
    const c = COLORS_FN();
    const chart = createChart(stochContainerRef.current, {
      autoSize: true,
      layout: { background: { color: c.bg }, textColor: c.text, fontSize: 10, fontFamily: "'Trebuchet MS', sans-serif" },
      grid: { vertLines: { color: c.gridLines, style: 4 as const }, horzLines: { color: c.gridLines, style: 4 as const } },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { color: c.crosshair, style: LineStyle.Dashed, width: 1 }, horzLine: { color: c.crosshair, style: LineStyle.Dashed, width: 1 } },
      rightPriceScale: { borderColor: c.border, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: c.border, timeVisible: true, visible: false, barSpacing: 7, minBarSpacing: 2 },
      handleScroll: { vertTouchDrag: false },
    });
    stochChartRef.current = chart;

    const kLine = chart.addLineSeries({ color: '#e91e63', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false });
    const dLine = chart.addLineSeries({ color: '#ff9800', lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false });
    stochKRef.current = kLine;
    stochDRef.current = dLine;

    // Reference lines
    kLine.createPriceLine({ price: 80, color: 'rgba(239,83,80,0.30)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
    kLine.createPriceLine({ price: 20, color: 'rgba(38,166,154,0.30)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' });
    kLine.createPriceLine({ price: 50, color: 'rgba(107,114,128,0.20)', lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false, title: '' });

    // Sync timescale
    let syncing = false;
    const mainTs = mainChartRef.current?.timeScale();
    if (mainTs) {
      mainTs.subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        chart.timeScale().setVisibleLogicalRange(range);
        syncing = false;
      });
    }

    void fetchData();

    return () => { chart.remove(); stochChartRef.current = null; stochKRef.current = null; stochDRef.current = null; };
  }, [visibleIndicators.stoch]); // eslint-disable-line react-hooks/exhaustive-deps

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


  /* ── Right-click context menu ─────────────────────────────────────────── */
  useEffect(() => {
    const container = mainContainerRef.current;
    const series = candleSeriesRef.current;
    if (!container || !series) return;

    const handler = (e: MouseEvent) => {
      e.preventDefault();
      const rect = container.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const price = series.coordinateToPrice(y) as number | null;
      setContextMenu({ x: e.clientX, y: e.clientY, price });
    };

    container.addEventListener('contextmenu', handler);
    return () => container.removeEventListener('contextmenu', handler);
  }, []);

  /* ── Chart screenshot ────────────────────────────────────────────────── */
  const handleScreenshot = useCallback(() => {
    const chart = mainChartRef.current;
    if (!chart) return;
    try {
      const canvas = chart.takeScreenshot();
      canvas.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `qs-chart-${selectedInterval}-${new Date().toISOString().slice(0, 16).replace(':', '')}.png`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast.success('Screenshot saved');
      });
    } catch {
      toast.error('Screenshot failed');
    }
  }, [selectedInterval, toast]);

  /* ── Global keyboard shortcuts ────────────────────────────────────────── */
  useKeyboardShortcuts({
    onToggleTheme: toggleTheme,
    onSelectInterval: (interval) => startTransition(() => setSelectedInterval(interval)),
    onToggleDrawing: () => setActiveTool(prev => prev === 'cursor' ? 'trendline' : 'cursor'),
    onEscDrawing: () => { setActiveTool('cursor'); setShowHelp(false); },
    onToggleSmc: () => setSmcVisible(v => !v),
    onToggleSessions: () => {
      setSessionsVisible(v => {
        const next = !v;
        if (sessionOverlayRef.current) {
          sessionOverlayRef.current.setVisible(next);
          if (next && rawCandlesRef.current.length) {
            sessionOverlayRef.current.rebuild(rawCandlesRef.current.map(c => c.time as number));
          }
        }
        return next;
      });
    },
    onToggleHelp: () => setShowHelp(v => !v),
  });

  /* ── Render ──────────────────────────────────────────────────────────── */
  return (
    <div ref={chartWrapperRef} className="flex flex-col h-full w-full bg-[var(--chart-bg)]">
      <IntervalToolbar
        selected={selectedInterval}
        onSelect={(v) => startTransition(() => setSelectedInterval(v))}
        refreshing={refreshing}
        onRefresh={() => void fetchData()}
        smcVisible={smcVisible}
        onToggleSmc={() => setSmcVisible(v => !v)}
        sessionsVisible={sessionsVisible}
        onToggleSessions={() => {
          const next = !sessionsVisible;
          setSessionsVisible(next);
          if (sessionOverlayRef.current) {
            sessionOverlayRef.current.setVisible(next);
            if (next && rawCandlesRef.current.length) {
              sessionOverlayRef.current.rebuild(rawCandlesRef.current.map(c => c.time as number));
            }
          }
        }}
        drawingCount={drawings.length}
        onClearDrawings={handleClearAll}
        visibleIndicators={visibleIndicators}
        onToggleIndicator={(key) => setVisibleIndicators(prev => ({ ...prev, [key]: !prev[key] }))}
        isFullscreen={isFullscreen}
        onToggleFullscreen={toggleFullscreen}
        onScreenshot={handleScreenshot}
        alertCount={activeAlerts.length}
        onOpenAlerts={() => setShowAlertManager(true)}
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

        <OHLCVLegend data={deferredLegend} interval={selectedInterval} visibleIndicators={visibleIndicators} />
        {/* Risk calculator floating button */}
        <button
          onClick={() => setShowRiskCalc(true)}
          className="absolute top-1 right-24 z-20 p-1.5 rounded-md text-[var(--chart-text)] hover:text-accent-blue hover:bg-[var(--color-secondary)] transition-all"
          title="Kalkulator ryzyka (position size)"
        >
          <Calculator size={12} />
        </button>
        {refreshing && (
          <div className="absolute top-1 right-2 z-20 flex items-center gap-1 text-[10px] text-[var(--chart-text)]">
            <RefreshCw size={9} className="animate-spin" /> updating…
          </div>
        )}
        {/* Loading / error overlays – container always in DOM so refs attach on first render */}
        {loading && isFirstLoad.current && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[var(--chart-bg)]/80 text-[var(--chart-text)] text-sm gap-2">
            <RefreshCw size={14} className="animate-spin" />
            Loading chart…
          </div>
        )}
        {error && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-[var(--chart-bg)]/80 text-[#ef5350] text-xs gap-2">
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
              className="bg-[var(--color-secondary)] border border-[#2962ff]/60 text-[var(--color-text-primary)] text-xs px-2 py-1 rounded outline-none w-40 shadow-lg"
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

      {/* RSI sub-chart — always in DOM for ref stability, hidden via style */}
      <div className={`relative shrink-0 border-t border-[var(--chart-border)] ${visibleIndicators.rsi ? '' : 'hidden'}`}>
        <SubChartLabel label="RSI(14)" value={deferredLegend?.rsi} color="text-[#7e57c2]" />
        <div ref={rsiContainerRef} className="w-full" style={{ height: 100 }} />
      </div>

      {/* MACD sub-chart */}
      {visibleIndicators.macd && (
        <div className="relative shrink-0 border-t border-[var(--chart-border)]">
          <span className="absolute top-0.5 left-2 z-20 text-[10px] font-sans pointer-events-none flex items-center gap-2">
            <span className="text-[var(--chart-text)]">MACD(12,26,9)</span>
            <IndVal label="M" value={deferredLegend?.macdVal} color="text-[#26a69a]" decimals={2} />
            <IndVal label="S" value={deferredLegend?.macdSignal} color="text-[#ef5350]" decimals={2} />
            <IndVal label="H" value={deferredLegend?.macdHist} color={
              (deferredLegend?.macdHist ?? 0) >= 0 ? 'text-[#26a69a]' : 'text-[#ef5350]'
            } decimals={2} />
          </span>
          <div ref={macdContainerRef} className="w-full" style={{ height: 100 }} />
        </div>
      )}

      {/* Stochastic sub-chart */}
      {visibleIndicators.stoch && (
        <div className="relative shrink-0 border-t border-[var(--chart-border)]">
          <span className="absolute top-0.5 left-2 z-20 text-[10px] font-sans pointer-events-none flex items-center gap-2">
            <span className="text-[var(--chart-text)]">Stoch(14,3,3)</span>
            <IndVal label="%K" value={deferredLegend?.stochK} color="text-[#e91e63]" decimals={1} />
            <IndVal label="%D" value={deferredLegend?.stochD} color="text-[#ff9800]" decimals={1} />
          </span>
          <div ref={stochContainerRef} className="w-full" style={{ height: 100 }} />
        </div>
      )}

      {/* Right-click context menu */}
      {contextMenu && (
        <ChartContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          price={contextMenu.price}
          onClose={() => setContextMenu(null)}
          onSetAlert={(price) => {
            const current = rawCandlesRef.current[rawCandlesRef.current.length - 1]?.close;
            if (current) {
              const alert = addAlert(price, current);
              toast.success(`Alert: $${price.toFixed(2)} (${alert.direction})`);
            }
          }}
          onCopyPrice={(price) => {
            void navigator.clipboard.writeText(price.toFixed(2));
            toast.success('Cena skopiowana');
          }}
          onScreenshot={handleScreenshot}
          onToggleSmc={() => setSmcVisible(v => !v)}
          onToggleSessions={() => {
            setSessionsVisible(v => {
              const next = !v;
              if (sessionOverlayRef.current) {
                sessionOverlayRef.current.setVisible(next);
                if (next && rawCandlesRef.current.length) {
                  sessionOverlayRef.current.rebuild(rawCandlesRef.current.map(c => c.time as number));
                }
              }
              return next;
            });
          }}
        />
      )}

      {/* Risk calculator */}
      {showRiskCalc && (
        <RiskCalculator onClose={() => setShowRiskCalc(false)} />
      )}

      {/* Alert manager */}
      {showAlertManager && (
        <AlertManager
          alerts={allAlerts}
          onRemove={removeAlert}
          onClearTriggered={clearTriggered}
          onClose={() => setShowAlertManager(false)}
        />
      )}

      {/* Keyboard shortcuts help modal */}
      {showHelp && (
        <>
          <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm" onClick={() => setShowHelp(false)} />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl shadow-2xl p-5 w-80">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold" style={{ color: 'var(--color-text-primary)' }}>Keyboard Shortcuts</h3>
              <button onClick={() => setShowHelp(false)} className="text-xs text-[var(--chart-text)] hover:text-[var(--color-text-primary)]">Esc</button>
            </div>
            <div className="space-y-1.5">
              {SHORTCUT_LIST.map(({ key, description }) => (
                <div key={key} className="flex items-center justify-between text-xs">
                  <span className="text-[var(--chart-text)]">{description}</span>
                  <kbd className="px-1.5 py-0.5 rounded bg-[var(--color-secondary)] text-[var(--color-text-primary)] font-mono text-[10px] font-medium border border-[var(--color-border)]">
                    {key}
                  </kbd>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
