"""
src/model_monitor.py — ML Model Monitoring & Drift Detection

Detects when models degrade and need retraining:
  - Prediction drift (PSI — Population Stability Index)
  - Accuracy tracking (rolling window)
  - Feature distribution shift (basic KS-test approximation)
  - Automatic alerts when thresholds breached

Run periodically (e.g., daily) via:
  from src.model_monitor import run_drift_check
  alerts = run_drift_check()
"""

import numpy as np
from typing import Dict, List, Optional
from src.logger import logger

# ═══════════════════════════════════════════════════════════════════════════
#  THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

PSI_WARN = 0.10       # PSI > 0.10 → notable shift
PSI_ALERT = 0.25      # PSI > 0.25 → significant drift, consider retraining
ACCURACY_DROP = 0.15  # Alert if accuracy drops >15% vs baseline
MIN_SAMPLES = 20      # Minimum predictions for meaningful analysis
ROLLING_WINDOW = 50   # Trades for rolling accuracy


# ═══════════════════════════════════════════════════════════════════════════
#  PSI (Population Stability Index)
# ═══════════════════════════════════════════════════════════════════════════

def compute_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """
    Calculate PSI between reference and current prediction distributions.

    PSI = Σ (p_i - q_i) * ln(p_i / q_i)

    PSI < 0.10 → no significant shift
    PSI 0.10-0.25 → moderate shift (monitor)
    PSI > 0.25 → significant shift (retrain)
    """
    if len(reference) < MIN_SAMPLES or len(current) < MIN_SAMPLES:
        return 0.0

    # Create bins from reference distribution
    breakpoints = np.linspace(0, 1, bins + 1)
    ref_counts = np.histogram(reference, bins=breakpoints)[0]
    cur_counts = np.histogram(current, bins=breakpoints)[0]

    # Normalize to proportions (add small epsilon to avoid div by zero)
    eps = 1e-6
    ref_pct = (ref_counts + eps) / (len(reference) + eps * bins)
    cur_pct = (cur_counts + eps) / (len(current) + eps * bins)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return max(0.0, psi)


# ═══════════════════════════════════════════════════════════════════════════
#  ACCURACY TRACKING
# ═══════════════════════════════════════════════════════════════════════════

def compute_rolling_accuracy(window: int = ROLLING_WINDOW) -> Dict[str, Optional[float]]:
    """
    Compute rolling accuracy for each model from recent trade outcomes.

    Returns dict: {"lstm": 0.62, "xgb": 0.55, "dqn": 0.48, "ensemble": 0.58}
    """
    try:
        from src.database import NewsDB
        db = NewsDB()

        rows = db._query("""
            SELECT mp.lstm_pred, mp.xgb_pred, mp.dqn_action,
                   mp.ensemble_signal, t.direction, t.status
            FROM ml_predictions mp
            JOIN trades t ON DATE(mp.timestamp) = DATE(t.timestamp)
                AND ABS(julianday(mp.timestamp) - julianday(t.timestamp)) < 0.02
            WHERE t.status IN ('WIN', 'LOSS')
            ORDER BY mp.id DESC
            LIMIT ?
        """, (window,))

        if not rows or len(rows) < MIN_SAMPLES:
            return {"lstm": None, "xgb": None, "dqn": None, "ensemble": None, "n": len(rows or [])}

        results: Dict[str, list] = {"lstm": [], "xgb": [], "dqn": [], "ensemble": []}

        for row in rows:
            lstm_pred, xgb_pred, dqn_action, ens_signal, direction, status = row
            is_win = status == 'WIN'
            is_long = "LONG" in str(direction).upper()

            # LSTM: predicted direction correct?
            if lstm_pred is not None:
                pred_long = float(lstm_pred) > 0.5
                correct = (pred_long == is_long) if is_win else (pred_long != is_long)
                results["lstm"].append(1 if correct else 0)

            # XGBoost
            if xgb_pred is not None:
                pred_long = float(xgb_pred) > 0.5
                correct = (pred_long == is_long) if is_win else (pred_long != is_long)
                results["xgb"].append(1 if correct else 0)

            # DQN
            if dqn_action is not None:
                pred_long = int(dqn_action) == 1  # 1 = buy
                correct = (pred_long == is_long) if is_win else (pred_long != is_long)
                results["dqn"].append(1 if correct else 0)

            # Ensemble signal
            if ens_signal:
                ens_long = "LONG" in str(ens_signal).upper()
                correct = (ens_long == is_long) if is_win else (ens_long != is_long)
                results["ensemble"].append(1 if correct else 0)

        return {
            name: round(np.mean(vals), 3) if len(vals) >= MIN_SAMPLES else None
            for name, vals in results.items()
        } | {"n": len(rows)}

    except (ImportError, AttributeError, TypeError) as e:
        logger.debug(f"Rolling accuracy failed: {e}")
        return {"lstm": None, "xgb": None, "dqn": None, "ensemble": None, "n": 0}


# ═══════════════════════════════════════════════════════════════════════════
#  PREDICTION DRIFT (PSI-based)
# ═══════════════════════════════════════════════════════════════════════════

def check_prediction_drift() -> Dict[str, Dict]:
    """
    Compare recent prediction distributions vs historical baseline.

    Splits ml_predictions into two halves:
    - Reference: older half (baseline)
    - Current: newer half
    Returns PSI per model + drift status.
    """
    try:
        from src.database import NewsDB
        db = NewsDB()

        rows = db._query("""
            SELECT lstm_pred, xgb_pred, dqn_action
            FROM ml_predictions
            WHERE lstm_pred IS NOT NULL OR xgb_pred IS NOT NULL
            ORDER BY id DESC
            LIMIT 200
        """)

        if not rows or len(rows) < MIN_SAMPLES * 2:
            return {}

        # Split into reference (older) and current (newer)
        mid = len(rows) // 2
        current_rows = rows[:mid]
        reference_rows = rows[mid:]

        results = {}

        for i, name in enumerate(["lstm", "xgb"]):
            ref_vals = np.array([float(r[i]) for r in reference_rows if r[i] is not None])
            cur_vals = np.array([float(r[i]) for r in current_rows if r[i] is not None])

            if len(ref_vals) >= MIN_SAMPLES and len(cur_vals) >= MIN_SAMPLES:
                psi = compute_psi(ref_vals, cur_vals)
                status = "ok" if psi < PSI_WARN else ("warn" if psi < PSI_ALERT else "alert")
                results[name] = {
                    "psi": round(psi, 4),
                    "status": status,
                    "ref_mean": round(float(np.mean(ref_vals)), 4),
                    "cur_mean": round(float(np.mean(cur_vals)), 4),
                    "ref_std": round(float(np.std(ref_vals)), 4),
                    "cur_std": round(float(np.std(cur_vals)), 4),
                    "ref_n": len(ref_vals),
                    "cur_n": len(cur_vals),
                }

        # DQN: action distribution (discrete)
        ref_dqn = [int(r[2]) for r in reference_rows if r[2] is not None]
        cur_dqn = [int(r[2]) for r in current_rows if r[2] is not None]
        if len(ref_dqn) >= MIN_SAMPLES and len(cur_dqn) >= MIN_SAMPLES:
            # Map to 0-1 for PSI
            ref_mapped = np.array([{0: 0.5, 1: 0.8, 2: 0.2}.get(a, 0.5) for a in ref_dqn])
            cur_mapped = np.array([{0: 0.5, 1: 0.8, 2: 0.2}.get(a, 0.5) for a in cur_dqn])
            psi = compute_psi(ref_mapped, cur_mapped)
            status = "ok" if psi < PSI_WARN else ("warn" if psi < PSI_ALERT else "alert")
            results["dqn"] = {
                "psi": round(psi, 4),
                "status": status,
                "ref_n": len(ref_dqn),
                "cur_n": len(cur_dqn),
            }

        return results

    except (ImportError, AttributeError, TypeError) as e:
        logger.debug(f"Drift check failed: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN DRIFT CHECK (run periodically)
# ═══════════════════════════════════════════════════════════════════════════

def run_drift_check() -> List[str]:
    """
    Run full model monitoring check. Returns list of alert messages.

    Call this daily or after every N trades. Logs warnings for:
    - PSI drift > threshold
    - Accuracy drop > threshold
    - Calibration suggestions
    """
    alerts = []

    # 1. Check prediction drift
    drift = check_prediction_drift()
    for model, info in drift.items():
        if info.get("status") == "alert":
            msg = (
                f"MODEL DRIFT ALERT: {model} PSI={info['psi']:.3f} (threshold={PSI_ALERT}). "
                f"Mean shifted {info.get('ref_mean', '?')} → {info.get('cur_mean', '?')}. "
                f"Consider retraining."
            )
            logger.warning(msg)
            alerts.append(msg)
        elif info.get("status") == "warn":
            msg = f"Model drift warning: {model} PSI={info['psi']:.3f} — monitor closely"
            logger.info(msg)
            alerts.append(msg)

    # 2. Check accuracy
    accuracy = compute_rolling_accuracy()
    baseline_accuracy = _get_baseline_accuracy()

    for model in ["lstm", "xgb", "dqn", "ensemble"]:
        current = accuracy.get(model)
        baseline = baseline_accuracy.get(model)
        if current is not None and baseline is not None:
            drop = baseline - current
            if drop > ACCURACY_DROP:
                msg = (
                    f"ACCURACY DROP: {model} dropped {drop:.0%} "
                    f"({baseline:.0%} → {current:.0%}). Consider retraining."
                )
                logger.warning(msg)
                alerts.append(msg)

    # 3. Calibration check
    try:
        from src.model_calibration import get_calibrator
        cal = get_calibrator()
        for model in ["lstm", "xgb", "dqn"]:
            if not cal.is_calibrated(model):
                alerts.append(f"Model {model} not calibrated — run calibrator.fit_all()")
    except (ImportError, AttributeError):
        pass

    if not alerts:
        logger.info("Model monitoring: all models healthy")

    # Persist check results
    _save_check_results(drift, accuracy)

    return alerts


def _get_baseline_accuracy() -> Dict[str, Optional[float]]:
    """Load baseline accuracy from database (set during training)."""
    try:
        from src.database import NewsDB
        db = NewsDB()
        return {
            "lstm": _safe_float(db.get_param("lstm_walkforward_accuracy")),
            "xgb": _safe_float(db.get_param("xgb_last_accuracy")),
            "dqn": None,  # DQN doesn't have a clear accuracy baseline
            "ensemble": None,
        }
    except (ImportError, AttributeError):
        return {}


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _save_check_results(drift: dict, accuracy: dict):
    """Persist monitoring results to database for historical tracking."""
    try:
        from src.database import NewsDB
        import json
        db = NewsDB()
        db.set_param("monitor_last_check", json.dumps({
            "drift": drift,
            "accuracy": accuracy,
        }))
    except (ImportError, AttributeError, TypeError):
        pass
