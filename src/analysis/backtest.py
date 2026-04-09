"""
backtest.py — moduł backtestowy do oceny skuteczności modeli ML.

Funkcje:
- Replay bar-by-bar na danych historycznych
- Porównanie predykcji z rzeczywistym ruchem ceny
- Metryki: accuracy, precision, recall, F1, Sharpe, max drawdown
- Ocena poszczególnych modeli + ensemble

Optimized: vectorized metric computation via NumPy, GPU-accelerated where available.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from src.core.logger import logger
from src.analysis.compute import get_array_module, to_numpy


def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray) -> Dict:
    """
    Oblicz metryki klasyfikacji binarnej (fully vectorized).
    y_true, y_pred: 0 = spadek, 1 = wzrost
    Includes MCC (Matthews Correlation Coefficient) — better than F1 for imbalanced data.
    """
    xp = get_array_module()
    n = len(y_true)
    if n == 0:
        return {"accuracy": 0, "precision": 0, "recall": 0, "f1": 0, "mcc": 0}

    yt = xp.asarray(y_true)
    yp = xp.asarray(y_pred)

    correct = int((yt == yp).sum())
    accuracy = correct / n

    tp = int(((yp == 1) & (yt == 1)).sum())
    fp = int(((yp == 1) & (yt == 0)).sum())
    fn = int(((yp == 0) & (yt == 1)).sum())
    tn = int(((yp == 0) & (yt == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    # MCC: Matthews Correlation Coefficient — balanced metric for binary classification
    # MCC = (TP*TN - FP*FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN))
    denom = np.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    mcc = (tp * tn - fp * fn) / denom if denom > 0 else 0.0

    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mcc": round(mcc, 4),
        "total": n,
        "correct": correct,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def compute_equity_metrics(returns: np.ndarray) -> Dict:
    """
    Professional equity curve metrics:
    Sharpe, Sortino, Calmar, Max Drawdown, VaR (95%), Total Return.
    Fully vectorized — uses CuPy if GPU available for large arrays.
    """
    xp = get_array_module()
    if len(returns) == 0:
        return {"sharpe": 0, "sortino": 0, "calmar": 0, "max_drawdown": 0,
                "total_return": 0, "var_95": 0}

    ret = xp.asarray(returns)

    # Equity curve (vectorized cumulative product)
    equity = xp.cumprod(1 + ret)
    total_return = float(equity[-1] - 1)

    # Max drawdown (vectorized)
    peak = xp.maximum.accumulate(equity)
    drawdown = (peak - equity) / (peak + 1e-10)
    max_drawdown = float(drawdown.max())

    # Risk-free rate
    risk_free_daily = 0.05 / 252

    mean_ret = float(xp.mean(ret))
    std_ret = float(xp.std(ret))
    excess_ret = mean_ret - risk_free_daily

    # Sharpe ratio
    sharpe = (excess_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0

    # Sortino ratio (penalizes downside volatility only)
    downside = ret[ret < 0]
    downside_std = float(xp.std(downside)) if len(downside) > 1 else std_ret
    sortino = (excess_ret / downside_std * np.sqrt(252)) if downside_std > 0 else 0

    # Calmar ratio (annualized return / max drawdown)
    ann_return = mean_ret * 252
    calmar = ann_return / max_drawdown if max_drawdown > 0.001 else 0

    # VaR 95% (Value at Risk — 5th percentile of daily returns)
    ret_np = to_numpy(ret) if hasattr(ret, 'get') else np.asarray(ret)
    var_95 = float(np.percentile(ret_np, 5))

    # Win rate and profit factor
    wins = ret[ret > 0]
    losses = ret[ret < 0]
    win_rate = float(len(wins)) / len(ret) if len(ret) > 0 else 0
    profit_factor = float(xp.sum(wins) / (-xp.sum(losses))) if len(losses) > 0 and float(xp.sum(losses)) != 0 else 0

    return {
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "final_equity": round(float(equity[-1]), 4),
        "var_95": round(var_95, 6),
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "n_trades": int(len(ret)),
    }


def backtest_xgb(df: pd.DataFrame, lookback: int = 100) -> Dict:
    """
    Backtest modelu XGBoost bar-by-bar na podanych danych.

    Target: matches training target — significant move >0.5 ATR in next 5 bars
    (not simple next-bar direction, which would be a target mismatch).
    """
    from src.ml.ml_models import ml
    from src.analysis.compute import compute_features, compute_target

    lookahead = 5  # must match training lookahead

    if len(df) < lookback + lookahead + 10:
        return {"error": "Za mało danych", "accuracy": 0}

    # Pre-compute actual targets using same logic as training
    features = compute_features(df)
    actual_targets = compute_target(features, lookahead=lookahead)

    y_true = []
    y_pred = []
    returns = []

    for i in range(lookback, len(df) - lookahead):
        window = df.iloc[max(0, i - lookback):i + 1]

        # Use same target as training (significant move in next N bars)
        actual_direction = int(actual_targets.iloc[i]) if i < len(actual_targets) else 0
        # Return: use next-bar return for equity simulation
        actual_return = (df['close'].iloc[i + 1] - df['close'].iloc[i]) / df['close'].iloc[i]

        prob = ml.predict_xgb(window)
        predicted = 1 if prob > 0.5 else 0

        y_true.append(actual_direction)
        y_pred.append(predicted)

        # Equity: jeśli przewiduje wzrost, daje zwrot; inaczej short
        if predicted == 1:
            returns.append(actual_return)
        else:
            returns.append(-actual_return)

    metrics = evaluate_predictions(np.array(y_true), np.array(y_pred))
    equity = compute_equity_metrics(np.array(returns))

    result = {**metrics, **equity, "model": "XGBoost"}
    logger.info(f"📊 [BACKTEST] XGBoost: accuracy={metrics['accuracy']:.1%}, Sharpe={equity['sharpe']:.2f}, "
                f"MaxDD={equity['max_drawdown']:.1%}")
    return result


def backtest_lstm(df: pd.DataFrame, lookback: int = 100, seq_len: int = 60) -> Dict:
    """
    Backtest modelu LSTM bar-by-bar na podanych danych.

    Target: matches training target — significant move >0.5 ATR in next 5 bars.
    """
    from src.ml.ml_models import ml
    from src.analysis.compute import compute_features, compute_target

    lookahead = 5  # must match training lookahead

    if len(df) < lookback + seq_len + lookahead + 10:
        return {"error": "Za mało danych", "accuracy": 0}

    # Pre-compute actual targets using same logic as training
    features = compute_features(df)
    actual_targets = compute_target(features, lookahead=lookahead)

    y_true = []
    y_pred = []
    returns = []

    for i in range(lookback + seq_len, len(df) - lookahead):
        window = df.iloc[max(0, i - lookback - seq_len):i + 1]

        # Use same target as training (significant move in next N bars)
        actual_direction = int(actual_targets.iloc[i]) if i < len(actual_targets) else 0
        actual_return = (df['close'].iloc[i + 1] - df['close'].iloc[i]) / df['close'].iloc[i]

        prob = ml.predict_lstm(window, seq_len)
        predicted = 1 if prob > 0.5 else 0

        y_true.append(actual_direction)
        y_pred.append(predicted)

        if predicted == 1:
            returns.append(actual_return)
        else:
            returns.append(-actual_return)

    metrics = evaluate_predictions(np.array(y_true), np.array(y_pred))
    equity = compute_equity_metrics(np.array(returns))

    result = {**metrics, **equity, "model": "LSTM"}
    logger.info(f"📊 [BACKTEST] LSTM: accuracy={metrics['accuracy']:.1%}, Sharpe={equity['sharpe']:.2f}, "
                f"MaxDD={equity['max_drawdown']:.1%}")
    return result


def backtest_dqn(df: pd.DataFrame) -> Dict:
    """
    Backtest agenta DQN bar-by-bar.
    """
    from src.ml.ensemble_models import predict_dqn_action

    if len(df) < 30:
        return {"error": "Za mało danych", "accuracy": 0}

    y_true = []
    y_pred = []
    returns = []
    balance = 1.0
    position = 0

    for i in range(20, len(df) - 1):
        close_window = df['close'].iloc[max(0, i - 19):i + 1].values
        actual_return = (df['close'].iloc[i + 1] - df['close'].iloc[i]) / df['close'].iloc[i]
        actual_direction = 1 if actual_return > 0 else 0

        action = predict_dqn_action(close_window, balance, position)
        if action is None:
            continue

        # Action: 0=hold, 1=buy, 2=sell
        if action == 1:
            predicted = 1
            position = 1
        elif action == 2:
            predicted = 0
            position = -1
        else:
            predicted = actual_direction  # hold = nie liczymy
            position = 0
            continue  # Pomijamy hold w metrykach

        y_true.append(actual_direction)
        y_pred.append(predicted)

        if predicted == 1:
            returns.append(actual_return)
            balance *= (1 + actual_return)
        else:
            returns.append(-actual_return)
            balance *= (1 - actual_return)

    metrics = evaluate_predictions(np.array(y_true), np.array(y_pred))
    equity = compute_equity_metrics(np.array(returns))

    result = {**metrics, **equity, "model": "DQN"}
    logger.info(f"📊 [BACKTEST] DQN: accuracy={metrics['accuracy']:.1%}, Sharpe={equity['sharpe']:.2f}, "
                f"MaxDD={equity['max_drawdown']:.1%}")
    return result


def backtest_ensemble(df: pd.DataFrame, lookback: int = 200) -> Dict:
    """
    Backtest pełnego ensemble (SMC + LSTM + XGB + DQN) bar-by-bar.
    """
    from src.ml.ensemble_models import get_ensemble_prediction

    if len(df) < lookback + 10:
        return {"error": "Za mało danych", "accuracy": 0}

    y_true = []
    y_pred = []
    returns = []
    signals = {"LONG": 0, "SHORT": 0, "CZEKAJ": 0}

    for i in range(lookback, len(df) - 1):
        window = df.iloc[max(0, i - lookback):i + 1]
        actual_return = (df['close'].iloc[i + 1] - df['close'].iloc[i]) / df['close'].iloc[i]
        actual_direction = 1 if actual_return > 0 else 0

        # Heurystyczny trend SMC na podstawie EMA
        ema20 = window['close'].ewm(span=20).mean().iloc[-1]
        smc_trend = "bull" if window['close'].iloc[-1] > ema20 else "bear"

        ensemble = get_ensemble_prediction(
            df=window,
            smc_trend=smc_trend,
            current_price=window['close'].iloc[-1],
            balance=10000,
            initial_balance=10000,
            position=0,
            use_twelve_data=False
        )

        signal = ensemble.get('ensemble_signal', 'CZEKAJ')
        signals[signal] = signals.get(signal, 0) + 1

        if signal == "CZEKAJ":
            continue  # Pomijamy CZEKAJ w metrykach kierunkowych

        predicted = 1 if signal == "LONG" else 0
        y_true.append(actual_direction)
        y_pred.append(predicted)

        if predicted == 1:
            returns.append(actual_return)
        else:
            returns.append(-actual_return)

    metrics = evaluate_predictions(np.array(y_true), np.array(y_pred))
    equity = compute_equity_metrics(np.array(returns))

    result = {**metrics, **equity, "model": "Ensemble", "signals": signals}
    logger.info(
        f"📊 [BACKTEST] Ensemble: accuracy={metrics['accuracy']:.1%}, Sharpe={equity['sharpe']:.2f}, "
        f"MaxDD={equity['max_drawdown']:.1%}, signals={signals}"
    )
    return result


def apply_transaction_costs(returns: np.ndarray, spread_pct: float = 0.0003) -> np.ndarray:
    """
    Deduct transaction costs from returns.

    Args:
        returns: Array of per-trade returns
        spread_pct: Cost per trade as fraction (0.0003 = 0.03% = ~$0.60 on $2000 gold)

    Returns:
        Adjusted returns array
    """
    return returns - spread_pct


def monte_carlo_simulation(returns: np.ndarray, n_simulations: int = 5000,
                           spread_pct: float = 0.0003) -> Dict:
    """
    Monte Carlo simulation: shuffle trade order to estimate return distribution.

    Generates n_simulations random permutations of the trade sequence,
    computes equity curves for each, and reports statistical distribution.

    Args:
        returns: Array of actual trade returns
        n_simulations: Number of random shuffles (default 5000)
        spread_pct: Transaction cost per trade

    Returns:
        Dict with percentile statistics of final equity and max drawdown
    """
    if len(returns) < 10:
        return {"error": "Insufficient trades for Monte Carlo"}

    # Apply costs once
    adj_returns = apply_transaction_costs(returns, spread_pct)

    final_equities = np.empty(n_simulations)
    max_drawdowns = np.empty(n_simulations)

    for i in range(n_simulations):
        shuffled = np.random.permutation(adj_returns)
        equity = np.cumprod(1 + shuffled)
        final_equities[i] = equity[-1]

        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / (peak + 1e-10)
        max_drawdowns[i] = dd.max()

    return {
        "n_simulations": n_simulations,
        "n_trades": len(returns),
        "spread_pct": spread_pct,
        "final_equity": {
            "mean": round(float(np.mean(final_equities)), 4),
            "median": round(float(np.median(final_equities)), 4),
            "p1": round(float(np.percentile(final_equities, 1)), 4),
            "p5": round(float(np.percentile(final_equities, 5)), 4),
            "p25": round(float(np.percentile(final_equities, 25)), 4),
            "p75": round(float(np.percentile(final_equities, 75)), 4),
            "p95": round(float(np.percentile(final_equities, 95)), 4),
            "p99": round(float(np.percentile(final_equities, 99)), 4),
        },
        "max_drawdown": {
            "mean": round(float(np.mean(max_drawdowns)), 4),
            "median": round(float(np.median(max_drawdowns)), 4),
            "p95": round(float(np.percentile(max_drawdowns, 95)), 4),
            "p99": round(float(np.percentile(max_drawdowns, 99)), 4),
            "worst": round(float(np.max(max_drawdowns)), 4),
        },
        "profitable_pct": round(float((final_equities > 1.0).mean()) * 100, 1),
        "ruin_pct": round(float((final_equities < 0.5).mean()) * 100, 2),
    }


def run_full_backtest(df: pd.DataFrame) -> Dict:
    """
    Uruchamia backtest dla wszystkich modeli i zwraca zbiorczy raport.
    """
    logger.info(f"[BACKTEST] Starting full backtest on {len(df)} bars")

    results = {}

    for name, label, fn in [
        ('xgb', 'XGBoost', backtest_xgb),
        ('lstm', 'LSTM', backtest_lstm),
        ('dqn', 'DQN', backtest_dqn),
        ('ensemble', 'Ensemble', backtest_ensemble),
    ]:
        try:
            logger.info(f"[BACKTEST] Running {label}...")
            results[name] = fn(df)
        except Exception as e:
            logger.warning(f"[BACKTEST] {label} failed: {e}")
            results[name] = {"error": str(e)}

    # Report
    for model_name, r in results.items():
        if "error" in r and r.get("accuracy", 0) == 0:
            logger.warning(f"[BACKTEST] {model_name}: FAILED — {r.get('error', 'unknown')}")
        else:
            logger.info(
                f"[BACKTEST] {model_name}: "
                f"Acc={r.get('accuracy', 0):.1%} MCC={r.get('mcc', 0):.3f} "
                f"Sharpe={r.get('sharpe', 0):.2f} Sortino={r.get('sortino', 0):.2f} "
                f"MaxDD={r.get('max_drawdown', 0):.1%} Return={r.get('total_return', 0):+.1%}"
            )

    # Persist to database
    try:
        from src.core.database import NewsDB
        db = NewsDB()
        import json
        db.set_param("last_backtest_results", json.dumps({
            k: {kk: (str(vv) if not isinstance(vv, (int, float, bool, type(None))) else vv)
                for kk, vv in v.items()}
            for k, v in results.items()
        }))
        logger.info("[BACKTEST] Results saved to database")
    except Exception as e:
        logger.warning(f"[BACKTEST] Could not save results: {e}")

    return results


if __name__ == "__main__":
    import yfinance as yf

    logger.info("Fetching data for backtest...")
    ticker = yf.Ticker("GC=F")
    df = ticker.history(period="3mo", interval="15m")
    if df.empty:
        df = ticker.history(period="6mo", interval="1h")
    if df.empty:
        df = ticker.history(period="2y", interval="1d")

    df = df.reset_index()
    col_map = {c: c.lower() for c in df.columns}
    df.rename(columns=col_map, inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()

    run_full_backtest(df)

