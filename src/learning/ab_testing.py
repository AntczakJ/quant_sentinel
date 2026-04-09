"""
src/ab_testing.py — A/B Testing Framework for Trading Parameters

New parameters are deployed to "shadow" mode first:
  1. Shadow params stored separately in DB (prefix: ab_shadow_)
  2. Each trade is evaluated with BOTH current and shadow params
  3. After N trades, compare performance
  4. If shadow outperforms with statistical significance → promote to live
  5. If shadow underperforms → discard

Usage:
  ab = ABTestManager()
  ab.propose_params({"risk_percent": 1.2, "target_rr": 3.0})  # start test
  ab.record_outcome(trade_id, "WIN", shadow_would_trade=True)  # per trade
  result = ab.evaluate()  # check if shadow should be promoted
"""

import datetime
import json
import math
from typing import Dict, Optional
from src.core.logger import logger


# Minimum trades before evaluating A/B test
MIN_AB_TRADES = 20

# Required improvement (shadow must be this much better than current)
MIN_IMPROVEMENT_PCT = 5.0  # 5% better win rate or equity

# Statistical significance threshold (simplified z-test)
MIN_Z_SCORE = 1.65  # ~95% confidence (one-tailed)


class ABTestManager:
    """Manages A/B testing of trading parameter sets."""

    def __init__(self):
        self._load_state()

    def _load_state(self):
        """Load current A/B test state from database."""
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            state_json = db.get_param("ab_test_state")
            if state_json and isinstance(state_json, str):
                self._state = json.loads(state_json)
            else:
                self._state = {"active": False}
        except (ImportError, json.JSONDecodeError, TypeError):
            self._state = {"active": False}

    def _save_state(self):
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            db.set_param("ab_test_state", json.dumps(self._state))
        except (ImportError, AttributeError):
            pass

    @property
    def is_active(self) -> bool:
        return bool(self._state.get("active", False))

    def propose_params(self, shadow_params: Dict[str, float], reason: str = ""):
        """
        Start a new A/B test with proposed shadow parameters.

        Args:
            shadow_params: Dict of param_name → proposed_value
            reason: Why these params are being tested
        """
        if self.is_active:
            logger.warning("A/B test already active — discard current first")
            return False

        # Store current params as control
        try:
            from src.core.database import NewsDB
            db = NewsDB()
            control_params = {}
            for name in shadow_params:
                control_params[name] = float(db.get_param(name, 1.0))
        except (ImportError, AttributeError):
            return False

        self._state = {
            "active": True,
            "started": datetime.datetime.now().isoformat(),
            "reason": reason,
            "control_params": control_params,
            "shadow_params": shadow_params,
            "control_wins": 0,
            "control_losses": 0,
            "shadow_wins": 0,
            "shadow_losses": 0,
            "trades_evaluated": 0,
        }
        self._save_state()
        logger.info(f"A/B test started: {shadow_params} (reason: {reason})")
        return True

    def record_outcome(self, outcome: str, shadow_would_trade: bool = True):
        """
        Record a trade outcome for both control and shadow.

        Args:
            outcome: "WIN" or "LOSS"
            shadow_would_trade: Whether shadow params would have taken this trade
        """
        if not self.is_active:
            return

        is_win = outcome in ("WIN", "PROFIT")

        # Control always trades (it's the current live system)
        if is_win:
            self._state["control_wins"] += 1
        else:
            self._state["control_losses"] += 1

        # Shadow only counts if it would have traded
        if shadow_would_trade:
            if is_win:
                self._state["shadow_wins"] += 1
            else:
                self._state["shadow_losses"] += 1

        self._state["trades_evaluated"] += 1
        self._save_state()

    def evaluate(self) -> Dict:
        """
        Evaluate A/B test results. Returns recommendation.

        Returns:
            {"action": "promote" | "reject" | "continue", "details": {...}}
        """
        if not self.is_active:
            return {"action": "no_test", "details": "No A/B test active"}

        n = self._state["trades_evaluated"]
        if n < MIN_AB_TRADES:
            return {
                "action": "continue",
                "details": f"Need {MIN_AB_TRADES - n} more trades (have {n})",
                "progress": n / MIN_AB_TRADES,
            }

        c_wins = self._state["control_wins"]
        c_total = c_wins + self._state["control_losses"]
        s_wins = self._state["shadow_wins"]
        s_total = s_wins + self._state["shadow_losses"]

        c_wr = c_wins / max(c_total, 1)
        s_wr = s_wins / max(s_total, 1)

        improvement = (s_wr - c_wr) / max(c_wr, 0.01) * 100

        # Z-test for two proportions
        z_score = self._two_proportion_z(c_wins, c_total, s_wins, s_total)

        result = {
            "control_wr": round(c_wr, 3),
            "shadow_wr": round(s_wr, 3),
            "improvement_pct": round(improvement, 1),
            "z_score": round(z_score, 2),
            "n_trades": n,
            "control_params": self._state["control_params"],
            "shadow_params": self._state["shadow_params"],
        }

        if improvement >= MIN_IMPROVEMENT_PCT and z_score >= MIN_Z_SCORE:
            result["action"] = "promote"
            result["details"] = (
                f"Shadow wins: {s_wr:.0%} vs control {c_wr:.0%} "
                f"(+{improvement:.1f}%, z={z_score:.2f})"
            )
        elif improvement < -MIN_IMPROVEMENT_PCT and z_score >= MIN_Z_SCORE:
            result["action"] = "reject"
            result["details"] = (
                f"Shadow underperforms: {s_wr:.0%} vs control {c_wr:.0%} "
                f"({improvement:.1f}%, z={z_score:.2f})"
            )
        else:
            result["action"] = "continue"
            result["details"] = f"Inconclusive (improvement={improvement:.1f}%, z={z_score:.2f})"

        return result

    def promote_shadow(self) -> bool:
        """Apply shadow parameters to live trading."""
        if not self.is_active:
            return False

        try:
            from src.core.database import NewsDB
            db = NewsDB()
            for name, val in self._state["shadow_params"].items():
                db.set_param(name, val)
            logger.info(f"A/B test PROMOTED: {self._state['shadow_params']}")
            self.discard()
            return True
        except (ImportError, AttributeError):
            return False

    def discard(self):
        """Discard current A/B test."""
        if self.is_active:
            logger.info("A/B test discarded")
        self._state = {"active": False}
        self._save_state()

    def get_status(self) -> Dict:
        """Return current A/B test status."""
        if not self.is_active:
            return {"active": False}
        result = self.evaluate()
        result["started"] = self._state.get("started")
        result["reason"] = self._state.get("reason")
        return result

    @staticmethod
    def _two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> float:
        """Z-test for difference between two proportions."""
        if n1 == 0 or n2 == 0:
            return 0.0
        p1 = x1 / n1
        p2 = x2 / n2
        p_pool = (x1 + x2) / (n1 + n2)
        if p_pool <= 0 or p_pool >= 1:
            return 0.0
        se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
        return abs(p2 - p1) / se if se > 0 else 0.0


def get_ab_manager() -> ABTestManager:
    return ABTestManager()
