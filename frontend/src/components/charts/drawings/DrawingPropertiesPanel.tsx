/**
 * DrawingPropertiesPanel.tsx — TradingView-style properties dialog.
 *
 * Tabs: Styl (Style), Współrzędne (Coordinates), Widoczność (Visibility)
 * Floating panel that appears when a drawing is selected/double-clicked.
 * Professional dark theme matching TradingView's dialog aesthetic.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { X, Trash2, Eye, EyeOff, Lock, Unlock } from 'lucide-react';
import type { Drawing, DrawingStyle, FibLevel } from './types';
import { DEFAULT_FIB_LEVELS } from './types';

interface Props {
  drawing: Drawing;
  onUpdate: (id: string, patch: Partial<Drawing>) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const PALETTE = [
  '#2962ff', '#2196f3', '#00bcd4', '#009688', '#4caf50',
  '#8bc34a', '#cddc39', '#ffeb3b', '#ffc107', '#ff9800',
  '#ff5722', '#f44336', '#e91e63', '#9c27b0', '#673ab7',
  '#787b86', '#b2b5be', '#d1d4dc', '#ffffff', '#000000',
];

function hexToRgba(hex: string, alpha: number) {
  const h = hex.replace('#', '');
  if (h.length < 6) { return `rgba(128,128,128,${alpha})`; }
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/* Tool metadata for header */
const TOOL_META: Record<string, { label: string; icon: string }> = {
  trendline:     { label: 'Linia trendu',       icon: '📐' },
  ray:           { label: 'Promień',             icon: '↗' },
  extendedline:  { label: 'Linia rozszerzona',   icon: '↔' },
  hline:         { label: 'Linia pozioma',       icon: '➖' },
  vline:         { label: 'Linia pionowa',       icon: '│' },
  channel:       { label: 'Kanał równoległy',    icon: '▬' },
  fib:           { label: 'Fibonacci',           icon: '📊' },
  rect:          { label: 'Prostokąt',           icon: '⬜' },
  path:          { label: 'Pędzel',              icon: '🖌' },
  text:          { label: 'Tekst',               icon: '🔤' },
  measure:       { label: 'Miara',               icon: '📏' },
  longposition:  { label: 'Pozycja Long',        icon: '🟢' },
  shortposition: { label: 'Pozycja Short',       icon: '🔴' },
};

function formatTimestamp(ts: number): string {
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString('pl-PL', { year: 'numeric', month: '2-digit', day: '2-digit' }) + ' ' +
           d.toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return '—'; }
}

type TabId = 'style' | 'coords' | 'visibility';

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  TAB CONTENT: STYLE                                                       */
/* ═══════════════════════════════════════════════════════════════════════════ */

function StyleTab({ drawing, onUpdate }: { drawing: Drawing; onUpdate: (id: string, patch: Partial<Drawing>) => void }) {
  const s = drawing.style;
  const isText = drawing.tool === 'text';
  const isFib = drawing.tool === 'fib';
  const hasLineWidth = !['text'].includes(drawing.tool);
  const hasFill = ['rect', 'channel', 'measure', 'fib', 'longposition', 'shortposition'].includes(drawing.tool);

  const [fibLevels, setFibLevels] = useState<FibLevel[]>(
    s.fibLevels ?? DEFAULT_FIB_LEVELS.map(l => ({ ...l }))
  );

  const updateStyle = useCallback((patch: Partial<DrawingStyle>) => {
    onUpdate(drawing.id, { style: { ...s, ...patch } });
  }, [drawing.id, s, onUpdate]);

  const updateFibLevel = useCallback((i: number, patch: Partial<FibLevel>) => {
    const next = fibLevels.map((l, idx) => idx === i ? { ...l, ...patch } : l);
    setFibLevels(next);
    onUpdate(drawing.id, { style: { ...s, fibLevels: next } });
  }, [drawing.id, s, fibLevels, onUpdate]);

  return (
    <div className="p-3 space-y-4">
      {/* ── Color palette ── */}
      <div>
        <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-2">Kolor</label>
        <div className="grid grid-cols-10 gap-1">
          {PALETTE.map(c => (
            <button
              key={c}
              onClick={() => updateStyle({ color: c, fillColor: hexToRgba(c, 0.12) })}
              className={`w-full aspect-square rounded-sm border transition-all hover:scale-110 ${
                s.color === c ? 'border-white scale-105 ring-1 ring-white/30' : 'border-transparent hover:border-[#787b86]'
              }`}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
        <input
          type="color"
          value={s.color.startsWith('#') ? s.color : '#2962ff'}
          onChange={e => updateStyle({ color: e.target.value, fillColor: hexToRgba(e.target.value, 0.12) })}
          className="w-full h-6 rounded cursor-pointer border border-[#363a45] bg-transparent mt-2"
        />
      </div>

      {/* ── Line width & style ── */}
      {hasLineWidth && (
        <div>
          <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-2">Linia</label>
          {/* Width */}
          <div className="flex gap-1 mb-2">
            {[1, 2, 3, 4, 5].map(w => (
              <button
                key={w}
                onClick={() => updateStyle({ lineWidth: w })}
                className={`flex-1 py-2.5 rounded border transition-colors flex items-center justify-center ${
                  s.lineWidth === w
                    ? 'border-[#2962ff] bg-[#2962ff]/15 text-[#2962ff]'
                    : 'border-[#363a45] text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39]'
                }`}
              >
                <div style={{ width: '60%', height: Math.max(w, 1), backgroundColor: 'currentColor', borderRadius: 1 }} />
              </button>
            ))}
          </div>
          {/* Style */}
          <div className="flex gap-1">
            {([
              { key: 'solid' as const,  visual: '━━━━━━' },
              { key: 'dashed' as const, visual: '╌ ╌ ╌ ╌' },
              { key: 'dotted' as const, visual: '• • • • •' },
            ]).map(ls => (
              <button
                key={ls.key}
                onClick={() => updateStyle({ lineStyle: ls.key })}
                className={`flex-1 py-1.5 rounded text-[10px] border transition-colors font-mono ${
                  s.lineStyle === ls.key
                    ? 'border-[#2962ff] bg-[#2962ff]/15 text-[#2962ff]'
                    : 'border-[#363a45] text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39]'
                }`}
              >
                {ls.visual}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Fill opacity ── */}
      {hasFill && !isFib && (
        <div>
          <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-2">Tło</label>
          <div className="flex gap-1">
            {[
              { val: 0, label: 'Brak' },
              { val: 0.08, label: '8%' },
              { val: 0.15, label: '15%' },
              { val: 0.25, label: '25%' },
              { val: 0.4, label: '40%' },
            ].map(o => (
              <button
                key={o.val}
                onClick={() => {
                  const hex = s.color.startsWith('#') ? s.color : '#2962ff';
                  updateStyle({ fillColor: hexToRgba(hex, o.val) });
                }}
                className="flex-1 py-1.5 rounded text-[10px] border border-[#363a45] text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors"
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Text section ── */}
      {isText && (
        <div>
          <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-2">Tekst</label>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#787b86] w-14">Rozmiar</span>
              <input
                type="range" min={8} max={32} step={1}
                value={s.fontSize}
                onChange={e => updateStyle({ fontSize: Number(e.target.value) })}
                className="flex-1 accent-[#2962ff]"
              />
              <span className="text-[10px] text-[#d1d4dc] w-8 text-right font-mono">{s.fontSize}px</span>
            </div>
            <input
              type="text"
              value={s.text}
              onChange={e => updateStyle({ text: e.target.value })}
              className="w-full bg-[#1e222d] border border-[#363a45] rounded px-2.5 py-1.5 text-[#d1d4dc] text-[11px] outline-none focus:border-[#2962ff] transition-colors"
              placeholder="Wpisz tekst..."
            />
          </div>
        </div>
      )}

      {/* ── Fibonacci levels ── */}
      {isFib && (
        <div>
          <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-2">Poziomy ceny</label>
          <div className="space-y-0.5 max-h-52 overflow-y-auto pr-0.5">
            {fibLevels.map((fl, i) => (
              <div key={i} className="flex items-center gap-2 py-1.5 rounded hover:bg-[#1e222d] px-1.5 -mx-1.5 group">
                {/* Toggle */}
                <button
                  onClick={() => updateFibLevel(i, { visible: !fl.visible })}
                  className={`w-4 h-4 rounded-sm border flex items-center justify-center transition-colors flex-shrink-0 ${
                    fl.visible
                      ? 'bg-[#2962ff] border-[#2962ff]'
                      : 'border-[#363a45] hover:border-[#787b86]'
                  }`}
                >
                  {fl.visible && (
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="2,5 4.5,7.5 8,3" />
                    </svg>
                  )}
                </button>

                {/* Level value */}
                <span className={`w-14 font-mono text-[11px] tabular-nums ${fl.visible ? 'text-[#d1d4dc]' : 'text-[#787b86]'}`}>
                  {fl.level}
                </span>

                {/* Color swatch */}
                <input
                  type="color"
                  value={fl.color.startsWith('#') ? fl.color : '#787b86'}
                  onChange={e => updateFibLevel(i, { color: hexToRgba(e.target.value, 0.6) })}
                  className="w-5 h-5 rounded cursor-pointer border border-[#363a45] bg-transparent flex-shrink-0"
                />

                {/* Color line preview */}
                <div className="flex-1 h-[2px] rounded-full" style={{ backgroundColor: fl.color }} />
              </div>
            ))}
          </div>

          {/* Preset buttons */}
          <div className="flex gap-1 mt-3">
            {[
              {
                label: 'Kluczowe',
                title: 'Pokaż 0, 0.382, 0.5, 0.618, 1',
                action: () => {
                  const preset = fibLevels.map(l => ({ ...l, visible: [0, 0.382, 0.5, 0.618, 1].includes(l.level) }));
                  setFibLevels(preset);
                  onUpdate(drawing.id, { style: { ...s, fibLevels: preset } });
                },
              },
              {
                label: 'Wszystkie',
                title: 'Pokaż wszystkie poziomy',
                action: () => {
                  const all = fibLevels.map(l => ({ ...l, visible: true }));
                  setFibLevels(all);
                  onUpdate(drawing.id, { style: { ...s, fibLevels: all } });
                },
              },
              {
                label: 'Szary',
                title: 'Ustaw kolor na szary',
                action: () => {
                  const gray = fibLevels.map(l => ({ ...l, color: 'rgba(156,163,175,0.6)' }));
                  setFibLevels(gray);
                  onUpdate(drawing.id, { style: { ...s, fibLevels: gray } });
                },
              },
            ].map(p => (
              <button
                key={p.label}
                onClick={p.action}
                title={p.title}
                className="flex-1 py-1.5 rounded text-[10px] border border-[#363a45] text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors font-medium"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  TAB CONTENT: COORDINATES                                                 */
/* ═══════════════════════════════════════════════════════════════════════════ */

function CoordsTab({ drawing }: { drawing: Drawing }) {
  return (
    <div className="p-3">
      <label className="text-[10px] text-[#787b86] uppercase tracking-wider font-semibold block mb-3">Punkty</label>
      <div className="space-y-2">
        {drawing.points.map((pt, i) => (
          <div key={i} className="bg-[#1e222d] rounded border border-[#363a45] p-2.5">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[10px] text-[#787b86] font-semibold uppercase">Punkt {i + 1}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-[9px] text-[#787b86] block mb-0.5">Cena</span>
                <div className="text-[11px] text-[#d1d4dc] font-mono tabular-nums bg-[#131722] rounded px-2 py-1 border border-[#363a45]">
                  {pt.price.toFixed(2)}
                </div>
              </div>
              <div>
                <span className="text-[9px] text-[#787b86] block mb-0.5">Czas</span>
                <div className="text-[10px] text-[#d1d4dc] font-mono tabular-nums bg-[#131722] rounded px-2 py-1 border border-[#363a45]">
                  {formatTimestamp(pt.time)}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
      {drawing.points.length === 0 && (
        <div className="text-[11px] text-[#787b86] text-center py-4">Brak punktów</div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  TAB CONTENT: VISIBILITY                                                  */
/* ═══════════════════════════════════════════════════════════════════════════ */

function VisibilityTab({ drawing, onUpdate }: { drawing: Drawing; onUpdate: (id: string, patch: Partial<Drawing>) => void }) {
  const isLocked = drawing.locked ?? false;

  return (
    <div className="p-3 space-y-3">
      {/* Visible toggle */}
      <button
        onClick={() => onUpdate(drawing.id, { visible: !drawing.visible })}
        className="w-full flex items-center gap-3 p-3 rounded border border-[#363a45] hover:bg-[#1e222d] transition-colors"
      >
        <div className={`w-4 h-4 rounded-sm border flex items-center justify-center ${
          drawing.visible ? 'bg-[#2962ff] border-[#2962ff]' : 'border-[#363a45]'
        }`}>
          {drawing.visible && (
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="2,5 4.5,7.5 8,3" />
            </svg>
          )}
        </div>
        <div className="flex items-center gap-2 flex-1">
          {drawing.visible ? <Eye size={14} className="text-[#d1d4dc]" /> : <EyeOff size={14} className="text-[#787b86]" />}
          <span className={`text-[11px] ${drawing.visible ? 'text-[#d1d4dc]' : 'text-[#787b86]'}`}>
            {drawing.visible ? 'Widoczny' : 'Ukryty'}
          </span>
        </div>
      </button>

      {/* Lock toggle */}
      <button
        onClick={() => onUpdate(drawing.id, { locked: !isLocked })}
        className="w-full flex items-center gap-3 p-3 rounded border border-[#363a45] hover:bg-[#1e222d] transition-colors"
      >
        <div className={`w-4 h-4 rounded-sm border flex items-center justify-center ${
          isLocked ? 'bg-[#f0b90b] border-[#f0b90b]' : 'border-[#363a45]'
        }`}>
          {isLocked && (
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="2,5 4.5,7.5 8,3" />
            </svg>
          )}
        </div>
        <div className="flex items-center gap-2 flex-1">
          {isLocked ? <Lock size={14} className="text-[#f0b90b]" /> : <Unlock size={14} className="text-[#787b86]" />}
          <span className={`text-[11px] ${isLocked ? 'text-[#f0b90b]' : 'text-[#787b86]'}`}>
            {isLocked ? 'Zablokowany (nie można przesuwać)' : 'Odblokowany'}
          </span>
        </div>
      </button>

      {/* Timeframe note */}
      <div className="text-[10px] text-[#787b86] mt-4 px-1">
        Rysunek jest widoczny na bieżącym interwale czasowym. Zmiana interwału ładuje osobny zestaw rysunków.
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN PANEL                                                               */
/* ═══════════════════════════════════════════════════════════════════════════ */

export function DrawingPropertiesPanel({ drawing, onUpdate, onDelete, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>('style');
  const meta = TOOL_META[drawing.tool] ?? { label: drawing.tool, icon: '📝' };
  const panelRef = useRef<HTMLDivElement>(null);

  // Dragging support for the panel
  const [dragging, setDragging] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const dragOffset = useRef({ x: 0, y: 0 });

  const onHeaderPointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    setDragging(true);
    const rect = panelRef.current?.getBoundingClientRect();
    if (rect) {
      dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }
  }, []);

  useEffect(() => {
    if (!dragging) { return; }
    const onMove = (e: PointerEvent) => {
      const parent = panelRef.current?.parentElement;
      if (!parent) { return; }
      const parentRect = parent.getBoundingClientRect();
      setPos({
        x: e.clientX - parentRect.left - dragOffset.current.x,
        y: e.clientY - parentRect.top - dragOffset.current.y,
      });
    };
    const onUp = () => setDragging(false);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragging]);

  const tabs: { id: TabId; label: string }[] = [
    { id: 'style', label: 'Styl' },
    { id: 'coords', label: 'Współrzędne' },
    { id: 'visibility', label: 'Widoczność' },
  ];

  const panelStyle: React.CSSProperties = pos
    ? { left: pos.x, top: pos.y, right: 'auto' }
    : { right: 8, top: 40 };

  return (
    <div
      ref={panelRef}
      className="absolute z-40 bg-[#131722] border border-[#363a45] rounded-lg shadow-2xl text-xs select-none overflow-hidden"
      style={{ width: 300, ...panelStyle }}
    >
      {/* ═══ Header — draggable ═══ */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-[#1e222d] border-b border-[#363a45] cursor-move"
        onPointerDown={onHeaderPointerDown}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm leading-none">{meta.icon}</span>
          <span className="text-[#d1d4dc] font-semibold text-[12px]">{meta.label}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => onDelete(drawing.id)}
            className="p-1.5 rounded text-[#ef5350]/70 hover:text-[#ef5350] hover:bg-[#ef5350]/10 transition-colors"
            title="Usuń rysunek"
          >
            <Trash2 size={12} />
          </button>
          <button
            onClick={onClose}
            className="p-1.5 rounded text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors"
            title="Zamknij"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* ═══ Tabs ═══ */}
      <div className="flex border-b border-[#363a45]">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-2 text-[11px] font-medium transition-colors relative ${
              activeTab === tab.id
                ? 'text-[#2962ff]'
                : 'text-[#787b86] hover:text-[#d1d4dc]'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <div className="absolute bottom-0 left-0 right-0 h-[2px] bg-[#2962ff]" />
            )}
          </button>
        ))}
      </div>

      {/* ═══ Tab content (scrollable) ═══ */}
      <div className="max-h-[65vh] overflow-y-auto">
        {activeTab === 'style' && <StyleTab drawing={drawing} onUpdate={onUpdate} />}
        {activeTab === 'coords' && <CoordsTab drawing={drawing} />}
        {activeTab === 'visibility' && <VisibilityTab drawing={drawing} onUpdate={onUpdate} />}
      </div>

      {/* ═══ Footer ═══ */}
      <div className="flex items-center justify-end gap-2 px-3 py-2 border-t border-[#363a45] bg-[#1e222d]">
        <button
          onClick={onClose}
          className="px-4 py-1.5 rounded text-[11px] text-[#787b86] hover:text-[#d1d4dc] hover:bg-[#2a2e39] transition-colors"
        >
          Anuluj
        </button>
        <button
          onClick={onClose}
          className="px-4 py-1.5 rounded text-[11px] bg-[#2962ff] text-white hover:bg-[#2962ff]/80 transition-colors font-medium"
        >
          Ok
        </button>
      </div>
    </div>
  );
}

