/**
 * DrawingPropertiesPanel.tsx — Professional floating editor for drawing properties.
 *
 * Appears on the right side when a drawing is double-clicked.
 * Features: collapsible sections, color palette + custom picker, line width/style,
 * fill opacity, font/text, fibonacci level editor, lock toggle, coordinates display.
 */

import { useState } from 'react';
import { X, Trash2, Eye, EyeOff, Lock, Unlock, ChevronDown, ChevronRight } from 'lucide-react';
import type { Drawing, DrawingStyle, FibLevel } from './types';
import { DEFAULT_FIB_LEVELS } from './types';

interface Props {
  drawing: Drawing;
  onUpdate: (id: string, patch: Partial<Drawing>) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

const PALETTE = [
  '#3b82f6', '#22c55e', '#ef4444', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#e2e8f0', '#6b7280',
  '#ffffff', '#000000',
];

function hexToRgba(hex: string, alpha: number) {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/* Tool metadata for header */
const TOOL_META: Record<string, { label: string; emoji: string }> = {
  trendline:     { label: 'Trend Line',       emoji: '📐' },
  ray:           { label: 'Ray',              emoji: '↗' },
  extendedline:  { label: 'Extended Line',    emoji: '↔' },
  hline:         { label: 'Horizontal Line',  emoji: '➖' },
  vline:         { label: 'Vertical Line',    emoji: '│' },
  channel:       { label: 'Parallel Channel', emoji: '▬' },
  fib:           { label: 'Fibonacci',        emoji: '📊' },
  rect:          { label: 'Rectangle',        emoji: '⬜' },
  path:          { label: 'Brush',            emoji: '🖌' },
  text:          { label: 'Text',             emoji: '🔤' },
  measure:       { label: 'Measure',          emoji: '📏' },
  longposition:  { label: 'Long Position',    emoji: '🟢' },
  shortposition: { label: 'Short Position',   emoji: '🔴' },
};

function formatTimestamp(ts: number): string {
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch { return '—'; }
}

/* ── Collapsible Section ── */
function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-[#1a2030] last:border-b-0">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-[10px] text-gray-500 font-semibold uppercase tracking-wider hover:text-gray-400 transition-colors"
      >
        <span>{title}</span>
        {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
      </button>
      {open && <div className="px-3 pb-3 space-y-2.5">{children}</div>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════ */
/*  MAIN PANEL                                                               */
/* ═══════════════════════════════════════════════════════════════════════════ */

export function DrawingPropertiesPanel({ drawing, onUpdate, onDelete, onClose }: Props) {
  const s = drawing.style;
  const meta = TOOL_META[drawing.tool] ?? { label: drawing.tool, emoji: '📝' };
  const isFib = drawing.tool === 'fib';
  const isText = drawing.tool === 'text';
  const hasLineWidth = !['text'].includes(drawing.tool);
  const hasFill = ['rect', 'channel', 'measure', 'fib', 'longposition', 'shortposition'].includes(drawing.tool);
  const isLocked = drawing.locked ?? false;

  const [fibLevels, setFibLevels] = useState<FibLevel[]>(
    s.fibLevels ?? DEFAULT_FIB_LEVELS.map(l => ({ ...l }))
  );

  const updateStyle = (patch: Partial<DrawingStyle>) => {
    onUpdate(drawing.id, { style: { ...s, ...patch } });
  };

  const updateFibLevel = (i: number, patch: Partial<FibLevel>) => {
    const next = fibLevels.map((l, idx) => idx === i ? { ...l, ...patch } : l);
    setFibLevels(next);
    onUpdate(drawing.id, { style: { ...s, fibLevels: next } });
  };

  return (
    <div
      className="absolute right-2 top-10 z-40 bg-[#0d1117] border border-[#1a2030] rounded-xl shadow-2xl text-xs select-none overflow-hidden"
      style={{ width: 280, backdropFilter: 'blur(12px)' }}
    >
      {/* ═══ Header ═══ */}
      <div className="flex items-center justify-between px-3 py-2.5 bg-[#0f1520] border-b border-[#1a2030]">
        <div className="flex items-center gap-2">
          <span className="text-sm leading-none">{meta.emoji}</span>
          <span className="text-gray-300 font-semibold text-[11px]">{meta.label}</span>
        </div>
        <div className="flex items-center gap-0.5">
          {/* Lock toggle */}
          <button
            onClick={() => onUpdate(drawing.id, { locked: !isLocked })}
            className={`p-1.5 rounded-md transition-colors ${
              isLocked ? 'text-amber-400 bg-amber-400/10' : 'text-gray-600 hover:text-gray-400 hover:bg-[#1a2030]'
            }`}
            title={isLocked ? 'Unlock drawing' : 'Lock drawing (prevent moving)'}
          >
            {isLocked ? <Lock size={12} /> : <Unlock size={12} />}
          </button>
          {/* Visibility */}
          <button
            onClick={() => onUpdate(drawing.id, { visible: !drawing.visible })}
            className={`p-1.5 rounded-md transition-colors ${
              drawing.visible ? 'text-gray-400 hover:bg-[#1a2030]' : 'text-gray-600 bg-gray-600/10 hover:bg-[#1a2030]'
            }`}
            title={drawing.visible ? 'Hide drawing' : 'Show drawing'}
          >
            {drawing.visible ? <Eye size={12} /> : <EyeOff size={12} />}
          </button>
          {/* Delete */}
          <button
            onClick={() => onDelete(drawing.id)}
            className="p-1.5 rounded-md text-red-500/80 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            title="Delete drawing"
          >
            <Trash2 size={12} />
          </button>
          {/* Close */}
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-500 hover:text-gray-300 hover:bg-[#1a2030] transition-colors"
            title="Close panel"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* ═══ Content (scrollable) ═══ */}
      <div className="max-h-[70vh] overflow-y-auto">

        {/* ── Color Section ── */}
        <Section title="Color">
          <div className="grid grid-cols-6 gap-1.5">
            {PALETTE.map(c => (
              <button
                key={c}
                onClick={() => updateStyle({ color: c, fillColor: hexToRgba(c, 0.12) })}
                className={`w-full aspect-square rounded-md border-2 transition-all hover:scale-110 ${
                  s.color === c ? 'border-white scale-105 shadow-lg' : 'border-transparent hover:border-gray-600'
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
          <input
            type="color"
            value={s.color.startsWith('#') ? s.color : '#3b82f6'}
            onChange={e => updateStyle({ color: e.target.value, fillColor: hexToRgba(e.target.value, 0.12) })}
            className="w-full h-7 rounded-md cursor-pointer border border-[#1a2030] bg-transparent mt-1"
            title="Custom color"
          />
        </Section>

        {/* ── Line Section ── */}
        {hasLineWidth && (
          <Section title="Line">
            {/* Width */}
            <div>
              <label className="text-gray-500 text-[10px] block mb-1.5">Width</label>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map(w => (
                  <button
                    key={w}
                    onClick={() => updateStyle({ lineWidth: w })}
                    className={`flex-1 py-2 rounded-md border transition-colors flex items-center justify-center ${
                      s.lineWidth === w
                        ? 'border-blue-500 bg-blue-500/15 text-blue-300'
                        : 'border-[#1a2030] text-gray-500 hover:text-gray-300 hover:bg-[#1a2030]'
                    }`}
                  >
                    <div style={{ width: '60%', height: Math.max(w, 1), backgroundColor: 'currentColor', borderRadius: 1 }} />
                  </button>
                ))}
              </div>
            </div>
            {/* Style */}
            <div>
              <label className="text-gray-500 text-[10px] block mb-1.5">Style</label>
              <div className="flex gap-1">
                {([
                  { key: 'solid' as const,  label: 'Solid',  visual: '━━━━━━' },
                  { key: 'dashed' as const, label: 'Dashed', visual: '╌ ╌ ╌ ╌' },
                  { key: 'dotted' as const, label: 'Dotted', visual: '• • • • •' },
                ]).map(ls => (
                  <button
                    key={ls.key}
                    onClick={() => updateStyle({ lineStyle: ls.key })}
                    className={`flex-1 py-1.5 rounded-md text-[10px] border transition-colors font-mono ${
                      s.lineStyle === ls.key
                        ? 'border-blue-500 bg-blue-500/15 text-blue-300'
                        : 'border-[#1a2030] text-gray-500 hover:text-gray-300 hover:bg-[#1a2030]'
                    }`}
                    title={ls.label}
                  >
                    {ls.visual}
                  </button>
                ))}
              </div>
            </div>
          </Section>
        )}

        {/* ── Fill Section ── */}
        {hasFill && !isFib && (
          <Section title="Fill">
            <div className="flex gap-1">
              {[
                { val: 0, label: 'None' },
                { val: 0.08, label: '8%' },
                { val: 0.15, label: '15%' },
                { val: 0.25, label: '25%' },
                { val: 0.4, label: '40%' },
              ].map(o => (
                <button
                  key={o.val}
                  onClick={() => {
                    const hex = s.color.startsWith('#') ? s.color : '#3b82f6';
                    updateStyle({ fillColor: hexToRgba(hex, o.val) });
                  }}
                  className="flex-1 py-1.5 rounded-md text-[10px] border border-[#1a2030] text-gray-500 hover:text-gray-300 hover:bg-[#1a2030] transition-colors"
                >
                  {o.label}
                </button>
              ))}
            </div>
          </Section>
        )}

        {/* ── Text Section ── */}
        {isText && (
          <Section title="Text">
            <div>
              <label className="text-gray-500 text-[10px] block mb-1.5">Font Size: {s.fontSize}px</label>
              <input
                type="range" min={8} max={32} step={1}
                value={s.fontSize}
                onChange={e => updateStyle({ fontSize: Number(e.target.value) })}
                className="w-full accent-blue-500"
              />
            </div>
            <div>
              <label className="text-gray-500 text-[10px] block mb-1.5">Content</label>
              <input
                type="text"
                value={s.text}
                onChange={e => updateStyle({ text: e.target.value })}
                className="w-full bg-[#1a2030] border border-[#2a3040] rounded-md px-2.5 py-1.5 text-white text-[11px] outline-none focus:border-blue-500/60 transition-colors"
                placeholder="Enter text..."
              />
            </div>
          </Section>
        )}

        {/* ── Fibonacci Levels Section ── */}
        {isFib && (
          <Section title="Fibonacci Levels">
            <div className="space-y-0.5 max-h-48 overflow-y-auto pr-0.5">
              {fibLevels.map((fl, i) => (
                <div key={i} className="flex items-center gap-2 py-1 rounded-md hover:bg-[#1a2030]/50 px-1.5 -mx-1.5">
                  {/* Toggle visibility */}
                  <button
                    onClick={() => updateFibLevel(i, { visible: !fl.visible })}
                    className={`flex-shrink-0 transition-colors ${fl.visible ? 'text-gray-300' : 'text-gray-600'}`}
                    title={fl.visible ? 'Hide level' : 'Show level'}
                  >
                    {fl.visible ? <Eye size={10} /> : <EyeOff size={10} />}
                  </button>

                  {/* Level label */}
                  <span className={`w-12 font-mono text-[10px] tabular-nums ${fl.visible ? 'text-gray-300' : 'text-gray-600'}`}>
                    {(fl.level * 100).toFixed(1)}%
                  </span>

                  {/* Color swatch */}
                  <input
                    type="color"
                    value={fl.color.startsWith('#') ? fl.color : '#6b7280'}
                    onChange={e => updateFibLevel(i, { color: hexToRgba(e.target.value, 0.6) })}
                    className="w-5 h-4 rounded cursor-pointer border border-[#2a3040] bg-transparent flex-shrink-0"
                    title="Level color"
                  />

                  {/* Color strip preview */}
                  <div className="flex-1 h-0.5 rounded-full" style={{ backgroundColor: fl.color }} />
                </div>
              ))}
            </div>

            {/* Preset buttons */}
            <div className="flex gap-1 mt-2">
              {[
                {
                  label: 'Key levels',
                  title: 'Show 0%, 38.2%, 50%, 61.8%, 100%',
                  action: () => {
                    const preset = fibLevels.map(l => ({ ...l, visible: [0, 0.382, 0.5, 0.618, 1].includes(l.level) }));
                    setFibLevels(preset);
                    onUpdate(drawing.id, { style: { ...s, fibLevels: preset } });
                  },
                },
                {
                  label: 'Gray',
                  title: 'Set all levels to gray',
                  action: () => {
                    const gray = fibLevels.map(l => ({ ...l, color: 'rgba(156,163,175,0.6)' }));
                    setFibLevels(gray);
                    onUpdate(drawing.id, { style: { ...s, fibLevels: gray } });
                  },
                },
                {
                  label: 'All',
                  title: 'Show all levels',
                  action: () => {
                    const all = fibLevels.map(l => ({ ...l, visible: true }));
                    setFibLevels(all);
                    onUpdate(drawing.id, { style: { ...s, fibLevels: all } });
                  },
                },
              ].map(p => (
                <button
                  key={p.label}
                  onClick={p.action}
                  title={p.title}
                  className="flex-1 py-1.5 rounded-md text-[9px] border border-[#1a2030] text-gray-500 hover:text-gray-300 hover:bg-[#1a2030] transition-colors font-medium"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </Section>
        )}

        {/* ── Coordinates Section (collapsed by default) ── */}
        {drawing.points.length > 0 && (
          <Section title="Coordinates" defaultOpen={false}>
            <div className="space-y-1.5">
              {drawing.points.map((pt, i) => (
                <div key={i} className="flex items-center gap-2 text-[10px] font-mono bg-[#1a2030]/40 rounded-md px-2 py-1.5">
                  <span className="text-gray-600 font-semibold w-5">P{i + 1}</span>
                  <span className="text-gray-400 tabular-nums">{pt.price.toFixed(2)}</span>
                  <span className="text-gray-600">@</span>
                  <span className="text-gray-500 tabular-nums">{formatTimestamp(pt.time)}</span>
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

