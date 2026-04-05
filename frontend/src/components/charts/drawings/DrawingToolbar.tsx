/**
 * drawings/DrawingToolbar.tsx — Professional vertical toolbar for drawing tools.
 *
 * Custom SVG icons designed for maximum visual clarity.
 * Hover tooltip explains each tool with name + description.
 * Grouped by function: Lines, Shapes, Annotate, Position.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { Trash2 } from 'lucide-react';
import type { DrawingTool, DrawingStyle } from './types';

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  CUSTOM SVG TOOL ICONS — 16×16, stroke/fill use currentColor             */
/* ═══════════════════════════════════════════════════════════════════════════ */

const S = 16; // icon size

const ICONS: Record<DrawingTool, React.ReactNode> = {
  /* ── Pointer ── */
  cursor: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="currentColor">
      <path d="M4 1.5v12l3-3.5 2.2 4.5 1.6-.8-2.2-4.5H13L4 1.5z" />
    </svg>
  ),
  /* ── Diagonal line with two endpoint dots ── */
  trendline: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="2.5" y1="13" x2="13.5" y2="3" />
      <circle cx="2.5" cy="13" r="2" fill="currentColor" fillOpacity="0.35" stroke="none" />
      <circle cx="13.5" cy="3" r="2" fill="currentColor" fillOpacity="0.35" stroke="none" />
    </svg>
  ),
  /* ── Line from dot → arrowhead extends right ── */
  ray: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="2.5" y1="12" x2="11" y2="5" />
      <circle cx="2.5" cy="12" r="2" fill="currentColor" fillOpacity="0.35" stroke="none" />
      <polyline points="9,3 13.5,4 11,7.5" fill="none" strokeWidth="1.3" />
    </svg>
  ),
  /* ── Dashed diagonal line extending both ways, two dots ── */
  extendedline: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="0.5" y1="13" x2="15.5" y2="3" strokeDasharray="3 2" />
      <circle cx="5" cy="10.4" r="1.8" fill="currentColor" fillOpacity="0.4" stroke="none" />
      <circle cx="11" cy="5.6" r="1.8" fill="currentColor" fillOpacity="0.4" stroke="none" />
    </svg>
  ),
  /* ── Horizontal line with price tag box ── */
  hline: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="0.5" y1="8" x2="15.5" y2="8" />
      <rect x="9" y="4.5" width="6" height="7" rx="1.5" fill="currentColor" fillOpacity="0.12" strokeWidth="0.8" />
    </svg>
  ),
  /* ── Vertical line with time tag box ── */
  vline: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <line x1="8" y1="0.5" x2="8" y2="15.5" />
      <rect x="4.5" y="0.5" width="7" height="4.5" rx="1.5" fill="currentColor" fillOpacity="0.12" strokeWidth="0.8" />
    </svg>
  ),
  /* ── Two parallel diagonal lines with fill between + dashed midline ── */
  channel: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
      <path d="M1 10 L15 4 L15 8 L1 14Z" fill="currentColor" fillOpacity="0.1" stroke="none" />
      <line x1="1" y1="10" x2="15" y2="4" />
      <line x1="1" y1="14" x2="15" y2="8" />
      <line x1="1" y1="12" x2="15" y2="6" strokeWidth="0.7" strokeDasharray="2 2" opacity="0.5" />
    </svg>
  ),
  /* ── Stacked horizontal lines at fibonacci-like spacing ── */
  fib: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round">
      <line x1="1.5" y1="2" x2="14.5" y2="2" strokeWidth="1.2" opacity="0.9" />
      <line x1="1.5" y1="5.5" x2="14.5" y2="5.5" strokeWidth="0.9" opacity="0.65" />
      <line x1="1.5" y1="8" x2="14.5" y2="8" strokeWidth="0.9" opacity="0.5" />
      <line x1="1.5" y1="10" x2="14.5" y2="10" strokeWidth="0.9" opacity="0.4" />
      <line x1="1.5" y1="14" x2="14.5" y2="14" strokeWidth="1.2" opacity="0.9" />
    </svg>
  ),
  /* ── Rectangle outline with slight fill ── */
  rect: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="currentColor" fillOpacity="0.1" stroke="currentColor" strokeWidth="1.3">
      <rect x="2" y="3" width="12" height="10" rx="1" />
    </svg>
  ),
  /* ── Smooth wavy freehand line ── */
  path: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M2 12 Q5 3, 8 8 T 14 4" />
    </svg>
  ),
  /* ── T letter representing text tool ── */
  text: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="currentColor">
      <rect x="2" y="2" width="12" height="2.8" rx="0.5" fillOpacity="0.4" />
      <rect x="6.6" y="2" width="2.8" height="12" rx="0.5" fillOpacity="0.6" />
    </svg>
  ),
  /* ── Vertical double-arrow bracket for measuring ── */
  measure: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <line x1="8" y1="2.5" x2="8" y2="13.5" />
      <polyline points="5.5,5 8,1.5 10.5,5" />
      <polyline points="5.5,11 8,14.5 10.5,11" />
      <line x1="3" y1="2" x2="5.5" y2="2" />
      <line x1="3" y1="14" x2="5.5" y2="14" />
    </svg>
  ),
  /* ── Green upward arrow ── */
  longposition: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none">
      <path d="M8 1.5L13 7.5H10V14.5H6V7.5H3Z" fill="#22c55e" fillOpacity="0.6" stroke="#22c55e" strokeWidth="1" strokeLinejoin="round" />
    </svg>
  ),
  /* ── Red downward arrow ── */
  shortposition: (
    <svg width={S} height={S} viewBox="0 0 16 16" fill="none">
      <path d="M8 14.5L13 8.5H10V1.5H6V8.5H3Z" fill="#ef4444" fillOpacity="0.6" stroke="#ef4444" strokeWidth="1" strokeLinejoin="round" />
    </svg>
  ),
};

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  TOOL DEFINITIONS (labels, descriptions, groups)                          */
/* ═══════════════════════════════════════════════════════════════════════════ */

interface ToolDef {
  tool: DrawingTool;
  label: string;
  desc: string;
  group: string;
}

const TOOLS: ToolDef[] = [
  { tool: 'cursor',        label: 'Pointer',           desc: 'Select, move and edit drawings',          group: 'select' },
  { tool: 'trendline',     label: 'Trend Line',        desc: 'Straight line between two points',        group: 'lines' },
  { tool: 'ray',           label: 'Ray',               desc: 'Line extending infinitely to the right',  group: 'lines' },
  { tool: 'extendedline',  label: 'Extended Line',     desc: 'Line extending in both directions',       group: 'lines' },
  { tool: 'hline',         label: 'Horizontal Line',   desc: 'Horizontal line at a price level',        group: 'lines' },
  { tool: 'vline',         label: 'Vertical Line',     desc: 'Vertical line at a specific time',        group: 'lines' },
  { tool: 'channel',       label: 'Parallel Channel',  desc: 'Two parallel trend lines (3 clicks)',     group: 'shapes' },
  { tool: 'fib',           label: 'Fib Retracement',   desc: 'Fibonacci retracement levels',            group: 'shapes' },
  { tool: 'rect',          label: 'Rectangle',         desc: 'Rectangular zone / highlight area',       group: 'shapes' },
  { tool: 'path',          label: 'Brush',             desc: 'Freehand drawing (click + drag)',         group: 'annotate' },
  { tool: 'text',          label: 'Text',              desc: 'Place a text label on the chart',         group: 'annotate' },
  { tool: 'measure',       label: 'Measure',           desc: 'Measure price distance and % change',     group: 'tools' },
  { tool: 'longposition',  label: 'Long Position',     desc: 'Entry → TP (up) + auto SL zone',         group: 'position' },
  { tool: 'shortposition', label: 'Short Position',    desc: 'Entry → TP (down) + auto SL zone',       group: 'position' },
];

const GROUP_LABELS: Record<string, string> = {
  select: '',
  lines: 'LINES',
  shapes: 'SHAPES',
  annotate: 'DRAW',
  tools: 'TOOLS',
  position: 'TRADE',
};

const COLORS = [
  '#3b82f6', '#22c55e', '#ef4444', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#e2e8f0', '#6b7280',
];

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN COMPONENT                                                           */
/* ═══════════════════════════════════════════════════════════════════════════ */

interface DrawingToolbarProps {
  activeTool: DrawingTool;
  onSelectTool: (tool: DrawingTool) => void;
  onStyleChange: (style: Partial<DrawingStyle>) => void;
  currentColor: string;
  onDeleteSelected: () => void;
  onClearAll: () => void;
  hasSelection: boolean;
  magneticMode?: boolean;
  onToggleMagnetic?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
}

export function DrawingToolbar({
  activeTool, onSelectTool, onStyleChange, currentColor,
  onDeleteSelected, onClearAll, hasSelection,
  magneticMode = true, onToggleMagnetic, onUndo, onRedo,
  canUndo = false, canRedo = false,
}: DrawingToolbarProps) {
  const [showColors, setShowColors] = useState(false);
  const [showWidths, setShowWidths] = useState(false);
  const [hoveredTool, setHoveredTool] = useState<string | null>(null);
  const [currentWidth, setCurrentWidth] = useState(2);

  const hoverTimer = useRef<ReturnType<typeof setTimeout>>();
  const colorRef = useRef<HTMLDivElement>(null);
  const widthRef = useRef<HTMLDivElement>(null);

  // Close popups on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (colorRef.current && !colorRef.current.contains(e.target as Node)) {setShowColors(false);}
      if (widthRef.current && !widthRef.current.contains(e.target as Node)) {setShowWidths(false);}
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Cleanup hover timer
  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  const startHover = useCallback((id: string) => {
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => setHoveredTool(id), 420);
  }, []);

  const endHover = useCallback(() => {
    clearTimeout(hoverTimer.current);
    setHoveredTool(null);
  }, []);

  const pickColor = useCallback((c: string) => {
    const hex = c.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    onStyleChange({ color: c, fillColor: `rgba(${r},${g},${b},0.12)` });
    setShowColors(false);
  }, [onStyleChange]);

  return (
    <div
      className="absolute left-0 top-0 bottom-0 z-30 flex flex-col items-center bg-[#131722] border-r border-[#2a2e39] py-1.5 gap-0.5 overflow-y-auto select-none"
      style={{ width: 42 }}
    >
      {TOOLS.map((t, i) => {
        const isActive = activeTool === t.tool;
        const prevGroup = i > 0 ? TOOLS[i - 1].group : null;
        const showSep = prevGroup !== null && prevGroup !== t.group;
        const groupLabel = showSep ? GROUP_LABELS[t.group] : null;

        return (
          <div key={t.tool} className="w-full flex flex-col items-center">
            {/* Group separator with optional label */}
            {showSep && (
              <div className="flex items-center gap-0.5 w-[34px] my-1">
                <div className="flex-1 h-px bg-[#2a2e39]" />
                {groupLabel && (
                  <span className="text-[6px] text-[#787b86] font-bold tracking-[0.1em] leading-none">{groupLabel}</span>
                )}
                <div className="flex-1 h-px bg-[#2a2e39]" />
              </div>
            )}

            {/* Tool button with tooltip */}
            <div className="relative">
              <button
                onClick={() => onSelectTool(isActive && t.tool !== 'cursor' ? 'cursor' : t.tool)}
                onMouseEnter={() => startHover(t.tool)}
                onMouseLeave={endHover}
                className={`w-[34px] h-[30px] flex items-center justify-center rounded transition-all duration-150 ${
                  isActive
                    ? 'bg-[#2962ff]/25 text-[#2962ff] shadow-[0_0_6px_rgba(41,98,255,0.2)]'
                    : 'text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39]'
                }`}
              >
                {ICONS[t.tool]}
              </button>

              {/* Tooltip */}
              {hoveredTool === t.tool && (
                <div className="absolute left-[42px] top-1/2 -translate-y-1/2 z-[60] pointer-events-none ml-1">
                  <div className="bg-[#1e222d] border border-[#363a45] rounded-lg px-3 py-2 shadow-2xl whitespace-nowrap">
                    <div className="text-[#d1d4dc] text-[11px] font-semibold">{t.label}</div>
                    <div className="text-[#787b86] text-[10px] mt-0.5 leading-snug max-w-[180px]">{t.desc}</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })}

      {/* ── Bottom controls ── */}
      <div className="flex-1" />

      {/* Magnetic snap toggle */}
      {onToggleMagnetic && (
        <button
          onClick={onToggleMagnetic}
          className={`w-[34px] h-[28px] flex items-center justify-center rounded transition-colors ${
            magneticMode
              ? 'bg-[#f0b90b]/15 text-[#f0b90b] hover:bg-[#f0b90b]/25'
              : 'text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39]'
          }`}
          title={magneticMode ? 'Magnetic snap: ON (snaps to OHLC)' : 'Magnetic snap: OFF'}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M4 2v5a4 4 0 0 0 8 0V2" />
            <line x1="2" y1="2" x2="6" y2="2" />
            <line x1="10" y1="2" x2="14" y2="2" />
          </svg>
        </button>
      )}

      {/* Undo / Redo */}
      {(onUndo || onRedo) && (
        <>
          <button
            onClick={onUndo}
            disabled={!canUndo}
            className="w-[34px] h-[28px] flex items-center justify-center rounded text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors disabled:opacity-25 disabled:pointer-events-none"
            title="Undo (Ctrl+Z)"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="4,7 1,4 4,1" />
              <path d="M1 4h9a4 4 0 0 1 0 8H7" />
            </svg>
          </button>
          <button
            onClick={onRedo}
            disabled={!canRedo}
            className="w-[34px] h-[28px] flex items-center justify-center rounded text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors disabled:opacity-25 disabled:pointer-events-none"
            title="Redo (Ctrl+Shift+Z)"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="12,7 15,4 12,1" />
              <path d="M15 4H6a4 4 0 0 0 0 8h2" />
            </svg>
          </button>
        </>
      )}

      {/* Line width picker */}
      <div className="relative" ref={widthRef}>
        <button
          onClick={() => { setShowWidths(!showWidths); setShowColors(false); }}
          className="w-[34px] h-[28px] flex items-center justify-center rounded text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors"
          title="Line width"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round">
            <line x1="2" y1="4" x2="14" y2="4" strokeWidth="1" />
            <line x1="2" y1="8" x2="14" y2="8" strokeWidth="2.2" />
            <line x1="2" y1="12" x2="14" y2="12" strokeWidth="3.5" />
          </svg>
        </button>

        {showWidths && (
          <div className="absolute left-[46px] bottom-0 bg-[#1e222d] border border-[#363a45] rounded-lg p-2 z-50 shadow-2xl flex flex-col gap-1">
            {[1, 2, 3, 4, 5].map(w => (
              <button
                key={w}
                onClick={() => { onStyleChange({ lineWidth: w }); setCurrentWidth(w); setShowWidths(false); }}
                className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded transition-colors ${
                  currentWidth === w ? 'bg-[#2962ff]/20 text-[#2962ff]' : 'text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39]'
                }`}
              >
                <div className="w-10 flex items-center">
                  <div style={{ width: '100%', height: Math.max(w, 1), backgroundColor: 'currentColor', borderRadius: 1 }} />
                </div>
                <span className="text-[10px] font-mono tabular-nums">{w}px</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Color picker */}
      <div className="relative" ref={colorRef}>
        <button
          onClick={() => { setShowColors(!showColors); setShowWidths(false); }}
          className="w-[34px] h-[28px] flex items-center justify-center rounded hover:bg-[#2a2e39] transition-colors"
          title="Drawing color"
        >
          <div className="w-5 h-5 rounded border-2 border-[#363a45] shadow-inner" style={{ backgroundColor: currentColor }} />
        </button>

        {showColors && (
          <div className="absolute left-[46px] bottom-0 bg-[#1e222d] border border-[#363a45] rounded-lg p-2.5 z-50 shadow-2xl">
            <div className="grid grid-cols-5 gap-1.5">
              {COLORS.map(c => (
                <button
                  key={c}
                  onClick={() => pickColor(c)}
                  className={`w-6 h-6 rounded border-2 transition-all hover:scale-125 ${
                    c === currentColor ? 'border-white scale-110 shadow-lg' : 'border-transparent hover:border-[#787b86]'
                  }`}
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
            <input
              type="color"
              value={currentColor.startsWith('#') ? currentColor : '#3b82f6'}
              onChange={e => pickColor(e.target.value)}
              className="mt-2 w-full h-6 rounded cursor-pointer border border-[#363a45] bg-transparent"
              title="Custom color"
            />
          </div>
        )}
      </div>

      {/* Separator */}
      <div className="w-6 h-px bg-[#2a2e39] mx-auto my-1" />

      {/* Delete selected */}
      {hasSelection && (
        <button
          onClick={onDeleteSelected}
          className="w-[34px] h-[28px] flex items-center justify-center rounded text-[#ef5350] hover:bg-[#ef5350]/15 transition-colors"
          title="Delete selected drawing"
        >
          <Trash2 size={14} />
        </button>
      )}

      {/* Clear all */}
      <button
        onClick={onClearAll}
        className="w-[34px] h-[28px] flex items-center justify-center rounded text-[#787b86] hover:text-[#ef5350] hover:bg-[#2a2e39] transition-colors mb-1"
        title="Clear all drawings"
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}
