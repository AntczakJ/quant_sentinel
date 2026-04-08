/**
 * src/components/dashboard/PortfolioStats.tsx - Portfolio performance
 */

import { useEffect, useState, memo } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { portfolioAPI, signalsAPI } from '../../api/client';
import type { Portfolio } from '../../types/trading';
import { Edit2, Plus, Loader2 } from 'lucide-react';

export const PortfolioStats = memo(function PortfolioStats() {
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
      console.error('Error fetching portfolio:', err);
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
      if (isNaN(amount) || amount <= 0) { alert('Invalid amount'); return; }
      const result = await portfolioAPI.updateBalance(amount);
      if (result.success) {
        setPortfolioState(prev => prev ? { ...prev, balance: amount, initial_balance: amount, equity: amount, pnl: 0 } : null);
        alert(`✅ ${result.message}`);
        setShowEditBalance(false);
        void refreshPortfolio();
      }
    } catch (err) {
      console.error('Error updating balance:', err);
      alert('Update failed');
    }
  };

  const handleAddTrade = async () => {
    if (addingTrade) {return;}
    try {
      setAddingTrade(true);
      const result = await portfolioAPI.quickTrade();
      if (result.direction === 'WAIT' || result.success === false) {
        alert(result.message || 'No setup — market waiting.');
        return;
      }
      if (result.success) {
        alert(`Trade ${result.direction} @ ${result.entry}\nSL: ${result.sl} | TP: ${result.tp}`);
      } else {
        alert(result.message || 'Error adding trade');
      }
    } catch (err) {
      alert(`Error: ${err instanceof Error ? err.message : 'Unknown'}`);
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
    <div className="space-y-2.5">
      {/* Header with Add Trade */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wider">Status</span>
        <button
          onClick={() => { void handleAddTrade(); }}
          disabled={addingTrade}
          className="text-xs bg-green-600/15 hover:bg-green-600/25 border border-green-600/30 rounded px-2 py-0.5 text-green-400 transition flex items-center gap-1 disabled:opacity-50"
        >
          {addingTrade ? <Loader2 size={10} className="animate-spin" /> : <Plus size={10} />}
          {addingTrade ? 'Wait...' : 'Trade'}
        </button>
      </div>

      {/* Balance */}
      <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">Balance</span>
          <button onClick={() => setShowEditBalance(!showEditBalance)} className="text-gray-600 hover:text-gray-400">
            <Edit2 size={10} />
          </button>
        </div>
        {showEditBalance ? (
          <div className="flex gap-1.5">
            <input type="number" value={newBalance} onChange={e => setNewBalance(e.target.value)}
              className="flex-1 bg-dark-secondary border border-dark-secondary rounded px-2 py-1 text-xs text-white" />
            <button onClick={() => { void handleBalanceUpdate(); }}
              className="text-xs text-green-400 bg-green-600/15 px-2 rounded">✓</button>
            <button onClick={() => setShowEditBalance(false)}
              className="text-xs text-red-400 bg-red-600/15 px-2 rounded">✕</button>
          </div>
        ) : (
          <>
            <div className="text-xl font-bold text-green-400 font-mono">{portfolio.balance.toFixed(2)} PLN</div>
            <div className="text-xs text-gray-600 mt-0.5">Initial: {portfolio.initial_balance.toFixed(2)}</div>
          </>
        )}
      </div>

      {/* Equity */}
      <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary">
        <div className="text-xs text-gray-500 mb-0.5">Equity</div>
        <div className="text-xl font-bold text-blue-400 font-mono">{portfolio.equity.toFixed(2)} PLN</div>
      </div>

      {/* P&L */}
      <div className={`rounded p-2.5 border ${pnlPositive ? 'bg-green-950/10 border-green-600/20' : 'bg-red-950/10 border-red-600/20'}`}>
        <div className="text-xs text-gray-500 mb-1">P&L</div>
        <div className={`text-xl font-bold ${pnlColor} font-mono`}>
          {pnlPositive ? '+' : ''}{portfolio.pnl.toFixed(2)}
        </div>
        <div className={`text-xs font-medium ${pnlColor}`}>{pnlPositive ? '+' : ''}{returnPct}%</div>
      </div>

      {/* Position */}
      {portfolio.has_position ? (
        <div className="bg-dark-bg rounded p-2.5 border border-blue-600/20">
          <div className="text-xs text-gray-500 mb-1">Active Position</div>
          <div className="flex items-center justify-between">
            <span className={`text-sm font-semibold ${portfolio.position_type === 'LONG' ? 'text-green-400' : 'text-red-400'}`}>
              {portfolio.position_type}
            </span>
            <span className="text-xs text-gray-500 font-mono">${portfolio.position_entry?.toFixed(2)}</span>
          </div>
          <div className={`text-xs font-bold mt-1 ${(portfolio.position_unrealized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            Unrealized: {(portfolio.position_unrealized_pnl ?? 0) >= 0 ? '+' : ''}{portfolio.position_unrealized_pnl?.toFixed(2)}
          </div>
        </div>
      ) : (
        <div className="bg-dark-bg rounded p-2.5 border border-dark-secondary text-center text-xs text-gray-600">
          No Active Position
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-dark-bg rounded p-2 border border-dark-secondary">
          <div className="text-gray-500 mb-0.5">ROE</div>
          <div className={`font-bold ${pnlPositive ? 'text-green-400' : 'text-red-400'}`}>{returnPct}%</div>
        </div>
        <div className="bg-dark-bg rounded p-2 border border-dark-secondary">
          <div className="text-gray-500 mb-0.5">Win Rate</div>
          <div className={`font-bold ${winRate != null ? (winRate >= 50 ? 'text-green-400' : 'text-red-400') : 'text-gray-600'}`}>
            {winRate != null ? `${winRate.toFixed(1)}%` : '—'}
          </div>
        </div>
      </div>
    </div>
  );
});
