/**
 * src/components/layout/DraggableGrid.tsx — Drag-drop dashboard grid
 *
 * Wraps page widgets in react-grid-layout for rearrangeable panels.
 * Persists layout per page in localStorage.
 * Supports preset layouts and lock/unlock toggle.
 */

import { useState, useCallback, useMemo, memo, type ReactNode } from 'react';
import ReactGridLayout from 'react-grid-layout';

// react-grid-layout uses namespace exports
const Responsive = (ReactGridLayout as any).Responsive ?? ReactGridLayout;
const WidthProvider = (ReactGridLayout as any).WidthProvider ?? ((c: any) => c);

interface Layout { i: string; x: number; y: number; w: number; h: number; minW?: number; minH?: number }
type Layouts = Record<string, Layout[]>;
import { Lock, Unlock, RotateCcw, LayoutGrid } from 'lucide-react';
import 'react-grid-layout/css/styles.css';

const ResponsiveGridLayout = WidthProvider(Responsive);

/* ── Types ─────────────────────────────────────────────────────────── */

export interface GridWidget {
  id: string;
  title: string;
  content: ReactNode;
  /** Default layout for lg breakpoint */
  defaultLayout: { x: number; y: number; w: number; h: number; minW?: number; minH?: number };
}

export interface PresetLayout {
  name: string;
  layouts: Record<string, Layout[]>;
}

interface Props {
  pageKey: string;
  widgets: GridWidget[];
  presets?: PresetLayout[];
  /** Columns at lg breakpoint (default 12) */
  cols?: number;
  /** Row height in pixels (default 80) */
  rowHeight?: number;
}

/* ── Helpers ───────────────────────────────────────────────────────── */

const STORAGE_PREFIX = 'qs:grid-layout:';

function loadLayout(pageKey: string): Layouts | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + pageKey);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveLayout(pageKey: string, layouts: Layouts) {
  try {
    localStorage.setItem(STORAGE_PREFIX + pageKey, JSON.stringify(layouts));
  } catch { /* quota */ }
}

function buildDefaultLayouts(widgets: GridWidget[]): Layouts {
  const lg = widgets.map(w => ({
    i: w.id,
    ...w.defaultLayout,
  }));

  // md: stack to 2 columns
  const md = widgets.map((w, idx) => ({
    i: w.id,
    x: (idx % 2) * 6,
    y: Math.floor(idx / 2) * (w.defaultLayout.h || 4),
    w: 6,
    h: w.defaultLayout.h,
    minW: w.defaultLayout.minW,
    minH: w.defaultLayout.minH,
  }));

  // sm: single column
  const sm = widgets.map((w, idx) => ({
    i: w.id,
    x: 0,
    y: idx * (w.defaultLayout.h || 4),
    w: 12,
    h: w.defaultLayout.h,
    minW: 1,
    minH: w.defaultLayout.minH,
  }));

  return { lg, md, sm };
}

/* ── Component ─────────────────────────────────────────────────────── */

export const DraggableGrid = memo(function DraggableGrid({
  pageKey, widgets, presets, cols = 12, rowHeight = 80,
}: Props) {
  const defaultLayouts = useMemo(() => buildDefaultLayouts(widgets), [widgets]);
  const [layouts, setLayouts] = useState<Layouts>(() => loadLayout(pageKey) ?? defaultLayouts);
  const [locked, setLocked] = useState(true);
  const [showPresets, setShowPresets] = useState(false);

  const handleLayoutChange = useCallback((_layout: Layout[], allLayouts: Layouts) => {
    setLayouts(allLayouts);
    saveLayout(pageKey, allLayouts);
  }, [pageKey]);

  const resetLayout = useCallback(() => {
    setLayouts(defaultLayouts);
    localStorage.removeItem(STORAGE_PREFIX + pageKey);
  }, [pageKey, defaultLayouts]);

  const applyPreset = useCallback((preset: PresetLayout) => {
    setLayouts(preset.layouts);
    saveLayout(pageKey, preset.layouts);
    setShowPresets(false);
  }, [pageKey]);

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center gap-1.5 justify-end">
        {presets && presets.length > 0 && (
          <div className="relative">
            <button
              onClick={() => setShowPresets(v => !v)}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-th-muted hover:text-th-secondary transition-colors"
            >
              <LayoutGrid size={10} />
              Presets
            </button>
            {showPresets && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setShowPresets(false)} />
                <div className="absolute right-0 top-full mt-1 z-40 bg-[var(--color-surface)] border border-[var(--color-border)] rounded-lg shadow-xl py-1 min-w-[140px]">
                  {presets.map(p => (
                    <button
                      key={p.name}
                      onClick={() => applyPreset(p)}
                      className="w-full text-left px-3 py-1.5 text-[11px] text-th-secondary hover:bg-[var(--color-secondary)] transition-colors"
                    >
                      {p.name}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <button
          onClick={resetLayout}
          className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-th-muted hover:text-th-secondary transition-colors"
          title="Reset layout"
        >
          <RotateCcw size={10} />
        </button>
        <button
          onClick={() => setLocked(v => !v)}
          className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors ${
            locked
              ? 'text-th-muted hover:text-th-secondary'
              : 'text-accent-blue bg-accent-blue/10 border border-accent-blue/20'
          }`}
          title={locked ? 'Unlock layout for editing' : 'Lock layout'}
        >
          {locked ? <Lock size={10} /> : <Unlock size={10} />}
          {locked ? 'Locked' : 'Editing'}
        </button>
      </div>

      {/* Grid */}
      <ResponsiveGridLayout
        className="layout"
        layouts={layouts}
        breakpoints={{ lg: 1200, md: 768, sm: 0 }}
        cols={{ lg: cols, md: cols, sm: cols }}
        rowHeight={rowHeight}
        isDraggable={!locked}
        isResizable={!locked}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".drag-handle"
        compactType="vertical"
        margin={[16, 16]}
        containerPadding={[0, 0]}
      >
        {widgets.map(w => (
          <div key={w.id} className="overflow-hidden">
            <div className="card h-full flex flex-col">
              {/* Drag handle header */}
              <div className={`drag-handle flex items-center justify-between mb-2 ${!locked ? 'cursor-grab active:cursor-grabbing' : ''}`}>
                <h2 className="section-title">{w.title}</h2>
                {!locked && (
                  <div className="flex gap-0.5">
                    <div className="w-1 h-1 rounded-full bg-th-muted" />
                    <div className="w-1 h-1 rounded-full bg-th-muted" />
                    <div className="w-1 h-1 rounded-full bg-th-muted" />
                  </div>
                )}
              </div>
              {/* Widget content */}
              <div className="flex-1 min-h-0 overflow-auto">
                {w.content}
              </div>
            </div>
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  );
});
