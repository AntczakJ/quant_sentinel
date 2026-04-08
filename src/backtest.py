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
from src.logger import logger
from src.compute import get_array_module, to_numpy


def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray) -> Dict:
    """
    Oblicz metryki klasyfikacji binarnej (fully vectorized).
    y_true, y_pred: 0 = spadek, 1 = wzrost
    Uses CuPy if GPU available for large arrays.
    """
    xp = get_array_module()
    n = len(y_true)
    if n == 0:
        return {"accuracy": 0, "precision": 0, "recall": 0, "f1": 0}

    yt = xp.asarray(y_true)
    yp = xp.asarray(y_pred)

    correct = int((yt == yp).sum())
    accuracy = correct / n

    tp = int(((yp == 1) & (yt == 1)).sum())
    fp = int(((yp == 1) & (yt == 0)).sum())
    fn = int(((yp == 0) & (yt == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "total": n,
        "correct": correct,
    }


def compute_equity_metrics(returns: np.ndarray) -> Dict:
    """
    Oblicz metryki equity curve: Sharpe ratio, max drawdown, total return.
    Fully vectorized — uses CuPy if GPU available for large arrays.
    """
    xp = get_array_module()
    if len(returns) == 0:
        return {"sharpe": 0, "max_drawdown": 0, "total_return": 0}

    ret = xp.asarray(returns)

    # Equity curve (vectorized cumulative product)
    equity = xp.cumprod(1 + ret)
    total_return = float(equity[-1] - 1)

    # Max drawdown (vectorized)
    peak = xp.maximum.accumulate(equity)
    drawdown = (peak - equity) / (peak + 1e-10)
    max_drawdown = float(drawdown.max())

    # Sharpe ratio
    mean_ret = float(xp.mean(ret))
    std_ret = float(xp.std(ret))
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0

    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "final_equity": round(float(equity[-1]), 4),
    }


def backtest_xgb(df: pd.DataFrame, lookback: int = 100) -> Dict:
    """
    Backtest modelu XGBoost bar-by-bar na podanych danych.
    """
    from src.ml_models import ml

    if len(df) < lookback + 10:
        return {"error": "Za mało danych", "accuracy": 0}

    y_true = []
    y_pred = []
    returns = []

    for i in range(lookback, len(df) - 1):
        window = df.iloc[max(0, i - lookback):i + 1]
        actual_direction = 1 if df['close'].iloc[i + 1] > df['close'].iloc[i] else 0
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
    """
    from src.ml_models import ml

    if len(df) < lookback + seq_len + 10:
        return {"error": "Za mało danych", "accuracy": 0}

    y_true = []
    y_pred = []
    returns = []

    for i in range(lookback + seq_len, len(df) - 1):
        window = df.iloc[max(0, i - lookback - seq_len):i + 1]
        actual_direction = 1 if df['close'].iloc[i + 1] > df['close'].iloc[i] else 0
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
    from src.ensemble_models import predict_dqn_action

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
    from src.ensemble_models import get_ensemble_prediction

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


def run_full_backtest(df: pd.DataFrame) -> Dict:
    """
    Uruchamia backtest dla wszystkich modeli i zwraca zbiorczy raport.
    """
    print("\n" + "=" * 60)
    print("📊 PEŁNY BACKTEST WSZYSTKICH MODELI")
    print("=" * 60)
    print(f"Dane: {len(df)} świec\n")

    results = {}

    # XGBoost
    try:
        print("🌳 Backtesting XGBoost...")
        results['xgb'] = backtest_xgb(df)
    except Exception as e:
        print(f"   ❌ XGBoost backtest failed: {e}")
        results['xgb'] = {"error": str(e)}

    # LSTM
    try:
        print("🧠 Backtesting LSTM...")
        results['lstm'] = backtest_lstm(df)
    except Exception as e:
        print(f"   ❌ LSTM backtest failed: {e}")
        results['lstm'] = {"error": str(e)}

    # DQN
    try:
        print("🤖 Backtesting DQN...")
        results['dqn'] = backtest_dqn(df)
    except Exception as e:
        print(f"   ❌ DQN backtest failed: {e}")
        results['dqn'] = {"error": str(e)}

    # Ensemble
    try:
        print("🎯 Backtesting Ensemble...")
        results['ensemble'] = backtest_ensemble(df)
    except Exception as e:
        print(f"   ❌ Ensemble backtest failed: {e}")
        results['ensemble'] = {"error": str(e)}

    # Raport końcowy
    print("\n" + "=" * 60)
    print("📋 RAPORT BACKTESTOWY")
    print("=" * 60)
    for model_name, r in results.items():
        if "error" in r and r.get("accuracy", 0) == 0:
            print(f"  {model_name:>10s}: ❌ {r.get('error', 'unknown error')}")
        else:
            acc = r.get('accuracy', 0)
            f1 = r.get('f1', 0)
            sharpe = r.get('sharpe', 0)
            mdd = r.get('max_drawdown', 0)
            ret = r.get('total_return', 0)
            print(
                f"  {model_name:>10s}: "
                f"Accuracy={acc:.1%} | F1={f1:.3f} | "
                f"Sharpe={sharpe:.2f} | MaxDD={mdd:.1%} | Return={ret:+.1%}"
            )
    print("=" * 60)

    # Zapisz do bazy
    try:
        from src.database import NewsDB
        db = NewsDB()
        import json
        db.set_param("last_backtest_results", json.dumps({
            k: {kk: (str(vv) if not isinstance(vv, (int, float, bool, type(None))) else vv)
                for kk, vv in v.items()}
            for k, v in results.items()
        }))
        print("📝 Wyniki backtestów zapisane do bazy.")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać wyników: {e}")

    return results


if __name__ == "__main__":
    import yfinance as yf

    print("Pobieranie danych do backtestingu...")
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

