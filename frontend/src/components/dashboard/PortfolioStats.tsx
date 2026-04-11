/**
 * src/components/dashboard/PortfolioStats.tsx - Portfolio performance
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { portfolioAPI, signalsAPI } from '../../api/client';
import type { Portfolio } from '../../types/trading';
import { Edit2, Plus, Loader2 } from 'lucide-react';
import { useToast } from '../ui/Toast';
import { AnimatedNumber } from '../ui/AnimatedNumber';

export const PortfolioStats = memo(function PortfolioStats() {
  const toast = useToast();
  const { portfolio: storePortfolio, setPortfolio, apiConnected } = useTradingStore();
  const [portfolio, setPortfolioState] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showEditBalance, setShowEditBalance] = useState(false);
  const [newBalance, setNewBalance] = useState('');
  const [addingTrade, setAddingTrade] = useState(false);
  const [winRate, setWinRate] = useState<number | null>(null);

  // Use Zustand store data from App.tsx polling — avoids duplicate requests
  useEffect(() => {
    if (storePortfolio) {
      setPortfolioState(storePortfolio);
      if (!showEditBalance && !newBalance) {setNewBalance(storePortfolio.balance.toString());}
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storePortfolio]);

  // Only fetch independently after balance edit to get updated data immediately
  const refreshPortfolio = async () => {
    try {
      setError(null);
      const data = await portfolioAPI.getStatus();
      setPortfolioState(data);
      setPortfolio(data);
    } catch (err) {
      toast.error('Failed to load portfolio');
      setError('Failed to load portfolio');
    }
  };

  // Fallback: if store is empty after 2s, fetch directly (first load)
  useEffect(() => {
    if (!apiConnected) return;
    if (storePortfolio) { setLoading(false); return; }
    const timer = setTimeout(() => {
      if (!storePortfolio) {void refreshPortfolio().finally(() => setLoading(false));}
    }, 2000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiConnected]);

  // Win rate — stagger by 1.5s to avoid request burst on mount
  useEffect(() => {
    if (!apiConnected) return;
    const fetchWinRate = async () => {
      try {
        const stats = await signalsAPI.getStats();
        if (stats.total > 0) {setWinRate(stats.win_rate * 100);}
      } catch { /* ignore */ }
    };
    const initTimer = setTimeout(() => void fetchWinRate(), 1500);
    const interval = setInterval(fetchWinRate, 60000);
    return () => { clearTimeout(initTimer); clearInterval(interval); };
  }, [apiConnected]);

  const handleBalanceUpdate = async () => {
    try {
      const amount = parseFloat(newBalance);
      if (isNaN(amount) || amount <= 0) { toast.warning('Invalid amount'); return; }
      const result = await portfolioAPI.updateBalance(amount);
      if (result.success) {
        setPortfolioState(prev => prev ? { ...prev, balance: amount, initial_balance: amount, equity: amount, pnl: 0 } : null);
        toast.success(result.message || 'Balance updated');
        setShowEditBalance(false);
        void refreshPortfolio();
      }
    } catch (err) {
      toast.error('Balance update failed');
    }
  };

  const handleAddTrade = async () => {
    if (addingTrade) {return;}
    try {
      setAddingTrade(true);
      const result = await portfolioAPI.quickTrade();
      if (result.direction === 'WAIT' || !result.success) {
        toast.info(result.message || 'No setup — market waiting.');
        return;
      }
      if (result.success) {
        toast.success(`Trade ${result.direction} @ ${result.entry} | SL: ${result.sl} | TP: ${result.tp}`);
      } else {
        toast.error(result.message || 'Error adding trade');
      }
    } catch (err) {
      toast.error(`Error: ${err instanceof Error ? err.message : 'Unknown'}`);
    } finally {
      setAddingTrade(false);
    }
  };

  if (loading && !portfolio) {
    return (
      <div className="space-y-4">
        <div className="skeleton-shimmer h-5 w-16 rounded" />
        <div className="grid grid-cols-2 gap-3">
          <div className="skeleton-shimmer h-20 rounded-lg" />
          <div className="skeleton-shimmer h-20 rounded-lg" />
        </div>
        <div className="skeleton-shimmer h-24 rounded-xl" />
        <div className="grid grid-cols-2 gap-3">
          <div className="skeleton-shimmer h-14 rounded-lg" />
          <div className="skeleton-shimmer h-14 rounded-lg" />
        </div>
      </div>
    );
  }
  if (error && !portfolio) {
    return <div className="flex items-center justify-center h-32 text-accent-red text-xs">{error}</div>;
  }
  if (!portfolio) {return null;}

  const pnlPositive = portfolio.pnl >= 0;
  const pnlColor = pnlPositive ? 'text-accent-green' : 'text-accent-red';
  const returnPct = portfolio.initial_balance > 0
    ? ((portfolio.pnl / portfolio.initial_balance) * 100).toFixed(2)
    : '0.00';

  return (
    <div className="space-y-4">
      {/* Header with Add Trade */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-th-muted font-medium uppercase tracking-widest">Status</span>
        <button
          onClick={() => { void handleAddTrade(); }}
          disabled={addingTrade}
          className="text-[11px] bg-accent-green/10 hover:bg-accent-green/20 border border-accent-green/25 rounded-lg px-3 py-1 text-accent-green transition-all duration-200 flex items-center gap-1.5 disabled:opacity-50"
        >
          {addingTrade ? <Loader2 size={11} className="animate-spin" /> : <Plus size={11} />}
          {addingTrade ? 'Wait...' : 'Quick Trade'}
        </button>
      </div>

      {/* Balance + Equity row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Balance */}
        <div className="stat-item">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-th-muted font-medium uppercase tracking-widest">Balance</span>
            <button onClick={() => setShowEditBalance(!showEditBalance)} className="text-th-dim hover:text-th-secondary transition-colors">
              <Edit2 size={10} />
            </button>
          </div>
          {showEditBalance ? (
            <div className="flex gap-1.5">
              <input type="number" value={newBalance} onChange={e => setNewBalance(e.target.value)}
                className="flex-1 bg-dark-tertiary border border-dark-secondary rounded-lg px-2.5 py-1.5 text-xs text-th focus:border-accent-blue/50 outline-none transition-colors" />
              <button onClick={() => { void handleBalanceUpdate(); }}
                className="text-xs text-accent-green bg-accent-green/10 hover:bg-accent-green/20 px-2.5 rounded-lg transition-colors">OK</button>
              <button onClick={() => setShowEditBalance(false)}
                className="text-xs text-accent-red bg-accent-red/10 hover:bg-accent-red/20 px-2.5 rounded-lg transition-colors">X</button>
            </div>
          ) : (
            <>
              <AnimatedNumber value={portfolio.balance} decimals={2} suffix=" PLN" className="text-xl font-bold text-accent-green font-mono tracking-tight" />
              <div className="text-[10px] text-th-dim mt-1">Initial: {portfolio.initial_balance.toFixed(2)}</div>
            </>
          )}
        </div>

        {/* Equity */}
        <div className="stat-item">
          <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1.5">Equity</div>
          <AnimatedNumber value={portfolio.equity} decimals={2} suffix=" PLN" className="text-xl font-bold text-accent-blue font-mono tracking-tight" />
        </div>
      </div>

      {/* P&L */}
      <div className={`rounded-xl p-4 border ${pnlPositive ? 'bg-accent-green/5 border-accent-green/15' : 'bg-accent-red/5 border-accent-red/15'}`}>
        <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1.5">P&L</div>
        <div className="flex items-end justify-between">
          <AnimatedNumber value={portfolio.pnl} decimals={2} prefix={pnlPositive ? '+' : ''} className={`text-2xl font-bold ${pnlColor} font-mono tracking-tight`} />
          <div className={`text-sm font-semibold ${pnlColor} font-mono`}>{pnlPositive ? '+' : ''}{returnPct}%</div>
        </div>
      </div>

      {/* Position */}
      {portfolio.has_position ? (
        <div className="stat-item !border-accent-blue/20">
          <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-2">Aktywna Pozycja</div>
          <div className="flex items-center justify-between">
            <span className={`text-base font-bold ${portfolio.position_type === 'LONG' ? 'text-accent-green' : 'text-accent-red'}`}>
              {portfolio.position_type}
            </span>
            <span className="text-xs text-th-muted font-mono">${portfolio.position_entry?.toFixed(2)}</span>
          </div>
          <div className={`text-sm font-bold mt-1.5 font-mono ${(portfolio.position_unrealized_pnl ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red'}`}>
            Niezreal.: {(portfolio.position_unrealized_pnl ?? 0) >= 0 ? '+' : ''}{portfolio.position_unrealized_pnl?.toFixed(2)}
          </div>
        </div>
      ) : (
        <div className="stat-item text-center">
          <span className="text-xs text-th-dim">Brak aktywnej pozycji</span>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3">
        <div className="stat-item">
          <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1">ROE</div>
          <div className={`text-base font-bold font-mono ${pnlPositive ? 'text-accent-green' : 'text-accent-red'}`}>{returnPct}%</div>
        </div>
        <div className="stat-item">
          <div className="text-[10px] text-th-muted font-medium uppercase tracking-widest mb-1">Win Rate</div>
          <div className={`text-base font-bold font-mono ${winRate != null ? (winRate >= 50 ? 'text-accent-green' : 'text-accent-red') : 'text-th-dim'}`}>
            {winRate != null ? `${winRate.toFixed(1)}%` : '--'}
          </div>
        </div>
      </div>
    </div>
  );
});
