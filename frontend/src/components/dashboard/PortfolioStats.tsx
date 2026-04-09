/**
 * src/components/dashboard/PortfolioStats.tsx - Portfolio performance
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { portfolioAPI, signalsAPI } from '../../api/client';
import type { Portfolio } from '../../types/trading';
import { Edit2, Plus, Loader2 } from 'lucide-react';
import { useToast } from '../ui/Toast';

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
    return <div className="flex items-center justify-center h-32 text-gray-500 text-sm">Loading portfolio...</div>;
  }
  if (error && !portfolio) {
    return <div className="flex items-center justify-center h-32 text-red-400 text-xs">{error}</div>;
  }
  if (!portfolio) {return null;}

  const pnlPositive = portfolio.pnl >= 0;
  const pnlColor = pnlPositive ? 'text-green-400' : 'text-red-400';
  const returnPct = ((portfolio.pnl / portfolio.initial_balance) * 100).toFixed(2);

  return (
    <div className="space-y-4">
      {/* Header with Add Trade */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-gray-500 font-medium uppercase tracking-widest">Status</span>
        <button
          onClick={() => { void handleAddTrade(); }}
          disabled={addingTrade}
          className="text-[11px] bg-green-600/10 hover:bg-green-600/20 border border-green-600/25 rounded-lg px-3 py-1 text-green-400 transition-all duration-200 flex items-center gap-1.5 disabled:opacity-50"
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
            <span className="text-[10px] text-gray-500 font-medium uppercase tracking-widest">Balance</span>
            <button onClick={() => setShowEditBalance(!showEditBalance)} className="text-gray-600 hover:text-gray-400 transition-colors">
              <Edit2 size={10} />
            </button>
          </div>
          {showEditBalance ? (
            <div className="flex gap-1.5">
              <input type="number" value={newBalance} onChange={e => setNewBalance(e.target.value)}
                className="flex-1 bg-[#141920] border border-[#1e2736] rounded-lg px-2.5 py-1.5 text-xs text-white focus:border-blue-500/50 outline-none transition-colors" />
              <button onClick={() => { void handleBalanceUpdate(); }}
                className="text-xs text-green-400 bg-green-600/10 hover:bg-green-600/20 px-2.5 rounded-lg transition-colors">OK</button>
              <button onClick={() => setShowEditBalance(false)}
                className="text-xs text-red-400 bg-red-600/10 hover:bg-red-600/20 px-2.5 rounded-lg transition-colors">X</button>
            </div>
          ) : (
            <>
              <div className="text-xl font-bold text-green-400 font-mono tracking-tight">{portfolio.balance.toFixed(2)} PLN</div>
              <div className="text-[10px] text-gray-600 mt-1">Initial: {portfolio.initial_balance.toFixed(2)}</div>
            </>
          )}
        </div>

        {/* Equity */}
        <div className="stat-item">
          <div className="text-[10px] text-gray-500 font-medium uppercase tracking-widest mb-1.5">Equity</div>
          <div className="text-xl font-bold text-blue-400 font-mono tracking-tight">{portfolio.equity.toFixed(2)} PLN</div>
        </div>
      </div>

      {/* P&L */}
      <div className={`rounded-xl p-4 border ${pnlPositive ? 'bg-green-950/8 border-green-600/15' : 'bg-red-950/8 border-red-600/15'}`}>
        <div className="text-[10px] text-gray-500 font-medium uppercase tracking-widest mb-1.5">P&L</div>
        <div className="flex items-end justify-between">
          <div className={`text-2xl font-bold ${pnlColor} font-mono tracking-tight`}>
            {pnlPositive ? '+' : ''}{portfolio.pnl.toFixed(2)}
          </div>
          <div className={`text-sm font-semibold ${pnlColor} font-mono`}>{pnlPositive ? '+' : ''}{returnPct}%</div>
        </div>
      </div>

      {/* Position */}
      {portfolio.has_position ? (
        <div className="stat-item !border-blue-600/20">
          <div className="text-[10px] text-gray-500 font-medium uppercase tracking-widest mb-2">Active Position</div>
          <div className="flex items-center justify-between">
            <span className={`text-base font-bold ${portfolio.position_type === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>
              {portfolio.position_type}
            </span>
            <span className="text-xs text-gray-500 font-mono">${portfolio.position_entry?.toFixed(2)}</span>
          </div>
          <div className={`text-sm font-bold mt-1.5 font-mono ${(portfolio.position_unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            Unrealized: {(portfolio.position_unrealized_pnl ?? 0) >= 0 ? '+' : ''}{portfolio.position_unrealized_pnl?.toFixed(2)}
          </div>
        </div>
      ) : (
        <div className="stat-item text-center">
          <span className="text-xs text-gray-600">No Active Position</span>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-3">
        <div className="stat-item">
          <div className="text-[10px] text-gray-500 font-medium uppercase tracking-widest mb-1">ROE</div>
          <div className={`text-base font-bold font-mono ${pnlPositive ? 'text-green-400' : 'text-red-400'}`}>{returnPct}%</div>
        </div>
        <div className="stat-item">
          <div className="text-[10px] text-gray-500 font-medium uppercase tracking-widest mb-1">Win Rate</div>
          <div className={`text-base font-bold font-mono ${winRate != null ? (winRate >= 50 ? 'text-green-400' : 'text-red-400') : 'text-gray-600'}`}>
            {winRate != null ? `${winRate.toFixed(1)}%` : '--'}
          </div>
        </div>
      </div>
    </div>
  );
});
