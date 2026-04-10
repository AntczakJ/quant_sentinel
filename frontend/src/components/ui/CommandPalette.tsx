/**
 * src/components/ui/CommandPalette.tsx — VS Code-style command palette (Ctrl+K)
 *
 * Fuzzy-search pages, actions, and settings. Keyboard navigable.
 */

import { memo, useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search, BarChart3, LineChart, Repeat, Brain, Newspaper, Bot,
  Sun, Moon, Layers, Clock,
} from 'lucide-react';
import { useTheme } from '../../hooks/useTheme';

interface Command {
  id: string;
  label: string;
  category: string;
  icon: typeof Search;
  action: () => void;
  keywords?: string;
}

function fuzzyMatch(query: string, text: string): boolean {
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;
  let qi = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) qi++;
  }
  return qi === q.length;
}

export const CommandPalette = memo(function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { isDark, toggle: toggleTheme } = useTheme();

  // Build command list
  const commands: Command[] = useMemo(() => [
    // Navigation
    { id: 'nav-chart', label: 'Go to Chart', category: 'Navigate', icon: BarChart3, action: () => navigate('/'), keywords: 'chart wykres home' },
    { id: 'nav-analysis', label: 'Go to Analysis', category: 'Navigate', icon: LineChart, action: () => navigate('/analysis'), keywords: 'analysis analiza' },
    { id: 'nav-trades', label: 'Go to Trades', category: 'Navigate', icon: Repeat, action: () => navigate('/trades'), keywords: 'trades transakcje journal' },
    { id: 'nav-models', label: 'Go to Models', category: 'Navigate', icon: Brain, action: () => navigate('/models'), keywords: 'models ml backtest training' },
    { id: 'nav-news', label: 'Go to News', category: 'Navigate', icon: Newspaper, action: () => navigate('/news'), keywords: 'news newsy calendar kalendarz' },
    { id: 'nav-agent', label: 'Go to Agent', category: 'Navigate', icon: Bot, action: () => navigate('/agent'), keywords: 'agent chat ai' },
    // Actions
    { id: 'act-theme', label: isDark ? 'Switch to Light Theme' : 'Switch to Dark Theme', category: 'Action', icon: isDark ? Sun : Moon, action: toggleTheme, keywords: 'theme motyw dark light ciemny jasny' },
    { id: 'act-smc', label: 'Toggle SMC Overlay', category: 'Action', icon: Layers, action: () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' })); }, keywords: 'smc overlay fvg order block' },
    { id: 'act-sessions', label: 'Toggle Sessions', category: 'Action', icon: Clock, action: () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 's' })); }, keywords: 'sessions sesje asian london ny' },
  ], [isDark, toggleTheme, navigate]);

  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    return commands.filter(c =>
      fuzzyMatch(query, c.label) ||
      fuzzyMatch(query, c.category) ||
      (c.keywords && fuzzyMatch(query, c.keywords))
    );
  }, [query, commands]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Ctrl+K to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(v => !v);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const executeCommand = useCallback((cmd: Command) => {
    cmd.action();
    setOpen(false);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && filtered[selectedIdx]) {
      e.preventDefault();
      executeCommand(filtered[selectedIdx]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }, [filtered, selectedIdx, executeCommand]);

  // Clamp selectedIdx when filtered changes
  useEffect(() => {
    setSelectedIdx(i => Math.min(i, Math.max(filtered.length - 1, 0)));
  }, [filtered.length]);

  if (!open) return null;

  // Group by category
  const grouped = new Map<string, Command[]>();
  for (const cmd of filtered) {
    const list = grouped.get(cmd.category) ?? [];
    list.push(cmd);
    grouped.set(cmd.category, list);
  }

  let globalIdx = 0;

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />

      {/* Palette */}
      <div className="fixed top-[15%] left-1/2 -translate-x-1/2 z-[71] w-[420px] max-w-[90vw] rounded-xl border shadow-2xl overflow-hidden"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>

        {/* Search input */}
        <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <Search size={14} className="text-th-muted flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Szukaj polecenia..."
            className="flex-1 bg-transparent text-sm outline-none"
            style={{ color: 'var(--color-text-primary)' }}
          />
          <kbd className="px-1.5 py-0.5 rounded text-[9px] font-mono border"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto py-1">
          {filtered.length === 0 ? (
            <div className="text-center text-xs py-6" style={{ color: 'var(--color-text-muted)' }}>
              Brak wynikow dla "{query}"
            </div>
          ) : (
            [...grouped.entries()].map(([category, cmds]) => (
              <div key={category}>
                <div className="px-4 py-1 text-[9px] font-medium uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>
                  {category}
                </div>
                {cmds.map(cmd => {
                  const idx = globalIdx++;
                  const isSelected = idx === selectedIdx;
                  const Icon = cmd.icon;
                  return (
                    <button
                      key={cmd.id}
                      onClick={() => executeCommand(cmd)}
                      onMouseEnter={() => setSelectedIdx(idx)}
                      className={`w-full flex items-center gap-3 px-4 py-2 text-xs transition-colors ${
                        isSelected ? 'bg-[var(--color-secondary)]' : ''
                      }`}
                      style={{ color: 'var(--color-text-primary)' }}
                    >
                      <Icon size={14} className="text-th-muted flex-shrink-0" />
                      <span className="flex-1 text-left">{cmd.label}</span>
                      {isSelected && (
                        <kbd className="px-1 py-0.5 rounded text-[8px] font-mono border"
                          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
                          Enter
                        </kbd>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* Footer hint */}
        <div className="px-4 py-2 border-t flex items-center gap-3 text-[9px]"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}>
          <span>↑↓ nawigacja</span>
          <span>Enter wybierz</span>
          <span>Esc zamknij</span>
        </div>
      </div>
    </>
  );
});
