#!/usr/bin/env python3
"""
backtest_harness.py — walk-forward strategy backtesting on historical data.

Usage:
  python backtest_harness.py                           # example SMA crossover strategy
  python backtest_harness.py --symbol GC=F --period 1y
  python backtest_harness.py --strategy rsi --symbol EURUSD=X

Or as a library:
  from backtest_harness import BacktestEngine, rsi_strategy
  engine = BacktestEngine(df, strategy=rsi_strategy)
  result = engine.run()
  print(result.summary())

Models ATR-based SL (1.5x ATR) + 2.5R TP. Applies vol-aware slippage
from RiskManager. Checks bar-by-bar SL/TP hits.

Strategy function signature:
  strategy(df: pd.DataFrame, i: int) -> str | None
Returns 'LONG', 'SHORT', or None (no signal). `i` is current bar index;
strategy may only use df.iloc[:i+1] (no look-ahead).
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ── Trade record ──────────────────────────────────────────────────────────

@dataclass
class Trade:
    entry_idx: int
    direction: str
    entry_price: float
    sl: float
    tp: float
    exit_idx: Optional[int] = None
    exit_price: Optional[float] = None
    status: str = "OPEN"  # OPEN | WIN | LOSS | BREAKEVEN
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: List[float]
    initial_balance: float

    @property
    def final_balance(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.initial_balance

    @property
    def total_return_pct(self) -> float:
        return (self.final_balance / self.initial_balance - 1) * 100

    @property
    def closed_trades(self) -> List[Trade]:
        return [t for t in self.trades if t.status != "OPEN"]

    @property
    def win_rate(self) -> float:
        closed = self.closed_trades
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t.status == "WIN")
        return wins / len(closed) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        eq = np.asarray(self.equity_curve, dtype=np.float64)
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak
        return float(dd.min()) * 100

    @property
    def profit_factor(self) -> float:
        wins = sum(t.pnl_pct for t in self.closed_trades if t.pnl_pct > 0)
        losses = -sum(t.pnl_pct for t in self.closed_trades if t.pnl_pct < 0)
        return (wins / losses) if losses > 0 else float("inf") if wins > 0 else 0.0

    def summary(self) -> str:
        closed = self.closed_trades
        lines = [
            "=" * 60,
            "BACKTEST RESULTS",
            "=" * 60,
            f"  Total return:    {self.total_return_pct:+.2f}%",
            f"  Final balance:   ${self.final_balance:.2f} (from ${self.initial_balance:.2f})",
            f"  Trades:          {len(closed)} closed / {len(self.trades)} total",
            f"  Win rate:        {self.win_rate:.1f}%",
            f"  Profit factor:   {self.profit_factor:.2f}",
            f"  Max drawdown:    {self.max_drawdown_pct:+.2f}%",
            "=" * 60,
        ]
        return "\n".join(lines)


# ── Engine ────────────────────────────────────────────────────────────────

class BacktestEngine:
    """Walk-forward bar-by-bar backtester.

    Parameters
    ----------
    df : DataFrame with columns open/high/low/close
    strategy : callable(df, i) -> 'LONG'|'SHORT'|None
    initial_balance : starting capital (default 10000)
    risk_per_trade : fraction of balance risked per trade (default 0.01)
    sl_atr_mult : SL distance in ATR units (default 1.5)
    target_rr : target risk:reward ratio (default 2.5)
    use_slippage : apply vol-aware slippage from RiskManager (default True)
    """
    def __init__(
        self,
        df: pd.DataFrame,
        strategy: Callable[[pd.DataFrame, int], Optional[str]],
        initial_balance: float = 10_000.0,
        risk_per_trade: float = 0.01,
        sl_atr_mult: float = 1.5,
        target_rr: float = 2.5,
        atr_period: int = 14,
        use_slippage: bool = True,
        warmup: int = 50,
    ):
        self.df = df.reset_index(drop=True)
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.sl_atr_mult = sl_atr_mult
        self.target_rr = target_rr
        self.atr_period = atr_period
        self.use_slippage = use_slippage
        self.warmup = warmup

        # Pre-compute ATR series for SL/TP + slippage scaling
        self._atr = self._compute_atr()

    def _compute_atr(self) -> np.ndarray:
        n = len(self.df)
        high = self.df["high"].to_numpy()
        low = self.df["low"].to_numpy()
        close = self.df["close"].to_numpy()
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i] - low[i],
                        abs(high[i] - close[i - 1]),
                        abs(low[i] - close[i - 1]))
        atr = np.zeros(n)
        for i in range(self.atr_period, n):
            atr[i] = np.mean(tr[i - self.atr_period + 1:i + 1])
        if self.atr_period < n:
            atr[:self.atr_period] = atr[self.atr_period]
        return atr

    def _apply_slippage(self, entry: float, sl: float, tp: float,
                        direction: str, atr: float) -> tuple:
        if not self.use_slippage:
            return entry, sl, tp
        try:
            from src.trading.risk_manager import get_risk_manager
            rm = get_risk_manager()
            return rm.adjust_for_slippage(entry, sl, tp, direction, atr=atr)
        except Exception:
            return entry, sl, tp

    def run(self) -> BacktestResult:
        trades: List[Trade] = []
        balance = self.initial_balance
        equity = [balance]
        open_trade: Optional[Trade] = None

        close = self.df["close"].to_numpy()
        high = self.df["high"].to_numpy()
        low = self.df["low"].to_numpy()

        for i in range(self.warmup, len(self.df) - 1):
            # 1. Check open trade for SL/TP hit on this bar
            if open_trade is not None:
                bar_high = high[i]
                bar_low = low[i]
                if open_trade.direction == "LONG":
                    if bar_high >= open_trade.tp:
                        open_trade.exit_idx = i
                        open_trade.exit_price = open_trade.tp
                        open_trade.status = "WIN"
                        open_trade.pnl_pct = (open_trade.tp / open_trade.entry_price - 1) * 100
                    elif bar_low <= open_trade.sl:
                        open_trade.exit_idx = i
                        open_trade.exit_price = open_trade.sl
                        open_trade.status = "LOSS"
                        open_trade.pnl_pct = (open_trade.sl / open_trade.entry_price - 1) * 100
                else:  # SHORT
                    if bar_low <= open_trade.tp:
                        open_trade.exit_idx = i
                        open_trade.exit_price = open_trade.tp
                        open_trade.status = "WIN"
                        open_trade.pnl_pct = (open_trade.entry_price / open_trade.tp - 1) * 100
                    elif bar_high >= open_trade.sl:
                        open_trade.exit_idx = i
                        open_trade.exit_price = open_trade.sl
                        open_trade.status = "LOSS"
                        open_trade.pnl_pct = (open_trade.entry_price / open_trade.sl - 1) * 100
                if open_trade.status != "OPEN":
                    # Closed this bar — fixed-fraction sizing (vol_normalize-equivalent)
                    balance *= (1 + open_trade.pnl_pct / 100 * self.risk_per_trade * 100)
                    open_trade = None

            equity.append(balance)

            # 2. If flat, consult strategy for new entry
            if open_trade is None:
                signal = self.strategy(self.df, i)
                if signal in ("LONG", "SHORT"):
                    entry = close[i]
                    atr = self._atr[i]
                    if atr <= 0:
                        continue
                    sl_dist = max(atr * self.sl_atr_mult, entry * 0.002)
                    tp_dist = sl_dist * self.target_rr
                    if signal == "LONG":
                        sl = entry - sl_dist
                        tp = entry + tp_dist
                    else:
                        sl = entry + sl_dist
                        tp = entry - tp_dist
                    entry, sl, tp = self._apply_slippage(entry, sl, tp, signal, atr)
                    open_trade = Trade(
                        entry_idx=i, direction=signal,
                        entry_price=entry, sl=sl, tp=tp,
                    )
                    trades.append(open_trade)

        return BacktestResult(
            trades=trades,
            equity_curve=equity,
            initial_balance=self.initial_balance,
        )


# ── Example strategies (pluggable) ────────────────────────────────────────

def sma_crossover_strategy(df: pd.DataFrame, i: int,
                           fast: int = 20, slow: int = 50) -> Optional[str]:
    """Classic SMA cross — proof-of-concept only. Don't trade live."""
    if i < slow + 1:
        return None
    close = df["close"]
    fast_now = close.iloc[i - fast:i].mean()
    slow_now = close.iloc[i - slow:i].mean()
    fast_prev = close.iloc[i - fast - 1:i - 1].mean()
    slow_prev = close.iloc[i - slow - 1:i - 1].mean()
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "LONG"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "SHORT"
    return None


def rsi_strategy(df: pd.DataFrame, i: int,
                 period: int = 14, oversold: float = 30,
                 overbought: float = 70) -> Optional[str]:
    """RSI mean-reversion — another reference strategy."""
    if i < period + 2:
        return None
    close = df["close"].iloc[i - period - 1:i + 1].to_numpy()
    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0).mean()
    losses = np.where(delta < 0, -delta, 0).mean()
    rs = gains / losses if losses > 0 else float("inf")
    rsi = 100 - (100 / (1 + rs))
    if rsi < oversold:
        return "LONG"
    if rsi > overbought:
        return "SHORT"
    return None


STRATEGIES = {"sma": sma_crossover_strategy, "rsi": rsi_strategy}


def _fetch_data(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Fetch OHLCV. Suppresses yfinance chatter."""
    import contextlib, io
    import yfinance as yf
    with contextlib.redirect_stderr(io.StringIO()), \
         contextlib.redirect_stdout(io.StringIO()):
        df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df is None or df.empty:
        raise SystemExit(f"Failed to fetch {symbol}")
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    return df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="GC=F")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--strategy", default="sma", choices=list(STRATEGIES.keys()))
    ap.add_argument("--balance", type=float, default=10_000.0)
    ap.add_argument("--risk", type=float, default=0.01,
                    help="risk per trade as fraction of balance (default 0.01)")
    args = ap.parse_args()

    print(f"Loading {args.symbol} ({args.period}/{args.interval})...")
    df = _fetch_data(args.symbol, args.period, args.interval)
    print(f"  {len(df)} bars loaded")

    engine = BacktestEngine(
        df=df,
        strategy=STRATEGIES[args.strategy],
        initial_balance=args.balance,
        risk_per_trade=args.risk,
    )
    result = engine.run()
    print(f"\nStrategy: {args.strategy}")
    print(result.summary())


if __name__ == "__main__":
    main()
