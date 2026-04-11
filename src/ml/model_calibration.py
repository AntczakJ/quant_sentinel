"""
src/model_calibration.py — Prediction Calibration for ML Ensemble

Problem: LSTM, XGBoost, and DQN output scores on different scales.
- LSTM outputs often extreme (0.95+ or <0.05)
- XGBoost outputs well-calibrated probabilities
- DQN outputs softmax Q-values (not true probabilities)

Solution: Platt Scaling (sigmoid calibration) — fits a logistic regression
on model outputs vs actual outcomes to map raw scores → true probabilities.

Usage:
  calibrator = ModelCalibrator()
  calibrated = calibrator.calibrate("lstm", raw_prediction)
"""

import os
import pickle
import numpy as np
from typing import Optional, Dict
from src.core.logger import logger

CALIBRATION_DIR = "models"
CALIBRATION_FILE = os.path.join(CALIBRATION_DIR, "calibration_params.pkl")

# Minimum predictions needed to fit calibration
MIN_CALIBRATION_SAMPLES = 50


class PlattScaler:
    """Platt Scaling: fits sigmoid P(y=1|f) = 1 / (1 + exp(A*f + B))"""

    def __init__(self):
        self.a = -1.0  # Default: identity-ish (no strong transformation)
        self.b = 0.0
        self.fitted = False

    def fit(self, predictions: np.ndarray, labels: np.ndarray):
        """
        Fit Platt parameters A, B using Newton's method.

        predictions: raw model outputs (0-1 range)
        labels: actual binary outcomes (0 or 1)
        """
        if len(predictions) < MIN_CALIBRATION_SAMPLES:
            return

        # Platt's target: avoid 0/1 targets for numerical stability
        n_pos = np.sum(labels == 1)
        n_neg = np.sum(labels == 0)
        if n_pos == 0 or n_neg == 0:
            return

        target = np.where(labels == 1,
                          (n_pos + 1) / (n_pos + 2),
                          1 / (n_neg + 2))

        # Gradient descent for A, B (simplified Newton's method)
        a, b = 0.0, 0.0
        lr = 0.01

        for _ in range(200):
            f_val = a * predictions + b
            p = 1.0 / (1.0 + np.exp(-f_val))
            p = np.clip(p, 1e-7, 1 - 1e-7)

            # Gradient
            d = p - target
            grad_a = np.dot(d, predictions) / len(predictions)
            grad_b = np.mean(d)

            a -= lr * grad_a
            b -= lr * grad_b

        self.a = float(a)
        self.b = float(b)
        self.fitted = True

    def transform(self, prediction: float) -> float:
        """Apply Platt scaling to a single prediction."""
        if not self.fitted:
            return prediction
        f_val = self.a * prediction + self.b
        return float(1.0 / (1.0 + np.exp(-f_val)))

    def to_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "fitted": self.fitted}

    @classmethod
    def from_dict(cls, d: dict) -> "PlattScaler":
        s = cls()
        s.a = d.get("a", -1.0)
        s.b = d.get("b", 0.0)
        s.fitted = d.get("fitted", False)
        return s


class ModelCalibrator:
    """
    Manages calibration parameters for all models in the ensemble.
    Persists to disk so calibration survives restarts.
    """

    def __init__(self):
        self._scalers: Dict[str, PlattScaler] = {}
        self._load()

    def _load(self):
        """Load calibration parameters from disk."""
        try:
            if os.path.exists(CALIBRATION_FILE):
                with open(CALIBRATION_FILE, 'rb') as f:
                    data = pickle.load(f)
                for name, params in data.items():
                    self._scalers[name] = PlattScaler.from_dict(params)
                logger.info(f"Loaded calibration for: {list(data.keys())}")
        except (FileNotFoundError, pickle.UnpicklingError, EOFError, KeyError) as e:
            logger.debug(f"No calibration params found: {e}")

    def _save(self):
        """Persist calibration parameters to disk."""
        try:
            os.makedirs(CALIBRATION_DIR, exist_ok=True)
            data = {name: s.to_dict() for name, s in self._scalers.items()}
            tmp_file = CALIBRATION_FILE + '.tmp'
            with open(tmp_file, 'wb') as f:
                pickle.dump(data, f)
            os.replace(tmp_file, CALIBRATION_FILE)
        except (OSError, pickle.PicklingError) as e:
            logger.warning(f"Could not save calibration: {e}")

    def fit_from_history(self, model_name: str):
        """
        Fit Platt scaling from historical predictions stored in ml_predictions table.

        Matches predictions with trade outcomes to create (prediction, label) pairs.
        """
        try:
            from src.core.database import NewsDB
            db = NewsDB()

            # Get recent predictions with their outcomes
            rows = db._query("""
                SELECT mp.lstm_pred, mp.xgb_pred, mp.dqn_action,
                       mp.ensemble_signal, t.status
                FROM ml_predictions mp
                JOIN trades t ON DATE(mp.timestamp) = DATE(t.timestamp)
                    AND ABS(julianday(mp.timestamp) - julianday(t.timestamp)) < 0.02
                WHERE t.status IN ('WIN', 'LOSS')
                ORDER BY mp.id DESC
                LIMIT 200
            """)

            if not rows or len(rows) < MIN_CALIBRATION_SAMPLES:
                logger.info(f"Calibration: not enough data for {model_name} ({len(rows or [])} < {MIN_CALIBRATION_SAMPLES})")
                return

            predictions = []
            labels = []

            for row in rows:
                lstm_pred, xgb_pred, dqn_action, _, status = row
                label = 1 if status == 'WIN' else 0

                if model_name == "lstm" and lstm_pred is not None:
                    predictions.append(float(lstm_pred))
                    labels.append(label)
                elif model_name == "xgb" and xgb_pred is not None:
                    predictions.append(float(xgb_pred))
                    labels.append(label)
                elif model_name == "dqn" and dqn_action is not None:
                    # DQN: map action to signal (0=0.5, 1=0.8, 2=0.2)
                    dqn_signal = {0: 0.5, 1: 0.8, 2: 0.2}.get(int(dqn_action), 0.5)
                    predictions.append(dqn_signal)
                    labels.append(label)

            if len(predictions) < MIN_CALIBRATION_SAMPLES:
                return

            preds_arr = np.array(predictions)
            labels_arr = np.array(labels)

            scaler = PlattScaler()
            scaler.fit(preds_arr, labels_arr)
            self._scalers[model_name] = scaler
            self._save()

            logger.info(
                f"Calibration fitted for {model_name}: "
                f"A={scaler.a:.4f}, B={scaler.b:.4f} (n={len(predictions)})"
            )

        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Calibration fit failed for {model_name}: {e}")

    def calibrate(self, model_name: str, raw_prediction: float) -> float:
        """
        Calibrate a raw prediction using Platt scaling.
        Returns raw prediction unchanged if no calibration is available.
        """
        if model_name in self._scalers:
            calibrated = self._scalers[model_name].transform(raw_prediction)
            return calibrated
        return raw_prediction

    def is_calibrated(self, model_name: str) -> bool:
        return model_name in self._scalers and self._scalers[model_name].fitted

    def fit_all(self):
        """Fit calibration for all models from historical data."""
        for name in ["lstm", "xgb", "dqn"]:
            self.fit_from_history(name)

    def get_status(self) -> dict:
        return {
            name: {
                "calibrated": s.fitted,
                "a": round(s.a, 4),
                "b": round(s.b, 4)
            }
            for name, s in self._scalers.items()
        }


# Module-level singleton
_calibrator: Optional[ModelCalibrator] = None


def get_calibrator() -> ModelCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = ModelCalibrator()
    return _calibrator
