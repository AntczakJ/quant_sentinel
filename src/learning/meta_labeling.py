"""src/learning/meta_labeling.py — Lopez de Prado meta-labeling for position sizing.

2026-05-05: shipped per comparative research adoption (#10 — biggest lift).
Two-stage architecture: SMC primary picks side, secondary ML model decides
"is this trade profitable?" (binary 0/1) and outputs CALIBRATED probability.
Position size = kelly_fraction(p_secondary).

Hudson & Thames empirical: WR 55→83% on calibrated secondary.
References:
  - Lopez de Prado *Advances in Financial ML* §3 (meta-labeling)
  - https://github.com/hudson-and-thames/meta-labeling
  - https://www.pm-research.com/content/iijjfds/5/2/23

Why this beats current ensemble:
  - Our 7-voter ensemble fuses direction+size implicitly. Meta-labeling
    cleanly decouples them. Calibrated secondary probability gives
    fractional Kelly sizing — directly attacks "winners 0.026 / losers
    0.084 lot" inverse-correlation bug.
  - v2_xgb per-direction is half-step toward this; meta-labeling
    completes it.

Architecture:
  Step 1: SMC primary triggers a setup with direction (existing flow)
  Step 2: Build feature vector + run secondary classifier
  Step 3: p = secondary.predict_proba()[1]  # P(profitable | features)
  Step 4: lot = base_lot × kelly_fraction(p, payoff_ratio)
  Step 5: If p < min_threshold → skip the trade entirely

Training:
  Build dataset from backtest.db: (features, primary_signal,
  binary_outcome). Fit XGBoost binary classifier with isotonic
  calibration. Persist to models/meta_labeler.pkl.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PKL = ROOT / "models" / "meta_labeler.pkl"

# Default Kelly fraction parameters per audit / Trading Risk research:
# - half-Kelly = empirical sweet-spot (cuts vol ~75% with ~25% growth haircut)
# - capped fraction prevents over-leverage during win streaks
DEFAULT_KELLY_CAP = 0.5  # half-Kelly
MIN_PROB_THRESHOLD = 0.55  # below this, skip trade (no edge)


# ── Kelly fraction ────────────────────────────────────────────────────

def kelly_fraction(prob_win: float, payoff_ratio: float = 2.0,
                   cap: float = DEFAULT_KELLY_CAP) -> float:
    """Kelly criterion fraction for sizing.

    f* = (p × b - (1 - p)) / b
    where p = P(win), b = win/loss payoff ratio (TP_distance / SL_distance).

    Capped at `cap` (default 0.5 = half-Kelly).
    Returns 0 if calculated f* is negative or NaN.

    Args:
        prob_win: secondary model's calibrated P(profitable) ∈ [0, 1]
        payoff_ratio: target_rr — typically 2.0 (B grade) or 2.5 (A+).
        cap: max fraction (default 0.5 = half-Kelly).
    """
    if not (0.0 <= prob_win <= 1.0):
        return 0.0
    if payoff_ratio <= 0:
        return 0.0
    p = prob_win
    b = payoff_ratio
    f_star = (p * b - (1.0 - p)) / b
    if f_star <= 0 or np.isnan(f_star):
        return 0.0
    return min(f_star, cap)


# ── Meta-labeler ──────────────────────────────────────────────────────

class MetaLabeler:
    """Wraps a calibrated binary classifier + feature pipeline."""

    def __init__(self, model, feature_names: list[str],
                 min_prob_threshold: float = MIN_PROB_THRESHOLD,
                 base_lot: float = 0.01):
        self.model = model
        self.feature_names = feature_names
        self.min_prob_threshold = min_prob_threshold
        self.base_lot = base_lot

    def predict_proba(self, x: np.ndarray) -> float:
        """Return calibrated P(profitable) for a single feature vector."""
        x = np.asarray(x, dtype=np.float64).reshape(1, -1)
        if hasattr(self.model, "predict_proba"):
            return float(self.model.predict_proba(x)[0, 1])
        # Fallback for raw XGBoost
        if hasattr(self.model, "predict"):
            return float(self.model.predict(x)[0])
        raise AttributeError("model has no predict_proba/predict")

    def size_trade(self, x: np.ndarray, payoff_ratio: float = 2.0) -> dict:
        """Compute final lot size from feature vector.

        Returns:
            skip: True if probability below threshold (no edge)
            prob: calibrated P(profitable)
            kelly_f: Kelly fraction (after cap)
            lot: base_lot × kelly_f / DEFAULT_KELLY_CAP (so half-Kelly = base_lot)
        """
        prob = self.predict_proba(x)
        if prob < self.min_prob_threshold:
            return {"skip": True, "prob": prob, "kelly_f": 0.0, "lot": 0.0}
        kf = kelly_fraction(prob, payoff_ratio=payoff_ratio)
        # Normalize: at p=threshold → kf~0, at p=1 → kf=cap. Scale so
        # at p=0.55 (threshold) lot ≈ 0.5×base, at p=0.75+ lot ≈ base.
        normalized = kf / DEFAULT_KELLY_CAP
        lot = self.base_lot * normalized
        return {"skip": False, "prob": prob, "kelly_f": kf, "lot": round(lot, 4)}

    # ── Persistence ───────────────────────────────────────────────────

    def save(self, path: Path = DEFAULT_PKL) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "min_prob_threshold": self.min_prob_threshold,
                "base_lot": self.base_lot,
                "version": 1,
            }, f)

    @classmethod
    def load(cls, path: Path = DEFAULT_PKL) -> Optional["MetaLabeler"]:
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
            return cls(
                model=data["model"],
                feature_names=data["feature_names"],
                min_prob_threshold=data.get("min_prob_threshold", MIN_PROB_THRESHOLD),
                base_lot=data.get("base_lot", 0.01),
            )
        except Exception:
            return None


# ── Training ──────────────────────────────────────────────────────────

def fit_meta_labeler(X: np.ndarray, y: np.ndarray, feature_names: list[str],
                     base_lot: float = 0.01,
                     min_prob_threshold: float = MIN_PROB_THRESHOLD) -> MetaLabeler:
    """Fit calibrated binary classifier from (features, outcome) pairs.

    Args:
        X: (n, n_features) — features computed at trade-open time
        y: (n,) — binary {0=LOSS, 1=WIN_or_PROFIT}
        feature_names: column names matching X
        base_lot: lot size at half-Kelly (full prob mid-range)

    Returns fitted MetaLabeler.
    """
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    try:
        from xgboost import XGBClassifier
        base = XGBClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            objective="binary:logistic", eval_metric="logloss",
            verbosity=0,
        )
    except ImportError:
        base = LogisticRegression(max_iter=1000)

    # CalibratedClassifierCV with isotonic — Lopez de Prado recommended for
    # binary edge classification (better than sigmoid when training set ≥1k)
    method = "isotonic" if len(y) >= 1000 else "sigmoid"
    cv = min(5, max(2, len(y) // 50))
    clf = CalibratedClassifierCV(base, method=method, cv=cv)
    clf.fit(X, y)
    return MetaLabeler(model=clf, feature_names=feature_names,
                       min_prob_threshold=min_prob_threshold,
                       base_lot=base_lot)


def cli_fit():
    """Operator entry — fits from backtest.db trade outcomes."""
    import sqlite3, json
    db_path = ROOT / "data" / "backtest.db"
    if not db_path.exists():
        db_path = ROOT / "data" / "sentinel.db"
    if not db_path.exists():
        print("ERROR: no DB found")
        return 1
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT factors, status, setup_score, rsi, model_agreement "
        "FROM trades WHERE status IN ('WIN','LOSS','PROFIT') "
        "AND factors IS NOT NULL"
    ).fetchall()
    conn.close()
    if len(rows) < 50:
        print(f"ERROR: only {len(rows)} closed trades, need >=50")
        return 1

    # Build feature matrix from factors JSON + scoring features
    feat_keys: set[str] = set()
    for r in rows:
        try:
            feat_keys.update(json.loads(r[0]).keys())
        except Exception:
            continue
    feat_keys.update({"setup_score", "rsi", "model_agreement"})
    feature_names = sorted(feat_keys)

    X = []
    y = []
    for r in rows:
        try:
            facts = json.loads(r[0]) if r[0] else {}
        except Exception:
            facts = {}
        row = []
        for fn in feature_names:
            if fn == "setup_score":     row.append(float(r[2] or 0))
            elif fn == "rsi":            row.append(float(r[3] or 50))
            elif fn == "model_agreement": row.append(float(r[4] or 0))
            else:                        row.append(float(facts.get(fn, 0)))
        X.append(row)
        y.append(1 if r[1] in ("WIN", "PROFIT") else 0)
    X = np.array(X, dtype=np.float64)
    y = np.array(y, dtype=np.int64)
    print(f"[meta] fitting on {len(y)} trades, WR={y.mean():.2%}, "
          f"{X.shape[1]} features")

    ml = fit_meta_labeler(X, y, feature_names)
    ml.save(DEFAULT_PKL)
    # Quick OOS-ish print
    p_train = ml.predict_proba(X[0]) if len(X) > 0 else None
    print(f"[meta] saved to {DEFAULT_PKL}, sample prob: {p_train}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(cli_fit())
