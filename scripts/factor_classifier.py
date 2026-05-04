"""
scripts/factor_classifier.py — train a tiny ML classifier on factor combos.

Validates whether sklearn (RandomForest/LogReg) can find predictive
signal in the factor-set we currently use. If it CAN beat 50% baseline
on hold-out, factor combinations have edge that single-factor analysis
missed. If it CANNOT, the edge isn't in factors — same conclusion as
the LLM premortem (7.7% accuracy).

Builds:
  - X: one-hot factor presence + grade + RSI + session
  - y: WIN (1) / LOSS (0)
  - 5-fold CV with stratified split
  - LogReg + RandomForest
  - Feature importance ranking

Usage:
    python scripts/factor_classifier.py [--db both]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def fetch_trades(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT id, direction, status, profit, factors,
                  setup_grade, setup_score, rsi, session,
                  trend, structure, vol_regime
           FROM trades WHERE status IN ('WIN','LOSS') AND factors IS NOT NULL"""
    ).fetchall()
    out = []
    cols = ["id", "direction", "status", "profit", "factors",
            "setup_grade", "setup_score", "rsi", "session",
            "trend", "structure", "vol_regime"]
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["factors_dict"] = json.loads(d["factors"]) if d["factors"] else {}
        except Exception:
            d["factors_dict"] = {}
        out.append(d)
    conn.close()
    return out


def build_features(trades: list[dict]) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    # Discover all factor keys
    all_factors = set()
    for t in trades:
        all_factors.update(t["factors_dict"].keys())
    # Filter penalty factors out — they're score adjustments not predictors
    factor_cols = sorted([f for f in all_factors if not f.endswith("_penalty")])

    rows = []
    y = []
    for t in trades:
        row = {f: int(f in t["factors_dict"]) for f in factor_cols}
        row["direction_long"] = 1 if t["direction"] == "LONG" else 0
        row["grade_aplus"] = 1 if t.get("setup_grade") == "A+" else 0
        row["grade_a"] = 1 if t.get("setup_grade") == "A" else 0
        row["grade_b"] = 1 if t.get("setup_grade") == "B" else 0
        row["score"] = float(t.get("setup_score") or 0)
        row["rsi"] = float(t.get("rsi") or 50)
        # Sessions one-hot
        for sess in ("asian", "london", "new_york", "overlap", "off_hours"):
            row[f"sess_{sess}"] = 1 if t.get("session") == sess else 0
        # Trend
        row["trend_bull"] = 1 if "Bull" in (t.get("trend") or "") else 0
        row["trend_bear"] = 1 if "Bear" in (t.get("trend") or "") else 0
        rows.append(row)
        y.append(1 if t["status"] == "WIN" else 0)

    X = pd.DataFrame(rows)
    feature_cols = X.columns.tolist()
    return X, np.array(y), feature_cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", choices=["live", "backtest", "both"], default="both")
    args = ap.parse_args()

    trades = []
    if args.db in ("live", "both"):
        trades.extend(fetch_trades("data/sentinel.db"))
    if args.db in ("backtest", "both"):
        trades.extend(fetch_trades("data/backtest.db"))

    n = len(trades)
    if n < 30:
        print(f"Too few trades ({n}); need 30+ for meaningful CV.")
        return

    wins = sum(1 for t in trades if t["status"] == "WIN")
    print(f"COHORT: N={n}, baseline WR {wins/n*100:.1f}%\n")

    X, y, feature_cols = build_features(trades)
    print(f"Features: {len(feature_cols)}, samples: {len(y)}")
    print(f"Class balance: {Counter(y)}")

    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # LogReg
    print("\n=== LogisticRegression (5-fold CV) ===")
    pipe_lr = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=500, class_weight="balanced", random_state=42)),
    ])
    scores_lr = cross_val_score(pipe_lr, X, y, cv=cv, scoring="accuracy")
    print(f"  Accuracy: {scores_lr.mean()*100:.1f}% (+/- {scores_lr.std()*100:.1f}%)")
    scores_auc = cross_val_score(pipe_lr, X, y, cv=cv, scoring="roc_auc")
    print(f"  ROC AUC: {scores_auc.mean():.3f} (+/- {scores_auc.std():.3f})")

    # RandomForest
    print("\n=== RandomForest (5-fold CV) ===")
    rf = RandomForestClassifier(n_estimators=200, max_depth=5,
                                 class_weight="balanced", random_state=42)
    scores_rf = cross_val_score(rf, X, y, cv=cv, scoring="accuracy")
    print(f"  Accuracy: {scores_rf.mean()*100:.1f}% (+/- {scores_rf.std()*100:.1f}%)")
    scores_rf_auc = cross_val_score(rf, X, y, cv=cv, scoring="roc_auc")
    print(f"  ROC AUC: {scores_rf_auc.mean():.3f} (+/- {scores_rf_auc.std():.3f})")

    # Feature importance from RF (full fit)
    rf_full = RandomForestClassifier(n_estimators=200, max_depth=5,
                                      class_weight="balanced", random_state=42)
    rf_full.fit(X, y)
    importances = pd.Series(rf_full.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print("\n=== Top 15 features by RF importance ===")
    for f, imp in importances.head(15).items():
        print(f"  {f:<35} {imp:.4f}")

    # LR coefficients
    pipe_lr.fit(X, y)
    coefs = pipe_lr.named_steps["clf"].coef_[0]
    coef_series = pd.Series(coefs, index=feature_cols).sort_values()
    print("\n=== LR coefficients (negative = pushes LOSS, positive = pushes WIN) ===")
    print("  Most negative (LOSS-pushing):")
    for f, c in coef_series.head(8).items():
        print(f"    {f:<35} {c:+.3f}")
    print("  Most positive (WIN-pushing):")
    for f, c in coef_series.tail(8).items():
        print(f"    {f:<35} {c:+.3f}")

    # Verdict
    print("\n=== VERDICT ===")
    if scores_auc.mean() > 0.65:
        print(f"  AUC {scores_auc.mean():.2f} > 0.65 — factor model HAS edge,")
        print("  worth training a real voter on this feature space.")
    elif scores_auc.mean() > 0.55:
        print(f"  AUC {scores_auc.mean():.2f} weakly above random — borderline.")
        print("  Re-run on N=300+ to confirm.")
    else:
        print(f"  AUC {scores_auc.mean():.2f} ~ random — factor combinations don't")
        print("  predict outcome at small-N. Edge must be elsewhere (regime/timing/exits).")


if __name__ == "__main__":
    main()
