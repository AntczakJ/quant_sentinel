"""
scripts/factor_classifier_wf.py — walk-forward validation for the
factor classifier (extends factor_classifier.py).

Random K-fold CV on time-series can leak future info into past.
This script splits trades chronologically into N blocks and trains
on past blocks, predicts next block. Realistic out-of-sample.

If walk-forward AUC holds within 0.05 of random-shuffle AUC, the
edge is robust. If it collapses to ~0.5, the random-CV result was
artifact of class balance + feature ordering.

Usage:
    python scripts/factor_classifier_wf.py [--db both] [--folds 5]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.split("+")[0].split(".")[0], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fetch(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id, timestamp, direction, status, profit, factors,
                  setup_grade, setup_score, rsi, session, trend
           FROM trades WHERE status IN ('WIN','LOSS') AND factors IS NOT NULL"""
    ).fetchall()
    out = []
    cols = ["id", "timestamp", "direction", "status", "profit", "factors",
            "setup_grade", "setup_score", "rsi", "session", "trend"]
    for r in rows:
        d = dict(zip(cols, r))
        ts = parse_ts(d["timestamp"])
        if not ts:
            continue
        d["ts"] = ts
        try:
            d["factors_dict"] = json.loads(d["factors"]) if d["factors"] else {}
        except Exception:
            d["factors_dict"] = {}
        out.append(d)
    conn.close()
    return sorted(out, key=lambda t: t["ts"])


def to_features(trades: list[dict]) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    all_factors = set()
    for t in trades:
        all_factors.update(t["factors_dict"].keys())
    factor_cols = sorted([f for f in all_factors if not f.endswith("_penalty")])

    rows = []
    y = []
    for t in trades:
        row = {f: int(f in t["factors_dict"]) for f in factor_cols}
        row["direction_long"] = 1 if t["direction"] == "LONG" else 0
        row["score"] = float(t.get("setup_score") or 0)
        row["rsi"] = float(t.get("rsi") or 50)
        for sess in ("asian", "london", "new_york", "overlap", "off_hours"):
            row[f"sess_{sess}"] = 1 if t.get("session") == sess else 0
        row["trend_bull"] = 1 if "Bull" in (t.get("trend") or "") else 0
        rows.append(row)
        y.append(1 if t["status"] == "WIN" else 0)
    return pd.DataFrame(rows), np.array(y), list(rows[0].keys()) if rows else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--min-train", type=int, default=20)
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch("data/backtest.db"))
    trades.sort(key=lambda t: t["ts"])
    n = len(trades)
    if n < args.min_train * 2:
        print(f"Too few trades for walk-forward ({n} < {args.min_train*2})")
        return

    X, y, feat_cols = to_features(trades)
    n_features = X.shape[1]
    print(f"Walk-forward: N={n} trades, {n_features} features, {args.folds} folds")
    print(f"Cohort time range: {trades[0]['ts'].date()} -> {trades[-1]['ts'].date()}\n")

    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, accuracy_score

    fold_size = n // args.folds
    aucs_lr, aucs_rf, accs_rf = [], [], []
    for k in range(args.folds - 1):
        train_end = (k + 1) * fold_size
        if train_end < args.min_train:
            continue
        test_start = train_end
        test_end = test_start + fold_size

        X_tr, y_tr = X.iloc[:train_end], y[:train_end]
        X_te, y_te = X.iloc[test_start:test_end], y[test_start:test_end]
        if len(set(y_te)) < 2 or len(set(y_tr)) < 2:
            continue

        # LogReg with scaling
        scaler = StandardScaler()
        X_tr_s = scaler.fit_transform(X_tr)
        X_te_s = scaler.transform(X_te)
        try:
            lr = LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)
            lr.fit(X_tr_s, y_tr)
            p_lr = lr.predict_proba(X_te_s)[:, 1]
            auc_lr = roc_auc_score(y_te, p_lr)
        except Exception:
            auc_lr = float("nan")

        # RandomForest
        rf = RandomForestClassifier(n_estimators=200, max_depth=5,
                                     class_weight="balanced", random_state=42)
        rf.fit(X_tr, y_tr)
        p_rf = rf.predict_proba(X_te)[:, 1]
        auc_rf = roc_auc_score(y_te, p_rf)
        acc_rf = accuracy_score(y_te, rf.predict(X_te))

        train_dates = (trades[0]["ts"].date(), trades[train_end - 1]["ts"].date())
        test_dates = (trades[test_start]["ts"].date(), trades[min(test_end, n) - 1]["ts"].date())
        print(f"Fold {k+1}: train n={train_end} ({train_dates[0]} -> {train_dates[1]}), "
              f"test n={test_end - test_start} ({test_dates[0]} -> {test_dates[1]})")
        print(f"   LR AUC: {auc_lr:.3f} | RF AUC: {auc_rf:.3f} | RF acc: {acc_rf*100:.1f}%")
        if not np.isnan(auc_lr):
            aucs_lr.append(auc_lr)
        aucs_rf.append(auc_rf)
        accs_rf.append(acc_rf)

    print()
    if aucs_lr:
        print(f"  LR AUC mean: {np.mean(aucs_lr):.3f}  std: {np.std(aucs_lr):.3f}")
    if aucs_rf:
        print(f"  RF AUC mean: {np.mean(aucs_rf):.3f}  std: {np.std(aucs_rf):.3f}")
        print(f"  RF acc mean: {np.mean(accs_rf)*100:.1f}%  std: {np.std(accs_rf)*100:.1f}%")

    print("\n=== VERDICT ===")
    if aucs_rf and np.mean(aucs_rf) > 0.6:
        print(f"  Walk-forward AUC {np.mean(aucs_rf):.3f} > 0.6 — robust edge.")
    elif aucs_rf and np.mean(aucs_rf) > 0.55:
        print(f"  Walk-forward AUC {np.mean(aucs_rf):.3f} weak — borderline.")
    elif aucs_rf:
        print(f"  Walk-forward AUC {np.mean(aucs_rf):.3f} ~ random — random-CV was overfit.")
    else:
        print("  Insufficient data.")


if __name__ == "__main__":
    main()
