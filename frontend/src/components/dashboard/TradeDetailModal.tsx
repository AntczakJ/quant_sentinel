/**
 * src/components/dashboard/TradeDetailModal.tsx — Full trade detail modal
 *
 * Shows entry/SL/TP chart, pattern info, timing, P&L breakdown.
 */

import { memo, useCallback, useState } from 'react';
import { X, TrendingUp, TrendingDown, Clock, Target, Shield, Zap, Copy, StickyNote, Save } from 'lucide-react';

interface Trade {
  id: number;
  direction: string;
  entry: string | number;
  sl: string | number;
  tp: string | number;
  status: string;
  profit?: string | number;
  timestamp: string;
  result: string;
  timeframe?: string | null;
  pattern?: string | null;
  grade?: string | null;
  session?: string | null;
}

function parsePrice(val: string | number | undefined): number {
  if (!val) {return 0;}
  if (typeof val === 'number') {return val;}
  return parseFloat(val.replace('$', '')) || 0;
}

function formatPrice(val: string | number | undefined): string {
  const n = parsePrice(val);
  return n ? `$${n.toFixed(2)}` : '—';
}

interface Props {
  trade: Trade;
  onClose: () => void;
}

const NOTES_KEY = 'qs:trade-notes';

function loadNote(tradeId: number): string {
  try { return JSON.parse(localStorage.getItem(NOTES_KEY) ?? '{}')[tradeId] ?? ''; }
  catch { return ''; }
}

function saveNote(tradeId: number, note: string) {
  try {
    const all = JSON.parse(localStorage.getItem(NOTES_KEY) ?? '{}');
    if (note.trim()) {all[tradeId] = note;} else {delete all[tradeId];}
    localStorage.setItem(NOTES_KEY, JSON.stringify(all));
  } catch { /* quota */ }
}

export const TradeDetailModal = memo(function TradeDetailModal({ trade, onClose }: Props) {
  const [note, setNote] = useState(() => loadNote(trade.id));
  const [noteSaved, setNoteSaved] = useState(true);

  const handleSaveNote = useCallback(() => {
    saveNote(trade.id, note);
    setNoteSaved(true);
  }, [trade.id, note]);

  const copyToClipboard = useCallback(() => {
    const lines = [
      `📊 Trade #${trade.id} — ${trade.direction} ${trade.result}`,
      `Entry: ${formatPrice(trade.entry)} | SL: ${formatPrice(trade.sl)} | TP: ${formatPrice(trade.tp)}`,
      `R:R: ${(Math.abs(parsePrice(trade.tp) - parsePrice(trade.entry)) / (Math.abs(parsePrice(trade.entry) - parsePrice(trade.sl)) || 1)).toFixed(2)}`,
      trade.profit !== null ? `P&L: ${formatPrice(trade.profit)}` : '',
      trade.pattern ? `Pattern: ${trade.pattern}` : '',
      trade.timeframe ? `TF: ${trade.timeframe}` : '',
      `Time: ${trade.timestamp}`,
    ].filter(Boolean).join('\n');
    void navigator.clipboard.writeText(lines);
  }, [trade]);
  const isWin = trade.result?.includes('WIN');
  const isLoss = trade.result?.includes('LOSS');
  const entry = parsePrice(trade.entry);
  const sl = parsePrice(trade.sl);
  const tp = parsePrice(trade.tp);
  const risk = Math.abs(entry - sl);
  const reward = Math.abs(tp - entry);
  const rr = risk > 0 ? reward / risk : 0;
  const profit = parsePrice(trade.profit);

  // Mini chart dimensions
  const W = 280, H = 120, PAD = 20;
  const prices = [sl, entry, tp].filter(Boolean);
  const pMin = Math.min(...prices);
  const pMax = Math.max(...prices);
  const pRange = pMax - pMin || 1;
  const yOf = (p: number) => PAD + ((pMax - p) / pRange) * (H - PAD * 2);

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[61] w-96 max-w-[90vw] rounded-xl border shadow-2xl overflow-hidden"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>

        {/* Header */}
        <div className={`flex items-center justify-between px-4 py-3 border-b ${
          isWin ? 'bg-accent-green/5' : isLoss ? 'bg-accent-red/5' : 'bg-accent-blue/5'
        }`} style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-2">
            {trade.direction === 'LONG' ? <TrendingUp size={16} className="text-accent-green" /> : <TrendingDown size={16} className="text-accent-red" />}
            <span className="text-sm font-bold" style={{ color: 'var(--color-text-primary)' }}>
              {trade.direction} #{trade.id}
            </span>
            <span className={`text-xs font-bold ${isWin ? 'text-accent-green' : isLoss ? 'text-accent-red' : 'text-accent-blue'}`}>
              {trade.result}
            </span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-dark-secondary transition-colors" style={{ color: 'var(--color-text-muted)' }}>
            <X size={14} />
          </button>
        </div>

        {/* SVG Chart */}
        <div className="px-4 py-3 flex justify-center">
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            {/* TP zone */}
            <rect x={40} y={Math.min(yOf(entry), yOf(tp))} width={W - 80}
              height={Math.abs(yOf(tp) - yOf(entry))}
              fill={isWin ? 'rgba(34,197,94,0.15)' : 'rgba(34,197,94,0.08)'} rx={4} />
            {/* SL zone */}
            <rect x={40} y={Math.min(yOf(entry), yOf(sl))} width={W - 80}
              height={Math.abs(yOf(sl) - yOf(entry))}
              fill="rgba(239,68,68,0.1)" rx={4} />

            {/* Lines */}
            <line x1={30} y1={yOf(tp)} x2={W - 30} y2={yOf(tp)} stroke="#22c55e" strokeWidth={1.5} strokeDasharray="6,3" />
            <line x1={30} y1={yOf(entry)} x2={W - 30} y2={yOf(entry)} stroke="#3b82f6" strokeWidth={2} />
            <line x1={30} y1={yOf(sl)} x2={W - 30} y2={yOf(sl)} stroke="#ef4444" strokeWidth={1.5} strokeDasharray="6,3" />

            {/* Labels */}
            <text x={8} y={yOf(tp) + 4} fill="#22c55e" fontSize="10" fontFamily="monospace" fontWeight="bold">TP</text>
            <text x={W - 28} y={yOf(tp) + 4} fill="#22c55e" fontSize="9" fontFamily="monospace" textAnchor="end">{formatPrice(trade.tp)}</text>

            <text x={8} y={yOf(entry) + 4} fill="#3b82f6" fontSize="10" fontFamily="monospace" fontWeight="bold">E</text>
            <text x={W - 28} y={yOf(entry) + 4} fill="#3b82f6" fontSize="9" fontFamily="monospace" textAnchor="end">{formatPrice(trade.entry)}</text>

            <text x={8} y={yOf(sl) + 4} fill="#ef4444" fontSize="10" fontFamily="monospace" fontWeight="bold">SL</text>
            <text x={W - 28} y={yOf(sl) + 4} fill="#ef4444" fontSize="9" fontFamily="monospace" textAnchor="end">{formatPrice(trade.sl)}</text>
          </svg>
        </div>

        {/* Details grid */}
        <div className="px-4 pb-4 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="stat-item !p-2">
              <div className="flex items-center gap-1 text-[9px] text-th-muted"><Target size={8} />R:R Ratio</div>
              <div className={`text-sm font-bold font-mono ${rr >= 2 ? 'text-accent-green' : rr >= 1 ? 'text-accent-orange' : 'text-accent-red'}`}>
                {rr.toFixed(2)}
              </div>
            </div>
            <div className="stat-item !p-2">
              <div className="flex items-center gap-1 text-[9px] text-th-muted"><Zap size={8} />P&L</div>
              <div className={`text-sm font-bold font-mono ${profit >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
                {profit >= 0 ? '+' : ''}${profit.toFixed(2)}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-[10px]">
            {trade.timeframe && (
              <div className="stat-item !p-2 text-center">
                <div className="text-th-dim">Timeframe</div>
                <div className="font-bold font-mono text-accent-blue">{trade.timeframe}</div>
              </div>
            )}
            {trade.grade && (
              <div className="stat-item !p-2 text-center">
                <div className="text-th-dim">Grade</div>
                <div className="font-bold font-mono text-accent-green">{trade.grade}</div>
              </div>
            )}
            {trade.session && (
              <div className="stat-item !p-2 text-center">
                <div className="text-th-dim">Session</div>
                <div className="font-bold font-mono text-accent-orange">{trade.session}</div>
              </div>
            )}
          </div>

          {trade.pattern && (
            <div className="stat-item !p-2">
              <div className="flex items-center gap-1 text-[9px] text-th-dim"><Shield size={8} />Pattern</div>
              <div className="text-xs text-th-secondary mt-0.5">{trade.pattern}</div>
            </div>
          )}

          {/* Personal notes */}
          <div className="stat-item !p-2">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1 text-[9px] text-th-dim"><StickyNote size={8} />Notatka</div>
              {!noteSaved && (
                <button onClick={handleSaveNote}
                  className="flex items-center gap-0.5 text-[9px] text-accent-green hover:underline">
                  <Save size={8} />Zapisz
                </button>
              )}
            </div>
            <textarea
              value={note}
              onChange={e => { setNote(e.target.value); setNoteSaved(false); }}
              onBlur={handleSaveNote}
              placeholder="Dodaj notatke do tej transakcji..."
              rows={2}
              className="w-full bg-dark-tertiary border border-dark-secondary rounded px-2 py-1 text-[10px] text-th-secondary outline-none resize-none focus:border-accent-blue/40"
            />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 text-[10px] text-th-dim">
              <Clock size={9} />
              {(() => {
                let iso = trade.timestamp.trim();
                iso = iso.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/, '$1T$2');
                if (!/[Zz+-]/.test(iso.slice(-6))) {iso += 'Z';}
                const d = new Date(iso);
                return isNaN(d.getTime()) ? trade.timestamp : d.toLocaleString('pl-PL');
              })()}
            </div>
            <button
              onClick={copyToClipboard}
              className="flex items-center gap-1 px-2 py-1 rounded text-[9px] text-accent-blue hover:bg-accent-blue/10 transition-colors"
              title="Kopiuj podsumowanie"
            >
              <Copy size={9} />
              Kopiuj
            </button>
          </div>
        </div>
      </div>
    </>
  );
});
