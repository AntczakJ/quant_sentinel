/**
 * src/components/dashboard/PortfolioStats.tsx - Portfolio performance statistics
 */

import { useEffect, useState } from 'react';
import { useTradingStore } from '../../store/tradingStore';
import { portfolioAPI, analysisAPI } from '../../api/client';
import type { Portfolio } from '../../types/trading';
import { Wallet, Edit2, Plus } from 'lucide-react';

export function PortfolioStats() {
  const { setPortfolio } = useTradingStore();
  const [portfolio, setPortfolioState] = useState<Portfolio | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showEditBalance, setShowEditBalance] = useState(false);
  const [newBalance, setNewBalance] = useState('');

  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await portfolioAPI.getStatus();
        setPortfolioState(data);
        setPortfolio(data);
        // Only initialize newBalance if NOT editing
        if (!showEditBalance && !newBalance) {
          setNewBalance(data.balance.toString());
        }
      } catch (err) {
        console.error('Error fetching portfolio:', err);
        setError('Failed to load portfolio');
      } finally {
        setLoading(false);
      }
    };

    fetchPortfolio();

    // Refresh every 5 seconds, but SKIP if user is editing balance
    const interval = setInterval(() => {
      if (!showEditBalance) {
        fetchPortfolio();
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [setPortfolio, showEditBalance]);

  const handleBalanceUpdate = async () => {
    try {
      const amount = parseFloat(newBalance);
      if (isNaN(amount) || amount <= 0) {
        alert('❌ Podaj poprawną kwotę');
        return;
      }

      // Call API to update balance
      const result = await portfolioAPI.updateBalance(amount);

      if (result.success) {
        // Update local state
        setPortfolioState(prev => prev ? {
          ...prev,
          balance: amount,
          initial_balance: amount,
          equity: amount,
          pnl: 0
        } : null);

        alert(`✅ ${result.message}`);
        setShowEditBalance(false);
      } else {
        alert('❌ Błąd podczas aktualizacji');
      }
    } catch (err) {
      console.error('Error updating balance:', err);
      alert('❌ Błąd podczas aktualizacji');
    }
  };

  if (loading && !portfolio) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <span>Loading portfolio...</span>
      </div>
    );
  }

  if (error && !portfolio) {
    return (
      <div className="flex items-center justify-center h-40 bg-red-900/10 border border-red-500/30 rounded-lg">
        <div className="flex items-center gap-2 text-red-400">
          <span>{error}</span>
        </div>
      </div>
    );
  }

  if (!portfolio) return null;

  const pnlIsPositive = portfolio.pnl >= 0;
  const performanceColor = pnlIsPositive ? 'text-accent-green' : 'text-accent-red';
  const performanceIcon = pnlIsPositive ? '📈' : '📉';
  const performanceBg = pnlIsPositive ? 'bg-green-900/10' : 'bg-red-900/10';
  const performanceBorder = pnlIsPositive ? 'border-green-500/30' : 'border-red-500/30';

  const returnPercentage = ((portfolio.pnl / portfolio.initial_balance) * 100).toFixed(2);

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-400 font-bold flex items-center gap-2">
          <Wallet size={14} />
          PORTFOLIO STATUS
        </div>
        <button
          onClick={async () => {
            try {
              // Pobierz bieżącą analizę QUANT PRO
              const analysis = await analysisAPI.getQuantPro();

              if (!analysis || !analysis.position) {
                alert('❌ Nie udało się pobrać analizy');
                return;
              }

              const pos = analysis.position;

              // Dodaj trade na podstawie analizy
              const result = await portfolioAPI.addTrade({
                direction: pos.direction || 'LONG',
                entry: pos.entry || 2050,
                sl: pos.stop_loss || 2045,
                tp: pos.take_profit || 2055,
                lot_size: pos.lot_size || 0.1,
                logic: `${pos.pattern} - ${pos.logic}`
              });

              alert(`✅ Trade ${result.direction} @ ${result.entry} dodany! (ID: ${result.trade_id})`);
            } catch (err) {
              alert(`❌ Błąd: ${err instanceof Error ? err.message : 'Nieznany błąd'}`);
              console.error('Error adding trade:', err);
            }
          }}
          className="text-xs bg-accent-green/20 hover:bg-accent-green/30 border border-accent-green/50 rounded px-2 py-1 text-accent-green transition flex items-center gap-1"
          title="Add trade from current analysis"
        >
          <Plus size={12} />
          Add Trade
        </button>
      </div>

      {/* Balance */}
      <div className="bg-dark-bg border border-dark-secondary rounded p-3">
        <div className="flex items-center justify-between mb-1">
          <div className="text-xs text-gray-400">Balance</div>
          <button
            onClick={() => setShowEditBalance(!showEditBalance)}
            className="text-xs text-gray-500 hover:text-accent-blue transition"
            title="Edit balance"
          >
            <Edit2 size={12} className="inline" />
          </button>
        </div>

        {showEditBalance ? (
          <div className="flex gap-2">
            <input
              type="number"
              value={newBalance}
              onChange={(e) => setNewBalance(e.target.value)}
              className="flex-1 bg-dark-surface border border-dark-secondary rounded px-2 py-1 text-sm text-white"
              placeholder="Enter amount"
            />
            <button
              onClick={handleBalanceUpdate}
              className="bg-accent-green/20 hover:bg-accent-green/30 border border-accent-green/50 rounded px-2 py-1 text-xs text-accent-green transition"
            >
              ✓
            </button>
            <button
              onClick={() => setShowEditBalance(false)}
              className="bg-accent-red/20 hover:bg-accent-red/30 border border-accent-red/50 rounded px-2 py-1 text-xs text-accent-red transition"
            >
              ✕
            </button>
          </div>
        ) : (
          <>
            <div className="text-2xl font-bold text-accent-green">
              {portfolio?.balance.toFixed(2)} PLN
            </div>
            <div className="text-xs text-gray-500 mt-1">
              Initial: {portfolio?.initial_balance.toFixed(2)} PLN
            </div>
          </>
        )}
      </div>

       {/* Equity */}
       <div className="bg-dark-bg border border-dark-secondary rounded p-3">
         <div className="text-xs text-gray-400 mb-1">Total Equity</div>
         <div className="text-2xl font-bold text-accent-blue">
           {portfolio.equity.toFixed(2)} PLN
         </div>
       </div>

      {/* P&L */}
      <div className={`${performanceBg} border ${performanceBorder} rounded p-3`}>
        <div className="text-xs text-gray-400 mb-2">Profit / Loss</div>
        <div className="flex items-end justify-between">
          <div>
            <div className={`text-2xl font-bold ${performanceColor}`}>
              {performanceIcon} {pnlIsPositive ? '+' : ''}{portfolio.pnl.toFixed(2)}
            </div>
            <div className={`text-sm font-semibold ${performanceColor} mt-1`}>
              {pnlIsPositive ? '+' : ''}{returnPercentage}%
            </div>
          </div>
          <div className="text-4xl opacity-20">{performanceIcon}</div>
        </div>
      </div>

      {/* Position Info */}
      {portfolio.has_position ? (
        <div className="bg-dark-bg border border-accent-blue/30 rounded p-3">
          <div className="text-xs text-gray-400 mb-2">Active Position</div>
          <div className="flex items-center justify-between mb-2">
            <span className={`text-sm font-semibold ${
              portfolio.position_type === 'LONG' ? 'text-accent-green' : 'text-accent-red'
            }`}>
              {portfolio.position_type === 'LONG' ? '📈 LONG' : '📉 SHORT'}
            </span>
            <span className="text-xs text-gray-400">Entry: ${portfolio.position_entry?.toFixed(2)}</span>
          </div>
          <div className={`text-sm font-bold ${
            (portfolio.position_unrealized_pnl ?? 0) >= 0 ? 'text-accent-green' : 'text-accent-red'
          }`}>
            Unrealized: {(portfolio.position_unrealized_pnl ?? 0) >= 0 ? '+' : ''}{portfolio.position_unrealized_pnl?.toFixed(2)}
          </div>
        </div>
      ) : (
        <div className="bg-dark-bg border border-dark-secondary rounded p-3 text-center">
          <div className="text-xs text-gray-400">⏸️ No Active Position</div>
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-dark-bg border border-dark-secondary rounded p-2">
          <div className="text-gray-400 mb-1">Return on Equity</div>
          <div className={`font-bold ${pnlIsPositive ? 'text-accent-green' : 'text-accent-red'}`}>
            {((portfolio.pnl / portfolio.initial_balance) * 100).toFixed(2)}%
          </div>
        </div>
        <div className="bg-dark-bg border border-dark-secondary rounded p-2">
          <div className="text-gray-400 mb-1">Win Rate</div>
          <div className="text-accent-blue font-bold">-</div>
        </div>
      </div>
    </div>
  );
}

