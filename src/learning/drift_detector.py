"""
src/learning/drift_detector.py — concept drift detection for trade outcomes.

2026-05-04: shipped per learning system audit. Walk-forward analysis
showed Fold 4 WR dropped -18.4pp vs older folds = real concept drift.
Without auto-detection, recent regime anomaly looks like new baseline
and tunes models to it.

Two complementary methods:

1. **Page-Hinkley test** — cumulative deviation from rolling mean.
   Triggers when sum-of-deviations exceeds threshold. Fast, lightweight,
   good for trend changes (e.g., WR slowly declining).

2. **PSI (Population Stability Index)** — feature distribution shift.
   Compares recent feature histogram vs reference. Triggers on
   distributional changes (e.g., RSI cluster shifts to lower values).

Output: drift score per detector, overall verdict (stable / warn /
drifted). Soft signal — never auto-disables models, just alerts.

Usage:
    from src.learning.drift_detector import detect_drift
    result = detect_drift(reference_window=90, recent_window=30)
    if result["verdict"] == "drifted":
        logger.warning(...)
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


# ── Page-Hinkley test ─────────────────────────────────────────────────

class PageHinkleyDetector:
    """Page-Hinkley test for trend changes in WR.

    Tracks cumulative sum of (x_t - reference_mean - delta).
    Detects when sum exceeds threshold (drift) or recovers below
    minimum (no drift).

    Recommended params for trade outcomes:
      delta = 0.005  # tolerance — ignore tiny shifts
      threshold = 0.05  # WR change of 5pp triggers
    """
    def __init__(self, delta: float = 0.005, threshold: float = 0.05):
        self.delta = delta
        self.threshold = threshold
        self.cumulative = 0.0
        self.minimum = 0.0
        self.reference_mean: float | None = None
        self.n = 0

    def fit_reference(self, observations: list[float]) -> None:
        """Set reference distribution from baseline observations."""
        if not observations:
            return
        self.reference_mean = sum(observations) / len(observations)

    def update(self, x: float) -> bool:
        """Add new observation. Returns True if drift detected."""
        if self.reference_mean is None:
            return False
        self.cumulative += x - self.reference_mean - self.delta
        self.minimum = min(self.minimum, self.cumulative)
        self.n += 1
        return (self.cumulative - self.minimum) > self.threshold

    def reset(self) -> None:
        """Reset after drift confirmed (start tracking new reference)."""
        self.cumulative = 0.0
        self.minimum = 0.0
        self.n = 0


# ── PSI (Population Stability Index) ──────────────────────────────────

def psi(reference: list[float], recent: list[float], n_bins: int = 10) -> float:
    """Population Stability Index.

    PSI < 0.1 → no significant change
    0.1 <= PSI < 0.25 → moderate change, monitor
    PSI >= 0.25 → major change, retrain consideration

    Args:
        reference: historical baseline (sorted ok, no need)
        recent: current window
        n_bins: histogram bin count

    Returns: float (>=0). None if insufficient data.
    """
    if len(reference) < n_bins or len(recent) < 5:
        return 0.0

    # Use reference quantiles as bin edges
    sorted_ref = sorted(reference)
    edges = [sorted_ref[int(len(sorted_ref) * i / n_bins)] for i in range(n_bins)]
    edges.append(sorted_ref[-1] + 1e-9)

    def histogram(vals: list[float]) -> list[float]:
        n = len(vals)
        counts = [0] * n_bins
        for v in vals:
            # Find bin (linear scan, fine for small n_bins)
            for i in range(n_bins):
                if v <= edges[i + 1]:
                    counts[i] += 1
                    break
        # Normalize + epsilon to avoid log(0)
        return [(c + 0.5) / (n + n_bins * 0.5) for c in counts]

    ref_dist = histogram(reference)
    rec_dist = histogram(recent)

    return sum(
        (rec - ref) * math.log(rec / ref)
        for ref, rec in zip(ref_dist, rec_dist)
    )


# ── Top-level detector ────────────────────────────────────────────────

def _fetch_outcomes(db_path: str, days_back: int) -> list[dict[str, Any]]:
    """Pull closed trades + their outcomes + key features."""
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT id, timestamp, status, profit, rsi, setup_score
           FROM trades
           WHERE status IN ('WIN','LOSS') AND timestamp >= ?
           ORDER BY timestamp""",
        (cutoff,)
    ).fetchall()
    conn.close()
    cols = ["id", "timestamp", "status", "profit", "rsi", "setup_score"]
    return [dict(zip(cols, r)) for r in rows]


def detect_drift(
    db_path: str | None = None,
    reference_days: int = 90,
    recent_days: int = 14,
) -> dict[str, Any]:
    """Run all drift detectors and return verdict.

    Args:
        db_path: path to sentinel.db (default: data/sentinel.db)
        reference_days: baseline window
        recent_days: current window to compare

    Returns dict:
        verdict: "stable" | "warn" | "drifted"
        wr_recent: float
        wr_reference: float
        wr_delta_pp: float (recent - reference, in percentage points)
        page_hinkley_alert: bool
        psi_rsi: float
        psi_score: float
        n_recent: int
        n_reference: int
    """
    db_path = db_path or str(ROOT / "data" / "sentinel.db")
    all_trades = _fetch_outcomes(db_path, reference_days + recent_days + 10)

    if len(all_trades) < 30:
        return {
            "verdict": "insufficient_data",
            "n_total": len(all_trades),
        }

    cutoff_recent = datetime.now() - timedelta(days=recent_days)
    cutoff_ref_lo = datetime.now() - timedelta(days=reference_days + recent_days)

    def _parse(ts: str) -> datetime:
        try:
            return datetime.strptime(ts.split("+")[0].split(".")[0], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    reference = [t for t in all_trades
                 if cutoff_ref_lo <= _parse(t["timestamp"]) < cutoff_recent]
    recent = [t for t in all_trades if _parse(t["timestamp"]) >= cutoff_recent]

    if len(reference) < 10 or len(recent) < 5:
        return {
            "verdict": "insufficient_data",
            "n_recent": len(recent),
            "n_reference": len(reference),
        }

    # WR delta
    wr_ref = sum(1 for t in reference if t["status"] == "WIN") / len(reference)
    wr_rec = sum(1 for t in recent if t["status"] == "WIN") / len(recent)
    wr_delta_pp = (wr_rec - wr_ref) * 100

    # Page-Hinkley on chronological win/loss sequence
    ph = PageHinkleyDetector(delta=0.005, threshold=0.10)
    ref_outcomes = [1.0 if t["status"] == "WIN" else 0.0 for t in reference]
    rec_outcomes = [1.0 if t["status"] == "WIN" else 0.0 for t in recent]
    ph.fit_reference(ref_outcomes)
    ph_alert = False
    for x in rec_outcomes:
        if ph.update(x):
            ph_alert = True
            break

    # PSI on RSI distribution
    rsi_ref = [float(t["rsi"]) for t in reference if t.get("rsi") is not None]
    rsi_rec = [float(t["rsi"]) for t in recent if t.get("rsi") is not None]
    psi_rsi = psi(rsi_ref, rsi_rec) if len(rsi_ref) >= 10 and len(rsi_rec) >= 5 else 0.0

    # PSI on setup_score
    sc_ref = [float(t["setup_score"]) for t in reference if t.get("setup_score") is not None]
    sc_rec = [float(t["setup_score"]) for t in recent if t.get("setup_score") is not None]
    psi_score = psi(sc_ref, sc_rec) if len(sc_ref) >= 10 and len(sc_rec) >= 5 else 0.0

    # Verdict
    drifted_signals = 0
    if abs(wr_delta_pp) >= 10.0:
        drifted_signals += 1
    if ph_alert:
        drifted_signals += 1
    if psi_rsi >= 0.25:
        drifted_signals += 1
    if psi_score >= 0.25:
        drifted_signals += 1

    if drifted_signals >= 2:
        verdict = "drifted"
    elif drifted_signals == 1:
        verdict = "warn"
    else:
        verdict = "stable"

    return {
        "verdict": verdict,
        "wr_recent": round(wr_rec * 100, 1),
        "wr_reference": round(wr_ref * 100, 1),
        "wr_delta_pp": round(wr_delta_pp, 1),
        "page_hinkley_alert": ph_alert,
        "psi_rsi": round(psi_rsi, 3),
        "psi_score": round(psi_score, 3),
        "n_recent": len(recent),
        "n_reference": len(reference),
        "drifted_signals": drifted_signals,
    }


def cli_main():
    """Standalone diagnostic — operator runs to check drift state."""
    import json
    result = detect_drift()
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") in ("stable", "insufficient_data") else 1


if __name__ == "__main__":
    import sys
    sys.exit(cli_main())
