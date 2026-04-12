/**
 * src/components/dashboard/RiskCalculator.tsx — Position Size / Risk Calculator
 *
 * Trader inputs entry price, SL, and risk % of balance.
 * Calculator outputs: lot size, risk in $, reward if TP hit, R:R.
 * Auto-fills from live price and portfolio balance.
 */

import { memo, useState, useEffect, useMemo, useRef } from 'react';
import { Calculator, AlertTriangle, TrendingUp, TrendingDown, X } from 'lucide-react';
import { useTradingStore } from '../../store/tradingStore';

interface Props {
  onClose: () => void;
  /** Pre-fill entry price (e.g., from context menu) */
  initialPrice?: number;
}

const GOLD_PIP_VALUE = 0.01; // 1 pip = $0.01 for XAU/USD
const GOLD_CONTRACT_SIZE = 100; // 1 lot = 100 oz

export const RiskCalculator = memo(function RiskCalculator({ onClose, initialPrice }: Props) {
  const ticker = useTradingStore(s => s.ticker);
  const portfolio = useTradingStore(s => s.portfolio);

  const livePrice = ticker?.price ?? 0;
  const balance = portfolio?.balance ?? 10000;

  const [direction, setDirection] = useState<'LONG' | 'SHORT'>('LONG');
  const [entry, setEntry] = useState(initialPrice?.toFixed(2) ?? livePrice.toFixed(2));
  const [sl, setSl] = useState('');
  const [tp, setTp] = useState('');
  const [riskPct, setRiskPct] = useState('1.0');

  // Auto-fill entry from live price when user hasn't typed yet
  const userEditedEntry = useRef(Boolean(initialPrice));
  useEffect(() => {
    if (!userEditedEntry.current && livePrice > 0) {
      setEntry(livePrice.toFixed(2));
    }
  }, [livePrice]);

  // Auto-suggest SL and TP based on ATR-like distance
  const userEditedSl = useRef(false);
  useEffect(() => {
    const e = parseFloat(entry);
    if (!e || userEditedSl.current) {return;} // Don't overwrite manual SL
    const defaultRisk = e * 0.003; // 0.3% = ~$10 for gold
    if (direction === 'LONG') {
      setSl((e - defaultRisk).toFixed(2));
      setTp((e + defaultRisk * 2).toFixed(2));
    } else {
      setSl((e + defaultRisk).toFixed(2));
      setTp((e - defaultRisk * 2).toFixed(2));
    }
  }, [entry, direction]);

  const calc = useMemo(() => {
    const e = parseFloat(entry) || 0;
    const s = parseFloat(sl) || 0;
    const t = parseFloat(tp) || 0;
    const rPct = parseFloat(riskPct) || 1;

    if (!e || !s) {return null;}

    const riskPerOz = Math.abs(e - s); // $ risk per oz
    const rewardPerOz = t ? Math.abs(t - e) : 0;
    const riskDollars = (rPct / 100) * balance;
    const lotSize = riskPerOz > 0 ? riskDollars / (riskPerOz * GOLD_CONTRACT_SIZE) : 0;
    const rr = riskPerOz > 0 && rewardPerOz > 0 ? rewardPerOz / riskPerOz : 0;
    const rewardDollars = lotSize * rewardPerOz * GOLD_CONTRACT_SIZE;
    const pipDistance = riskPerOz / GOLD_PIP_VALUE;

    // Validate direction
    const isValid = direction === 'LONG' ? s < e : s > e;

    return {
      riskDollars,
      rewardDollars,
      lotSize,
      rr,
      pipDistance,
      riskPerOz,
      isValid,
    };
  }, [entry, sl, tp, riskPct, balance, direction]);

  return (
    <>
      <div className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[61] w-96 max-w-[90vw] rounded-xl border shadow-2xl overflow-hidden"
        style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex items-center gap-2">
            <Calculator size={14} className="text-accent-blue" />
            <span className="text-sm font-bold" style={{ color: 'var(--color-text-primary)' }}>Kalkulator Ryzyka</span>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-dark-secondary transition-colors" style={{ color: 'var(--color-text-muted)' }}>
            <X size={14} />
          </button>
        </div>

        <div className="px-4 py-3 space-y-3">
          {/* Direction toggle */}
          <div className="flex gap-2">
            <button
              onClick={() => setDirection('LONG')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-bold transition-all border ${
                direction === 'LONG'
                  ? 'bg-accent-green/15 text-accent-green border-accent-green/30'
                  : 'text-th-muted border-transparent hover:border-dark-secondary'
              }`}
            >
              <TrendingUp size={12} />
              LONG
            </button>
            <button
              onClick={() => setDirection('SHORT')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-bold transition-all border ${
                direction === 'SHORT'
                  ? 'bg-accent-red/15 text-accent-red border-accent-red/30'
                  : 'text-th-muted border-transparent hover:border-dark-secondary'
              }`}
            >
              <TrendingDown size={12} />
              SHORT
            </button>
          </div>

          {/* Inputs */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[9px] text-th-muted uppercase tracking-wider block mb-1">Entry Price</label>
              <input type="number" step="0.01" value={entry} onChange={e => { userEditedEntry.current = true; setEntry(e.target.value); }}
                className="w-full bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs font-mono text-th focus:border-accent-blue/50 outline-none" />
            </div>
            <div>
              <label className="text-[9px] text-th-muted uppercase tracking-wider block mb-1">Stop Loss</label>
              <input type="number" step="0.01" value={sl} onChange={e => { userEditedSl.current = true; setSl(e.target.value); }}
                className="w-full bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs font-mono text-accent-red focus:border-accent-red/50 outline-none" />
            </div>
            <div>
              <label className="text-[9px] text-th-muted uppercase tracking-wider block mb-1">Take Profit</label>
              <input type="number" step="0.01" value={tp} onChange={e => setTp(e.target.value)}
                className="w-full bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs font-mono text-accent-green focus:border-accent-green/50 outline-none" />
            </div>
            <div>
              <label className="text-[9px] text-th-muted uppercase tracking-wider block mb-1">Risk % of Balance</label>
              <input type="number" step="0.1" min="0.1" max="10" value={riskPct} onChange={e => setRiskPct(e.target.value)}
                className="w-full bg-dark-tertiary border border-dark-secondary rounded-lg px-3 py-1.5 text-xs font-mono text-accent-orange focus:border-accent-orange/50 outline-none" />
            </div>
          </div>

          {/* Balance info */}
          <div className="text-[10px] text-th-dim flex justify-between">
            <span>Balance: {balance.toFixed(2)} PLN</span>
            <span>Live: ${livePrice.toFixed(2)}</span>
          </div>

          {/* Results */}
          {calc && (
            <div className="space-y-2 pt-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
              {!calc.isValid && (
                <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-accent-red/10 border border-accent-red/20 text-accent-red text-[10px]">
                  <AlertTriangle size={10} />
                  SL jest po zlej stronie dla {direction}
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <div className="stat-item !p-2.5">
                  <div className="text-[9px] text-th-muted uppercase tracking-wider">Lot Size</div>
                  <div className="text-lg font-bold font-mono text-accent-blue">
                    {calc.lotSize.toFixed(2)}
                  </div>
                  <div className="text-[9px] text-th-dim">{(calc.lotSize * GOLD_CONTRACT_SIZE).toFixed(0)} oz</div>
                </div>
                <div className="stat-item !p-2.5">
                  <div className="text-[9px] text-th-muted uppercase tracking-wider">R:R Ratio</div>
                  <div className={`text-lg font-bold font-mono ${calc.rr >= 2 ? 'text-accent-green' : calc.rr >= 1 ? 'text-accent-orange' : 'text-accent-red'}`}>
                    {calc.rr > 0 ? calc.rr.toFixed(2) : '—'}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="stat-item !p-2">
                  <div className="text-[8px] text-th-dim">Risk</div>
                  <div className="text-xs font-bold font-mono text-accent-red">
                    ${calc.riskDollars.toFixed(2)}
                  </div>
                </div>
                <div className="stat-item !p-2">
                  <div className="text-[8px] text-th-dim">Reward</div>
                  <div className="text-xs font-bold font-mono text-accent-green">
                    ${calc.rewardDollars.toFixed(2)}
                  </div>
                </div>
                <div className="stat-item !p-2">
                  <div className="text-[8px] text-th-dim">Distance</div>
                  <div className="text-xs font-bold font-mono text-th-secondary">
                    {calc.pipDistance.toFixed(0)} pips
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
});
