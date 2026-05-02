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

        Uses CORRECTED LABELS (2026-05-02 fix): the model's raw output is
        P(LONG wins). For Platt to fit a sane positive `a`, the binary
        label must equal 1 iff "LONG would have won at this bar".

          - LONG WIN  → LONG won            → label = 1
          - LONG LOSS → LONG lost           → label = 0
          - SHORT WIN → SHORT won = LONG    → label = 0
                        would have lost
          - SHORT LOSS → SHORT lost = LONG  → label = 1
                         would have won

        Previous implementation used label=(status=='WIN') across mixed
        directions, which broke the correlation: high raw with SHORT WIN
        (= LONG would lose, label=1 in old impl) → spurious negative `a`.

        Per-direction scalers were considered but rejected: at our cohort
        size (~50 trades) we barely meet MIN_CALIBRATION_SAMPLES=50 with
        all directions pooled; splitting halves data per direction.
        """
        try:
            from src.core.database import NewsDB
            db = NewsDB()

            # Get recent predictions joined with their TRADE direction
            # (added 2026-05-02 — was previously missing).
            rows = db._query("""
                SELECT mp.lstm_pred, mp.xgb_pred, mp.dqn_action,
                       mp.smc_pred, mp.attention_pred, mp.deeptrans_pred,
                       mp.v2_xgb_pred,
                       mp.ensemble_signal, t.status, t.direction
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
                (lstm_pred, xgb_pred, dqn_action, smc_pred,
                 attn_pred, deeptrans_pred, v2_xgb_pred,
                 _ensemble_signal, status, direction) = row
                # CORRECTED LABEL: 1 iff LONG would have won
                long_would_win = (
                    (status == 'WIN' and direction == 'LONG')
                    or (status == 'LOSS' and direction == 'SHORT')
                )
                label = 1 if long_would_win else 0

                # Pick raw prediction by model name
                raw = None
                if model_name == "lstm" and lstm_pred is not None:
                    raw = float(lstm_pred)
                elif model_name == "xgb" and xgb_pred is not None:
                    raw = float(xgb_pred)
                elif model_name == "smc" and smc_pred is not None:
                    raw = float(smc_pred)
                elif model_name == "attention" and attn_pred is not None:
                    raw = float(attn_pred)
                elif model_name == "deeptrans" and deeptrans_pred is not None:
                    raw = float(deeptrans_pred)
                elif model_name == "v2_xgb" and v2_xgb_pred is not None:
                    raw = float(v2_xgb_pred)
                elif model_name == "dqn" and dqn_action is not None:
                    # DQN action 0=HOLD,1=BUY/LONG,2=SELL/SHORT.
                    # Map to P(LONG wins): action=1→0.8 (high P LONG),
                    # action=2→0.2 (low P LONG = high P SHORT), action=0→0.5
                    raw = {0: 0.5, 1: 0.8, 2: 0.2}.get(int(dqn_action), 0.5)

                if raw is not None:
                    predictions.append(raw)
                    labels.append(label)

            if len(predictions) < MIN_CALIBRATION_SAMPLES:
                logger.info(
                    f"Calibration {model_name}: only {len(predictions)} samples "
                    f"after filtering — need {MIN_CALIBRATION_SAMPLES}"
                )
                return

            preds_arr = np.array(predictions)
            labels_arr = np.array(labels)

            # Sanity: refuse to fit if labels are degenerate (all-1 or all-0)
            n_pos = int(np.sum(labels_arr == 1))
            n_neg = int(np.sum(labels_arr == 0))
            if n_pos == 0 or n_neg == 0:
                logger.warning(
                    f"Calibration {model_name}: degenerate labels "
                    f"(pos={n_pos} neg={n_neg}) — skipping fit"
                )
                return

            scaler = PlattScaler()
            scaler.fit(preds_arr, labels_arr)

            # 2026-05-02 safeguard: refuse to install a scaler with a<0.
            # Negative `a` means the sigmoid is monotonically decreasing
            # in the input — i.e., the calibrator would INVERT every
            # raw prediction. Almost always a sign of data prep bug
            # (label/direction mismatch). Better to leave model
            # uncalibrated than ship an inverter.
            if scaler.fitted and scaler.a < 0:
                logger.warning(
                    f"Calibration {model_name}: refused to install — "
                    f"fitted A={scaler.a:.4f} < 0 would invert predictions. "
                    f"Likely data issue (n_pos={n_pos}, n_neg={n_neg}). "
                    f"Leaving uncalibrated."
                )
                return

            self._scalers[model_name] = scaler
            self._save()

            logger.info(
                f"Calibration fitted for {model_name}: "
                f"A={scaler.a:.4f}, B={scaler.b:.4f} "
                f"(n={len(predictions)} pos={n_pos} neg={n_neg})"
            )

        except (ImportError, AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Calibration fit failed for {model_name}: {e}")

    def calibrate(self, model_name: str, raw_prediction: float) -> float:
        """
        Calibrate a raw prediction using Platt scaling.

        Kill-switch (2026-04-29): when env DISABLE_CALIBRATION=1, return raw
        unchanged — both the fitted Platt path AND the uncalibrated 20%
        shrinkage path are bypassed. Reason: audit `2026-04-29_audit_4_label_ensemble.md`
        revealed Platt was fit on TRADE outcomes (WIN/LOSS) regressed against
        P(LONG-wins) raw outputs from a mix of LONG and SHORT trades —
        meaningless correlation produced negative `a`, mathematically inverting
        every signal that hit the calibrator. Until per-direction calibration
        is rebuilt, raw passes through.

        If the model HAS a fitted scaler → apply it (well-behaved path).
        If the model has NO fitted scaler → apply mild shrinkage toward 0.5
        (the "uncalibrated penalty"). Uncalibrated raw scores are often
        overconfident (LSTM in particular — routinely outputs 0.97+ when
        its historical accuracy on those predictions is closer to 0.55).
        Shrinking 20% toward neutral damps their voting power in the
        ensemble until they earn calibration with enough history.
        """
        if os.environ.get("DISABLE_CALIBRATION") == "1":
            return float(raw_prediction)
        if model_name in self._scalers and self._scalers[model_name].fitted:
            return self._scalers[model_name].transform(raw_prediction)
        # Uncalibrated penalty: shrink toward 0.5
        shrunk = 0.5 + (raw_prediction - 0.5) * 0.8
        return float(shrunk)

    def is_calibrated(self, model_name: str) -> bool:
        return model_name in self._scalers and self._scalers[model_name].fitted

    def fit_all(self):
        """Fit calibration for all models from historical data.

        2026-05-02: extended from {lstm, xgb, dqn} to all 7 voters now
        that smc/attention/deeptrans/v2_xgb columns are populated by
        the muted-voter persistence fix (commit 1a253cf).
        """
        for name in ["lstm", "xgb", "smc", "attention", "deeptrans", "v2_xgb", "dqn"]:
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
