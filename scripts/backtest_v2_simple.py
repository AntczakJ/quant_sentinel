#!/usr/bin/env python3
"""
backtest_v2_simple.py — Fast triple-barrier backtest using v2 ensemble predictions.

For each bar in test period:
  1. Compute features_v2
  2. Get v2 ensemble prediction (XGB long_R, XGB short_R, [LSTM])
  3. If high-confidence directional signal → simulate trade with triple barrier
     (TP=2ATR, SL=1ATR, time barrier=48 bars)
  4. Aggregate WR, PF, avg R, max DD

Much faster than full production backtest because:
  - No full scanner cascade (just v2 ensemble decision)
  - No ml ensemble round-trip via ensemble_models.py
  - Direct model.predict() calls
  - All data pre-loaded from parquet warehouse

Use case: quick A/B comparison of v2 vs v1 baseline on same test period.

Usage:
    python scripts/backtest_v2_simple.py
    python scripts/backtest_v2_simple.py --days 30 --threshold 0.5
    python scripts/backtest_v2_simple.py --days 60 --threshold 0.3 --tf 15min
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Repo path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

MODELS_V2 = Path("models/v2")
WAREHOUSE = Path("data/historical")


def load_models():
    """Load v2 XGB models."""
    import xgboost as xgb
    meta_path = MODELS_V2 / "xau_long_xgb_v2.meta.json"
    with open(meta_path) as f:
        meta = json.load(f)
    feature_cols = meta["feature_cols"]

    long_m = xgb.XGBRegressor()
    long_m.load_model(str(MODELS_V2 / "xau_long_xgb_v2.json"))
    short_m = xgb.XGBRegressor()
    short_m.load_model(str(MODELS_V2 / "xau_short_xgb_v2.json"))
    return long_m, short_m, feature_cols


def load_data_with_features(tf: str = "5min", days: int = 30):
    from src.analysis.features_v2 import compute_features_v2
    p = WAREHOUSE / "XAU_USD" / f"{tf}.parquet"
    df = pd.read_parquet(p)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    df = df[df["datetime"] >= cutoff].reset_index(drop=True)
    print(f"Loaded {len(df)} XAU {tf} bars for backtest")
    df = df.set_index("datetime")
    features = compute_features_v2(df)
    return features


def simulate_trade(
    bars: pd.DataFrame, entry_idx: int, direction: str,
    atr: float, tp_atr: float = 2.0, sl_atr: float = 1.0,
    max_horizon: int = 48,
) -> tuple[str, float, int]:
    """
    Walk forward bar-by-bar to find first barrier hit.

    Returns: (outcome, R_realized, bars_to_exit)
      outcome: 'TP' / 'SL' / 'TIME'
      R_realized: e.g. +2 for TP hit, -1 for SL hit, fraction for time exit
    """
    entry = bars["close"].iloc[entry_idx]
    sign = 1 if direction == "LONG" else -1
    tp_price = entry + sign * tp_atr * atr
    sl_price = entry - sign * sl_atr * atr

    horizon_end = min(entry_idx + 1 + max_horizon, len(bars))
    for j in range(entry_idx + 1, horizon_end):
        high_j = bars["high"].iloc[j]
        low_j = bars["low"].iloc[j]
        if direction == "LONG":
            hit_sl = low_j <= sl_price
            hit_tp = high_j >= tp_price
        else:
            hit_sl = high_j >= sl_price
            hit_tp = low_j <= tp_price

        if hit_sl and hit_tp:
            # conservative: assume SL hit first
            return ("SL", -1.0, j - entry_idx)
        if hit_sl:
            return ("SL", -1.0, j - entry_idx)
        if hit_tp:
            return ("TP", tp_atr, j - entry_idx)

    # Time barrier
    final_close = bars["close"].iloc[horizon_end - 1]
    r = sign * (final_close - entry) / (sl_atr * atr)
    return ("TIME", float(r), horizon_end - 1 - entry_idx)


def backtest_v2(
    threshold: float = 0.5, days: int = 30, tf: str = "5min",
    cooldown_bars: int = 5, ensemble_mode: str = "xgb_only",
):
    """
    Run v2 simple backtest.

    cooldown_bars: minimum bars between trade entries (matches production
                   adaptive cooldown logic, simplified)
    ensemble_mode: "xgb_only" or "xgb_lstm" (avg of XGB + LSTM)
    """
    long_m, short_m, feature_cols = load_models()
    features = load_data_with_features(tf=tf, days=days)
    if "atr" not in features.columns:
        raise ValueError("features missing 'atr'")

    # Prepare X for batch prediction
    X = features[feature_cols].fillna(0).values.astype(np.float32)
    long_preds = long_m.predict(X)
    short_preds = short_m.predict(X)

    if ensemble_mode == "xgb_lstm":
        # Try to add LSTM ensemble
        try:
            import tensorflow as tf_mod
            seq_len = 32
            lstm_long = tf_mod.keras.models.load_model(str(MODELS_V2 / "xau_long_lstm_v2.keras"))
            lstm_short = tf_mod.keras.models.load_model(str(MODELS_V2 / "xau_short_lstm_v2.keras"))
            sc_l = np.load(str(MODELS_V2 / "xau_long_lstm_v2.scaler.npz"))
            sc_s = np.load(str(MODELS_V2 / "xau_short_lstm_v2.scaler.npz"))

            # Build sequences
            n = len(X)
            X_seq = np.zeros((n, seq_len, X.shape[1]), dtype=np.float32)
            for i in range(seq_len, n):
                X_seq[i] = X[i - seq_len:i]

            lstm_long_norm = (X_seq - sc_l["mean"].squeeze()) / sc_l["std"].squeeze()
            lstm_short_norm = (X_seq - sc_s["mean"].squeeze()) / sc_s["std"].squeeze()
            lstm_long_pred = lstm_long.predict(lstm_long_norm, batch_size=256, verbose=0).flatten()
            lstm_short_pred = lstm_short.predict(lstm_short_norm, batch_size=256, verbose=0).flatten()

            # Average XGB + LSTM
            long_preds = (long_preds + lstm_long_pred) / 2
            short_preds = (short_preds + lstm_short_pred) / 2
            print("Ensemble: XGB + LSTM averaged")
        except Exception as e:
            print(f"LSTM ensemble failed, falling back to XGB only: {e}")

    # Walk through bars, decide trades
    trades = []
    last_entry = -cooldown_bars - 1
    for i in range(len(X) - 50):  # leave room for max_horizon
        if i - last_entry < cooldown_bars:
            continue
        atr = features["atr"].iloc[i]
        if not np.isfinite(atr) or atr <= 0:
            continue

        long_r = long_preds[i]
        short_r = short_preds[i]
        # Trade decision
        if long_r >= threshold and long_r > -short_r:
            direction = "LONG"
        elif short_r <= -threshold and -short_r > long_r:
            direction = "SHORT"
        else:
            continue

        outcome, r_realized, bars_held = simulate_trade(
            features, i, direction, atr,
        )
        trades.append({
            "ts": features.index[i],
            "direction": direction,
            "entry": float(features["close"].iloc[i]),
            "atr": float(atr),
            "outcome": outcome,
            "r_realized": r_realized,
            "bars_held": bars_held,
            "long_pred": float(long_r),
            "short_pred": float(short_r),
        })
        last_entry = i

    if not trades:
        return {"error": "no trades"}

    df_t = pd.DataFrame(trades)
    n = len(df_t)
    wins = (df_t["r_realized"] > 0).sum()
    losses = (df_t["r_realized"] < 0).sum()
    wr = wins / n * 100
    sum_r = df_t["r_realized"].sum()
    sum_win = df_t.loc[df_t["r_realized"] > 0, "r_realized"].sum()
    sum_loss = -df_t.loc[df_t["r_realized"] < 0, "r_realized"].sum()
    pf = sum_win / sum_loss if sum_loss > 0 else float("inf")

    # Equity curve + drawdown
    cumr = df_t["r_realized"].cumsum()
    peak = cumr.cummax()
    dd = (cumr - peak)
    max_dd = float(dd.min())

    # Per-direction
    per_dir = {}
    for d in ("LONG", "SHORT"):
        sub = df_t[df_t["direction"] == d]
        if len(sub) == 0:
            per_dir[d] = {"n": 0}
            continue
        per_dir[d] = {
            "n": len(sub),
            "wr": float((sub["r_realized"] > 0).sum() / len(sub) * 100),
            "sum_r": float(sub["r_realized"].sum()),
            "avg_r": float(sub["r_realized"].mean()),
        }

    return {
        "n_trades": int(n),
        "wins": int(wins),
        "losses": int(losses),
        "wr_pct": float(wr),
        "sum_r": float(sum_r),
        "avg_r": float(sum_r / n),
        "profit_factor": float(pf),
        "max_dd_R": max_dd,
        "per_direction": per_dir,
        "outcome_counts": df_t["outcome"].value_counts().to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--tf", default="5min")
    ap.add_argument("--cooldown-bars", type=int, default=5)
    ap.add_argument("--ensemble", choices=["xgb_only", "xgb_lstm"], default="xgb_only")
    args = ap.parse_args()

    print(f"Backtest config: days={args.days}, threshold={args.threshold}R, "
          f"tf={args.tf}, cooldown={args.cooldown_bars}bars, ensemble={args.ensemble}")
    result = backtest_v2(
        threshold=args.threshold, days=args.days, tf=args.tf,
        cooldown_bars=args.cooldown_bars, ensemble_mode=args.ensemble,
    )
    print()
    print("=" * 60)
    print("V2 BACKTEST RESULTS")
    print("=" * 60)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return
    for k, v in result.items():
        if k in ("per_direction", "outcome_counts"):
            print(f"  {k}:")
            for k2, v2 in v.items():
                print(f"    {k2}: {v2}")
        elif isinstance(v, float):
            print(f"  {k:25s}: {v:.4f}")
        else:
            print(f"  {k:25s}: {v}")


if __name__ == "__main__":
    main()
