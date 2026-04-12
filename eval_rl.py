#!/usr/bin/env python3
"""eval_rl.py - Evaluate (and optionally compare) trained RL agent(s) on fresh market data.

Usage:
  python eval_rl.py                                  # eval models/rl_agent.keras on default basket
  python eval_rl.py --model models/foo.keras         # eval specific model
  python eval_rl.py --compare models/a.keras models/b.keras   # side-by-side
  python eval_rl.py --symbols GC=F,EURUSD=X          # custom basket

Runs out-of-sample evaluation (last 30% of fetched data) with epsilon=0.
Reports per-symbol: return %, WR, trades, max drawdown, profit factor.
"""
import os
import sys
import argparse
import contextlib
import io

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import numpy as np
import pandas as pd
import yfinance as yf

from src.ml.rl_agent import TradingEnv, DQNAgent
from train_rl import SYMBOLS, INITIAL_BALANCE


def _fetch_eval_data(symbol):
    """Fetch data for evaluation. Uses 1h/2y (rate-limit friendly) with 1d/5y fallback.
    Swallows yfinance stderr/stdout to avoid cp1252 UnicodeEncodeError on Windows."""
    combos = [("2y", "1h"), ("1y", "1h"), ("5y", "1d"), ("2y", "1d")]
    for period, interval in combos:
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                df = yf.Ticker(symbol).history(period=period, interval=interval)
            if df is None or len(df) < 100:
                continue
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            required = ['open', 'high', 'low', 'close', 'volume']
            available = [c for c in required if c in df.columns]
            return df[available]
        except Exception:
            continue
    return None


def _eval_env_with_stats(agent, env):
    """Run a single epsilon=0 pass and collect detailed trade stats."""
    agent.epsilon = 0.0
    state = env.reset()
    done = False
    equity_curve = [env.balance]
    trade_returns = []
    prev_balance = env.balance
    prev_total_trades = 0
    info = {}
    while not done:
        action = agent.act(state)
        state, _, done, info = env.step(action)
        equity_curve.append(env.balance)
        if info.get('total_trades', 0) > prev_total_trades:
            trade_returns.append(env.balance - prev_balance)
            prev_balance = env.balance
            prev_total_trades = info['total_trades']

    equity = np.asarray(equity_curve, dtype=np.float64)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    gross_win = float(sum(wins))
    gross_loss = float(-sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf') if gross_win > 0 else 0.0

    balance = info.get('balance', INITIAL_BALANCE)
    ret_pct = (balance - INITIAL_BALANCE) / INITIAL_BALANCE * 100
    wr = info.get('win_rate', 0) * 100
    trades = info.get('total_trades', 0)

    return {
        'balance': balance,
        'return_pct': ret_pct,
        'win_rate': wr,
        'trades': trades,
        'max_dd_pct': max_dd * 100,
        'profit_factor': profit_factor,
        'avg_win': float(np.mean(wins)) if wins else 0.0,
        'avg_loss': float(np.mean(losses)) if losses else 0.0,
    }


def eval_model(model_path, symbols, oos_fraction=0.3):
    """Evaluate one model on out-of-sample slice of each symbol."""
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not os.path.exists(model_path + '.params'):
        raise FileNotFoundError(f"Params not found: {model_path}.params")

    agent = DQNAgent(state_size=22, action_size=3)
    agent.load(model_path)

    results = {}
    for sym in symbols:
        df = _fetch_eval_data(sym)
        if df is None or len(df) < 100:
            print(f"  Skipped {sym}: no usable data")
            continue
        n = len(df)
        split = int(n * (1 - oos_fraction))
        oos = df.iloc[split:].reset_index(drop=True)
        if len(oos) < 50:
            print(f"  Skipped {sym}: OOS slice too short ({len(oos)})")
            continue
        env = TradingEnv(oos, initial_balance=INITIAL_BALANCE, transaction_cost=0.001)
        results[sym] = _eval_env_with_stats(agent, env)
    return results


def print_report(label, results):
    print(f"\n=== {label} ===")
    if not results:
        print("  (no symbols evaluated)")
        return
    header = f"{'Symbol':<12} {'Return%':>9} {'WR%':>6} {'Trades':>7} {'MaxDD%':>8} {'PF':>6} {'AvgW':>8} {'AvgL':>8}"
    print(header)
    print('-' * len(header))
    rets, wrs = [], []
    for sym, r in results.items():
        rets.append(r['return_pct'])
        wrs.append(r['win_rate'])
        pf_str = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "inf"
        print(f"{sym:<12} {r['return_pct']:>+8.2f}% {r['win_rate']:>5.0f}% {r['trades']:>7d} "
              f"{r['max_dd_pct']:>+7.2f}% {pf_str:>6} {r['avg_win']:>+7.2f} {r['avg_loss']:>+7.2f}")
    print('-' * len(header))
    avg_ret = float(np.mean(rets)) if rets else 0.0
    avg_wr = float(np.mean(wrs)) if wrs else 0.0
    print(f"{'AVERAGE':<12} {avg_ret:>+8.2f}% {avg_wr:>5.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='models/rl_agent.keras', help='model path')
    ap.add_argument('--compare', nargs=2, metavar=('MODEL_A', 'MODEL_B'),
                    help='compare two models side by side')
    ap.add_argument('--symbols', default=','.join(SYMBOLS),
                    help='comma-separated symbols')
    ap.add_argument('--oos', type=float, default=0.3,
                    help='out-of-sample fraction (default 0.3)')
    args = ap.parse_args()

    syms = [s.strip() for s in args.symbols.split(',') if s.strip()]

    if args.compare:
        a_path, b_path = args.compare
        print(f"Fetching data for {len(syms)} symbols...")
        r_a = eval_model(a_path, syms, args.oos)
        r_b = eval_model(b_path, syms, args.oos)
        print_report(f"A: {a_path}", r_a)
        print_report(f"B: {b_path}", r_b)
        # Delta summary
        print("\n=== DELTA (B - A) ===")
        for sym in syms:
            if sym in r_a and sym in r_b:
                da = r_b[sym]['return_pct'] - r_a[sym]['return_pct']
                dwr = r_b[sym]['win_rate'] - r_a[sym]['win_rate']
                print(f"  {sym:<12} Return: {da:>+7.2f}pp  WR: {dwr:>+5.0f}pp")
    else:
        print(f"Fetching data for {len(syms)} symbols (OOS={args.oos:.0%})...")
        r = eval_model(args.model, syms, args.oos)
        print_report(args.model, r)


if __name__ == '__main__':
    main()
