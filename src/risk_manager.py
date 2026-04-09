"""
src/risk_manager.py — Centralized Risk Management Module

Professional-grade risk controls for the Quant Sentinel trading system.

Features:
  - Fractional Kelly Criterion position sizing
  - Drawdown circuit breakers (daily loss, consecutive losses)
  - Portfolio heat tracking (max aggregate risk)
  - Session-aware dynamic slippage model
  - Kill switch (halt/resume trading)

All state is persisted to database (dynamic_params) so it survives restarts.
"""

import threading
import datetime
from typing import Optional
from src.logger import logger

# ═══════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

# Kelly fraction — use 25% of theoretical Kelly for safety (half-Kelly = 50%, quarter = 25%)
KELLY_FRACTION = 0.25

# Minimum trades required before Kelly sizing kicks in (else use default risk_percent)
KELLY_MIN_TRADES = 30

# Circuit breaker thresholds
DAILY_LOSS_SOFT_LIMIT_PCT = 2.0    # 2% daily loss → reduce position to 50%
DAILY_LOSS_HARD_LIMIT_PCT = 5.0    # 5% daily loss → halt trading
CONSEC_LOSS_COOLDOWN = 3           # 3 consecutive losses → 30min cooldown
CONSEC_LOSS_COOLDOWN_MINS = 30     # Cooldown duration in minutes

# Portfolio heat — max total risk across all open positions
MAX_PORTFOLIO_HEAT_PCT = 6.0       # 6% max aggregate risk

# Session-dependent spread model (XAU/USD typical spreads in USD)
SESSION_SPREADS = {
    "asian":     0.35,   # Low volatility, tight spreads
    "london":    0.60,   # Medium volatility
    "overlap":   0.80,   # London+NY overlap, wider spreads
    "new_york":  1.00,   # High volatility, widest spreads
    "off_hours": 1.50,   # After-hours, very wide spreads
    "weekend":   0.00,   # Market closed
}

# ═══════════════════════════════════════════════════════════════════════════
#  RISK MANAGER (Singleton)
# ═══════════════════════════════════════════════════════════════════════════

_lock = threading.Lock()


class RiskManager:
    """Centralized risk engine. Thread-safe, database-backed."""

    _instance: Optional["RiskManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._halted = False
        self._halt_reason = ""
        self._last_cooldown_until: Optional[datetime.datetime] = None
        self._load_state()

    def _load_state(self):
        """Load persisted risk state from database."""
        try:
            from src.database import NewsDB
            db = NewsDB()
            halted = db.get_param("risk_halted", 0)
            self._halted = bool(int(halted)) if halted else False
            self._halt_reason = str(db.get_param("risk_halt_reason", "") or "")
        except (ImportError, AttributeError, TypeError):
            pass

    # ─── KELLY CRITERION ─────────────────────────────────────────────

    def compute_kelly_risk_percent(self, default_risk: float = 1.0) -> float:
        """
        Compute optimal risk percent using Fractional Kelly Criterion.

        Formula: f* = KELLY_FRACTION * (p * b - q) / b
        where:
          p = win probability
          q = 1 - p (loss probability)
          b = avg_win / avg_loss (payoff ratio)

        Returns default_risk if insufficient trade history.
        """
        try:
            from src.database import NewsDB
            db = NewsDB()
            rows = db._query(
                "SELECT status, profit FROM trades "
                "WHERE status IN ('WIN', 'LOSS') AND profit IS NOT NULL "
                "ORDER BY id DESC LIMIT 100"
            )
            if not rows or len(rows) < KELLY_MIN_TRADES:
                return default_risk

            wins = [abs(float(r[1])) for r in rows if r[0] == 'WIN' and r[1]]
            losses = [abs(float(r[1])) for r in rows if r[0] == 'LOSS' and r[1]]

            if not wins or not losses:
                return default_risk

            total = len(wins) + len(losses)
            p = len(wins) / total          # win probability
            q = 1.0 - p                     # loss probability
            avg_win = sum(wins) / len(wins)
            avg_loss = sum(losses) / len(losses)

            if avg_loss <= 0:
                return default_risk

            b = avg_win / avg_loss          # payoff ratio

            # Kelly formula
            kelly_f = (p * b - q) / b

            if kelly_f <= 0:
                # Negative Kelly = system is unprofitable, use minimum risk
                logger.warning(f"Kelly f* negative ({kelly_f:.3f}): WR={p:.1%}, payoff={b:.2f} — using minimum 0.25%")
                return 0.25

            # Apply fraction for safety
            optimal_risk = KELLY_FRACTION * kelly_f * 100  # Convert to percent

            # Clamp to sane range [0.25%, 3.0%]
            optimal_risk = max(0.25, min(optimal_risk, 3.0))

            logger.info(
                f"Kelly sizing: f*={kelly_f:.3f}, fraction={KELLY_FRACTION}, "
                f"risk={optimal_risk:.2f}% (WR={p:.1%}, payoff={b:.2f}, n={total})"
            )
            return round(optimal_risk, 2)

        except (ImportError, AttributeError, TypeError, ValueError, ZeroDivisionError) as e:
            logger.debug(f"Kelly calculation failed: {e}")
            return default_risk

    # ─── CIRCUIT BREAKERS ─────────────────────────────────────────────

    def check_circuit_breakers(self, balance: float) -> tuple[bool, str]:
        """
        Check all circuit breakers. Returns (can_trade, reason).

        Checks:
          1. Kill switch (manual halt)
          2. Cooldown period (after consecutive losses)
          3. Daily loss limit (soft = reduce, hard = halt)
        """
        # 1. Manual halt
        if self._halted:
            return False, f"Trading halted: {self._halt_reason}"

        # 2. Cooldown check
        if self._last_cooldown_until and datetime.datetime.now() < self._last_cooldown_until:
            remaining = (self._last_cooldown_until - datetime.datetime.now()).seconds // 60
            return False, f"Cooldown active ({remaining}min remaining after {CONSEC_LOSS_COOLDOWN} consecutive losses)"

        # 3. Daily loss check
        try:
            daily_loss_pct = self._get_daily_loss_pct(balance)

            if daily_loss_pct >= DAILY_LOSS_HARD_LIMIT_PCT:
                self.halt(f"Daily loss limit hit: {daily_loss_pct:.1f}% (limit: {DAILY_LOSS_HARD_LIMIT_PCT}%)")
                return False, f"Daily loss {daily_loss_pct:.1f}% exceeds hard limit {DAILY_LOSS_HARD_LIMIT_PCT}%"

        except (ImportError, AttributeError, TypeError) as e:
            logger.debug(f"Circuit breaker check failed: {e}")

        # 4. Consecutive loss cooldown trigger
        try:
            consec = self._get_consecutive_losses()
            if consec >= CONSEC_LOSS_COOLDOWN:
                self._last_cooldown_until = datetime.datetime.now() + datetime.timedelta(
                    minutes=CONSEC_LOSS_COOLDOWN_MINS
                )
                return False, f"{consec} consecutive losses — {CONSEC_LOSS_COOLDOWN_MINS}min cooldown activated"
        except (ImportError, AttributeError, TypeError):
            pass

        return True, "OK"

    def get_daily_risk_multiplier(self, balance: float) -> float:
        """
        Returns a multiplier (0.0 - 1.0) based on daily drawdown.
        Soft limit: reduce to 50%. Hard limit: returns 0.0 (no trading).
        """
        try:
            daily_loss_pct = self._get_daily_loss_pct(balance)

            if daily_loss_pct >= DAILY_LOSS_HARD_LIMIT_PCT:
                return 0.0
            elif daily_loss_pct >= DAILY_LOSS_SOFT_LIMIT_PCT:
                # Linear reduction: 2% loss = 0.5x, 3.5% = 0.25x
                reduction = 1.0 - ((daily_loss_pct - DAILY_LOSS_SOFT_LIMIT_PCT) /
                                   (DAILY_LOSS_HARD_LIMIT_PCT - DAILY_LOSS_SOFT_LIMIT_PCT))
                return max(0.1, min(0.5, reduction))
        except (ImportError, AttributeError, TypeError, ZeroDivisionError):
            pass
        return 1.0

    def _get_daily_loss_pct(self, balance: float) -> float:
        """Get today's total realized loss as percentage of balance."""
        from src.database import NewsDB
        db = NewsDB()
        today = datetime.date.today().isoformat()
        rows = db._query(
            "SELECT COALESCE(SUM(profit), 0) FROM trades "
            "WHERE status IN ('LOSS', 'WIN') AND DATE(timestamp) = ?",
            (today,)
        )
        daily_pnl = float(rows[0][0]) if rows and rows[0] and rows[0][0] else 0.0
        if balance <= 0:
            return 0.0
        # Only count losses (negative PnL means we're down)
        if daily_pnl >= 0:
            return 0.0
        return abs(daily_pnl) / balance * 100

    def _get_consecutive_losses(self) -> int:
        """Count consecutive losses from most recent trades."""
        from src.database import NewsDB
        db = NewsDB()
        rows = db._query(
            "SELECT status FROM trades WHERE status IN ('WIN', 'LOSS') ORDER BY id DESC LIMIT 10"
        )
        count = 0
        for r in (rows or []):
            if r[0] == 'LOSS':
                count += 1
            else:
                break
        return count

    # ─── PORTFOLIO HEAT ───────────────────────────────────────────────

    def check_portfolio_heat(self, balance: float, new_risk_usd: float) -> tuple[bool, float]:
        """
        Check if adding a new trade would exceed max portfolio heat.

        Returns (can_open, current_heat_pct).
        """
        try:
            from src.database import NewsDB
            db = NewsDB()
            open_trades = db.get_open_trades()

            current_risk = 0.0
            for trade in (open_trades or []):
                _, direction, entry, sl, _ = trade
                try:
                    entry_f = float(entry or 0)
                    sl_f = float(sl or 0)
                    if entry_f > 0 and sl_f > 0:
                        current_risk += abs(entry_f - sl_f) * 100  # * 100 oz per lot (simplified)
                except (ValueError, TypeError):
                    continue

            total_risk = current_risk + new_risk_usd
            heat_pct = (total_risk / balance * 100) if balance > 0 else 0.0

            if heat_pct > MAX_PORTFOLIO_HEAT_PCT:
                logger.warning(
                    f"Portfolio heat {heat_pct:.1f}% would exceed limit {MAX_PORTFOLIO_HEAT_PCT}% — trade blocked"
                )
                return False, heat_pct

            return True, heat_pct

        except (ImportError, AttributeError, TypeError) as e:
            logger.debug(f"Portfolio heat check failed: {e}")
            return True, 0.0

    # ─── SLIPPAGE MODEL ───────────────────────────────────────────────

    def get_spread_buffer(self, session: Optional[str] = None) -> float:
        """
        Returns expected spread in USD for current session.
        Falls back to detecting session from current hour if not provided.
        """
        if session is None:
            session = self._detect_session()

        spread = SESSION_SPREADS.get(session, SESSION_SPREADS["off_hours"])
        return spread

    def adjust_for_slippage(self, entry: float, sl: float, tp: float,
                            direction: str, session: Optional[str] = None) -> tuple[float, float, float]:
        """
        Adjust entry/SL/TP for expected slippage and spread.
        Returns (adjusted_entry, adjusted_sl, adjusted_tp).
        """
        spread = self.get_spread_buffer(session)
        half_spread = spread / 2

        if "LONG" in direction.upper():
            # Buy: enter slightly higher, SL slightly lower, TP slightly lower
            adj_entry = round(entry + half_spread, 2)
            adj_sl = round(sl - half_spread, 2)
            adj_tp = round(tp - half_spread, 2)
        else:
            # Sell: enter slightly lower, SL slightly higher, TP slightly higher
            adj_entry = round(entry - half_spread, 2)
            adj_sl = round(sl + half_spread, 2)
            adj_tp = round(tp + half_spread, 2)

        return adj_entry, adj_sl, adj_tp

    @staticmethod
    def _detect_session() -> str:
        """Detect current trading session from UTC hour."""
        utc_hour = datetime.datetime.now(datetime.timezone.utc).hour
        if 0 <= utc_hour < 7:
            return "asian"
        elif 7 <= utc_hour < 12:
            return "london"
        elif 12 <= utc_hour < 16:
            return "overlap"
        elif 16 <= utc_hour < 21:
            return "new_york"
        else:
            return "off_hours"

    # ─── KILL SWITCH ──────────────────────────────────────────────────

    def halt(self, reason: str = "Manual halt"):
        """Halt all trading immediately."""
        with _lock:
            self._halted = True
            self._halt_reason = reason
            logger.warning(f"TRADING HALTED: {reason}")
            try:
                from src.database import NewsDB
                db = NewsDB()
                db.set_param("risk_halted", 1)
                db.set_param("risk_halt_reason", reason)
            except (ImportError, AttributeError):
                pass

    def resume(self):
        """Resume trading after halt."""
        with _lock:
            self._halted = False
            self._halt_reason = ""
            self._last_cooldown_until = None
            logger.info("TRADING RESUMED")
            try:
                from src.database import NewsDB
                db = NewsDB()
                db.set_param("risk_halted", 0)
                db.set_param("risk_halt_reason", "")
            except (ImportError, AttributeError):
                pass

    @property
    def is_halted(self) -> bool:
        return bool(self._halted)

    def get_status(self) -> dict:
        """Return current risk manager status for API/monitoring."""
        try:
            from src.database import NewsDB
            db = NewsDB()
            balance_raw = db.get_param("portfolio_balance", 10000)
            balance = float(balance_raw) if balance_raw else 10000.0
        except (ImportError, AttributeError, TypeError, ValueError):
            balance = 10000.0

        try:
            daily_loss = self._get_daily_loss_pct(balance)
        except (ImportError, AttributeError, TypeError):
            daily_loss = 0.0

        try:
            consec_losses = self._get_consecutive_losses()
        except (ImportError, AttributeError, TypeError):
            consec_losses = 0

        cooldown_active = bool(
            self._last_cooldown_until and datetime.datetime.now() < self._last_cooldown_until
        )

        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "daily_loss_pct": round(daily_loss, 2),
            "daily_loss_soft_limit": DAILY_LOSS_SOFT_LIMIT_PCT,
            "daily_loss_hard_limit": DAILY_LOSS_HARD_LIMIT_PCT,
            "consecutive_losses": consec_losses,
            "cooldown_active": cooldown_active,
            "cooldown_until": self._last_cooldown_until.isoformat() if self._last_cooldown_until else None,
            "max_portfolio_heat_pct": MAX_PORTFOLIO_HEAT_PCT,
            "kelly_risk_pct": self.compute_kelly_risk_percent(),
            "session": self._detect_session(),
            "spread_buffer": self.get_spread_buffer(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  MODULE-LEVEL ACCESSOR
# ═══════════════════════════════════════════════════════════════════════════

def get_risk_manager() -> RiskManager:
    """Get the singleton RiskManager instance."""
    return RiskManager()
