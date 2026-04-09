"""
ensemble_voting.py — LEGACY: Simple ensemble voting.

DEPRECATED: Use ensemble_models.py instead — it provides:
- Dynamic weights from database (self-learning)
- Regime-dependent weight adjustment
- Platt Scaling calibration
- Model agreement filter
- Signal confirmation pipeline

This module is kept for backwards compatibility with test_ensemble_integration.py.
"""

import numpy as np
from typing import Dict, Tuple, List
from src.logger import logger

class EnsembleVoter:
    """Combines predictions from multiple ML models."""

    def __init__(self, xgb_weight=0.4, lstm_weight=0.35, dqn_weight=0.25):
        """
        Initialize ensemble voter with model weights.

        Args:
            xgb_weight: Weight for XGBoost predictions (0-1)
            lstm_weight: Weight for LSTM predictions (0-1)
            dqn_weight: Weight for DQN predictions (0-1)
        """
        # Normalize weights to sum to 1
        total = xgb_weight + lstm_weight + dqn_weight
        self.xgb_weight = xgb_weight / total
        self.lstm_weight = lstm_weight / total
        self.dqn_weight = dqn_weight / total

        # Performance tracking
        self.predictions_count = 0
        self.correct_predictions = 0
        self.vote_history = []

        logger.info(f"Ensemble Voter initialized - XGB: {self.xgb_weight:.2%}, "
                   f"LSTM: {self.lstm_weight:.2%}, DQN: {self.dqn_weight:.2%}")

    def vote(self,
             xgb_prob: float,
             lstm_prob: float,
             dqn_action: int) -> Tuple[str, float, Dict]:
        """
        Combine predictions from all models using weighted voting.

        Args:
            xgb_prob: XGBoost probability of UP (0-1)
            lstm_prob: LSTM probability of UP (0-1)
            dqn_action: DQN action (0=HOLD, 1=BUY, 2=SELL)

        Returns:
            Tuple of:
            - decision: "LONG", "SHORT", or "HOLD"
            - confidence: Confidence score (0-1)
            - details: Detailed voting information
        """
        # Convert DQN action to probability (1=UP, 2=DOWN)
        dqn_prob = 0.7 if dqn_action == 1 else (0.3 if dqn_action == 2 else 0.5)

        # Weighted average
        weighted_prob = (
            self.xgb_weight * xgb_prob +
            self.lstm_weight * lstm_prob +
            self.dqn_weight * dqn_prob
        )

        # Determine direction
        if weighted_prob > 0.6:
            decision = "LONG"
            confidence = min(weighted_prob, 0.95)
        elif weighted_prob < 0.4:
            decision = "SHORT"
            confidence = min(1 - weighted_prob, 0.95)
        else:
            decision = "HOLD"
            confidence = abs(weighted_prob - 0.5) * 2  # Closer to 0.5 = lower confidence

        # Count individual model votes
        xgb_vote = "UP" if xgb_prob > 0.5 else "DOWN"
        lstm_vote = "UP" if lstm_prob > 0.5 else "DOWN"
        dqn_vote = "UP" if dqn_action == 1 else ("DOWN" if dqn_action == 2 else "HOLD")

        # Voting agreement
        up_votes = sum([xgb_vote == "UP", lstm_vote == "UP", dqn_vote == "UP"])
        down_votes = sum([xgb_vote == "DOWN", lstm_vote == "DOWN", dqn_vote == "DOWN"])
        agreement_level = max(up_votes, down_votes, 0) / 3.0

        details = {
            'xgb_prob': round(xgb_prob, 3),
            'lstm_prob': round(lstm_prob, 3),
            'dqn_action': dqn_action,
            'weighted_prob': round(weighted_prob, 3),
            'xgb_vote': xgb_vote,
            'lstm_vote': lstm_vote,
            'dqn_vote': dqn_vote,
            'up_votes': up_votes,
            'down_votes': down_votes,
            'agreement_level': round(agreement_level, 2),
        }

        # Record in history
        self.vote_history.append({
            'decision': decision,
            'confidence': confidence,
            'details': details
        })
        self.predictions_count += 1

        return decision, confidence, details

    def update_weights(self, xgb_weight=None, lstm_weight=None, dqn_weight=None):
        """Update model weights based on performance."""
        if xgb_weight is not None:
            self.xgb_weight = xgb_weight
        if lstm_weight is not None:
            self.lstm_weight = lstm_weight
        if dqn_weight is not None:
            self.dqn_weight = dqn_weight

        # Re-normalize
        total = self.xgb_weight + self.lstm_weight + self.dqn_weight
        self.xgb_weight /= total
        self.lstm_weight /= total
        self.dqn_weight /= total

        logger.info(f"Ensemble weights updated - XGB: {self.xgb_weight:.2%}, "
                   f"LSTM: {self.lstm_weight:.2%}, DQN: {self.dqn_weight:.2%}")

    def get_statistics(self) -> Dict:
        """Get ensemble voting statistics."""
        if not self.vote_history:
            return {}

        recent = self.vote_history[-100:]  # Last 100 votes

        long_votes = sum(1 for v in recent if v['decision'] == 'LONG')
        short_votes = sum(1 for v in recent if v['decision'] == 'SHORT')
        hold_votes = sum(1 for v in recent if v['decision'] == 'HOLD')

        avg_confidence = np.mean([v['confidence'] for v in recent])
        avg_agreement = np.mean([v['details']['agreement_level'] for v in recent])

        return {
            'total_votes': len(self.vote_history),
            'recent_long': long_votes,
            'recent_short': short_votes,
            'recent_hold': hold_votes,
            'avg_confidence': round(avg_confidence, 3),
            'avg_agreement_level': round(avg_agreement, 3),
            'weights': {
                'xgb': round(self.xgb_weight, 3),
                'lstm': round(self.lstm_weight, 3),
                'dqn': round(self.dqn_weight, 3),
            }
        }


# Global ensemble voter instance
ensemble_voter = EnsembleVoter(xgb_weight=0.4, lstm_weight=0.35, dqn_weight=0.25)
ensemble_stacking = None  # Removed: unused EnsembleStacking class

