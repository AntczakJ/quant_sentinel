"""
src/core/dynamic_params_schema.py — schema + drift tracker for `dynamic_params`.

Why this exists
---------------
`dynamic_params` is a key/value SQLite store with no schema. Bug #95569f7
(2026-04-16) was a writer/reader name drift: `self_learning.py` wrote
`target_rr`, but `finance.py:119` was reading `tp_to_sl_ratio`. The fix
mirrored writes manually — fragile and easy to break next time.

This module enforces structure WITHOUT migrating all 50+ existing
call-sites. It does three things:

1. **Validates** type/range of well-known keys when they are set
   (warns; never raises in production — keep the API/scanner alive).
2. **Tracks** in-process (last_write_ts, last_read_ts, n_writes, n_reads)
   for every key touched, so a periodic watchdog can warn about
   write-without-read or read-without-write drift.
3. **Auto-mirrors** known coupled pairs (e.g. `target_rr → tp_to_sl_ratio`)
   so the next learning-target rename can't silently break production
   sizing again.

Adoption is opt-in but transparent: `NewsDB.set_param` / `get_param` in
`src/core/database.py` route through `validate_param_write` / `track_read`
helpers exposed here.

Adding a new key
----------------
Either:
  a) add a `KeySpec` to `_REGISTRY` (literal name) — gets validated, and
     drift watchdog will see it.
  b) for prefix-based dynamic keys (e.g. `ensemble_weight_*`), add a
     `PrefixSpec` to `_PREFIXES`.

Anything not in either falls back to "unknown" — tracked but not
validated, no warning.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Specs ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KeySpec:
    """Single literal key (e.g. `tp_to_sl_ratio`)."""
    name: str
    kind: str  # 'float' | 'int' | 'str' | 'json' | 'bool' | 'ts'
    domain: str  # 'risk_sizing' | 'ensemble' | 'portfolio' | …
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    """Soft warning when value is outside [min, max]; never raises."""


@dataclass(frozen=True)
class PrefixSpec:
    """Dynamic key family (e.g. `ensemble_weight_*`)."""
    prefix: str
    kind: str
    domain: str
    description: str = ""
    min_value: Optional[float] = None
    max_value: Optional[float] = None


# ── Registry ──────────────────────────────────────────────────────────
# Sourced from inventory in memory/dynamic_params_inventory_2026-04-26.md.
# Add a key here when you introduce a new write-path.

_REGISTRY: tuple[KeySpec, ...] = (
    # ── Risk / sizing ─────────────────────────────────────────────
    KeySpec("risk_percent",        "float", "risk_sizing", "Per-trade risk as % of account.",      0.05, 5.0),
    KeySpec("sl_atr_multiplier",   "float", "risk_sizing", "SL distance = ATR × this.",              0.5, 6.0),
    KeySpec("sl_min_distance",     "float", "risk_sizing", "Minimum SL distance (price units).",    0.5, 20.0),
    KeySpec("min_tp_distance_mult","float", "risk_sizing", "Min TP distance multiplier.",           0.5, 5.0),
    # CRITICAL coupled pair — see `_MIRRORS` below.
    KeySpec("tp_to_sl_ratio",      "float", "risk_sizing", "Production reads this for TP geometry.", 1.0, 6.0),
    KeySpec("target_rr",           "float", "risk_sizing", "Learning-target alias of tp_to_sl_ratio.", 1.0, 6.0),
    # ── Volatility / regime ──────────────────────────────────────
    KeySpec("vol_target_atr",      "float", "volatility",   "EMA-smoothed ATR baseline.",           0.5, 50.0),
    KeySpec("vol_min_mult",        "float", "volatility",   "Floor multiplier for vol scaling.",    0.1, 1.0),
    KeySpec("vol_max_mult",        "float", "volatility",   "Ceiling multiplier for vol scaling.",  1.0, 5.0),
    # ── Kelly / circuit-breakers ─────────────────────────────────
    KeySpec("kelly_reset_ts",      "ts",    "kelly",        "ISO timestamp of last Kelly reset."),
    KeySpec("risk_halted",         "int",   "circuit",      "0/1 emergency halt flag.",             0,    1),
    KeySpec("risk_halt_reason",    "str",   "circuit",      "Free-text halt reason."),
    # ── Portfolio state ──────────────────────────────────────────
    KeySpec("portfolio_balance",        "float","portfolio","Cash balance.",                        0.0, 1e9),
    KeySpec("portfolio_initial_balance","float","portfolio","Reference balance for net % calc.",    0.0, 1e9),
    KeySpec("portfolio_equity",         "float","portfolio","Equity = balance + unrealized PnL."),
    KeySpec("portfolio_pnl",            "float","portfolio","Cumulative realized PnL."),
    KeySpec("portfolio_currency_text",  "str",  "portfolio","Currency symbol (e.g. USD/PLN)."),
    KeySpec("portfolio_history",        "json", "portfolio","Equity timeline (timestamps/equity_values/pnl_values)."),
    KeySpec("current_price",            "float","portfolio","Last known XAU/USD spot.",             100.0, 20000.0),
    # ── ML metrics (training-time) ───────────────────────────────
    KeySpec("xgb_last_accuracy",         "float","ml_metrics","Last XGB OOS accuracy.",     0.0, 1.0),
    KeySpec("xgb_feature_count",         "int",  "ml_metrics","XGB feature_count post-train."),
    KeySpec("lstm_last_accuracy",        "float","ml_metrics","LSTM validation accuracy.",  0.0, 1.0),
    KeySpec("lstm_walkforward_accuracy", "float","ml_metrics","LSTM walk-forward accuracy.", 0.0, 1.0),
    # ── A/B testing & optimization ───────────────────────────────
    KeySpec("ab_test_state",         "json", "ab_testing", "A/B test state JSON."),
    KeySpec("last_backtest_results", "json", "ab_testing", "Last backtest summary JSON."),
    # ── RL deployment ────────────────────────────────────────────
    KeySpec("rl_last_promote_ts",     "ts", "deployment", "ISO ts of last RL model promotion."),
    KeySpec("rl_last_promote_backup", "str","deployment", "Path to backup of pre-promotion model."),
    # ── Misc tracking ────────────────────────────────────────────
    KeySpec("last_trade_regime",       "int","tracking", "Hash of last trade's regime."),
    KeySpec("last_trade_session_name", "str","tracking", "Last trade's session name."),
    KeySpec("monitor_last_check",      "ts","tracking",  "Last model monitor check timestamp."),
)

_PREFIXES: tuple[PrefixSpec, ...] = (
    PrefixSpec("ensemble_weight_",  "float", "ensemble", "Voter weight ∈ [0, 1].",       0.0, 1.0),
    PrefixSpec("model_",            "int",   "ensemble", "Voter accuracy counters (correct/incorrect)."),
    PrefixSpec("pattern_weight_",   "float", "patterns", "Auto-tuned candlestick pattern weight.", 0.0, 5.0),
    PrefixSpec("factor_alpha_",     "float", "bayesian", "Bayesian Beta-α posterior."),
    PrefixSpec("factor_beta_",      "float", "bayesian", "Bayesian Beta-β posterior."),
    PrefixSpec("weight_",           "float", "bayesian", "Derived factor weight."),
    PrefixSpec("daily_report_",     "json",  "compliance","Daily compliance report JSON."),
)

# Coupled keys — writes to `source` mirror to `target` automatically.
# Reverse direction is NOT mirrored (would be a write-loop).
_MIRRORS: dict[str, str] = {
    "target_rr": "tp_to_sl_ratio",
}


# ── Lookup helpers ────────────────────────────────────────────────────


def _lookup(name: str) -> tuple[Optional[KeySpec], Optional[PrefixSpec]]:
    for spec in _REGISTRY:
        if spec.name == name:
            return spec, None
    for pre in _PREFIXES:
        if name.startswith(pre.prefix):
            return None, pre
    return None, None


# ── Drift tracker ─────────────────────────────────────────────────────


@dataclass
class _UsageStat:
    last_write_ts: float = 0.0
    last_read_ts: float = 0.0
    n_writes: int = 0
    n_reads: int = 0
    last_value_repr: str = ""


_usage: dict[str, _UsageStat] = {}
_usage_lock = Lock()


def _bump(name: str, kind: str, value: Any = None) -> None:
    now = time.time()
    with _usage_lock:
        s = _usage.setdefault(name, _UsageStat())
        if kind == "write":
            s.n_writes += 1
            s.last_write_ts = now
            s.last_value_repr = repr(value)[:80]
        else:
            s.n_reads += 1
            s.last_read_ts = now


def get_usage_snapshot() -> dict[str, dict[str, Any]]:
    """Read-only view of the current usage map. Safe to JSON-encode."""
    with _usage_lock:
        return {
            name: {
                "n_writes": s.n_writes,
                "n_reads": s.n_reads,
                "last_write_ts": s.last_write_ts,
                "last_read_ts": s.last_read_ts,
                "last_value_repr": s.last_value_repr,
            }
            for name, s in _usage.items()
        }


# ── Validation hooks ─────────────────────────────────────────────────


def _coerce_check(value: Any, spec_kind: str) -> Optional[str]:
    """Returns a warning string when value mismatches `spec_kind`, else None."""
    if value is None:
        return None
    try:
        if spec_kind == "float":
            float(value)
        elif spec_kind == "int":
            int(value)
        elif spec_kind == "bool":
            if not isinstance(value, (bool, int)) and str(value).lower() not in ("0", "1", "true", "false"):
                return f"expected bool-like, got {type(value).__name__}"
        elif spec_kind in ("str", "ts"):
            if not isinstance(value, str):
                return f"expected str, got {type(value).__name__}"
        elif spec_kind == "json":
            if not isinstance(value, (str, dict, list)):
                return f"expected JSON-serializable str/dict/list, got {type(value).__name__}"
    except (TypeError, ValueError):
        return f"could not coerce to {spec_kind}: {value!r}"
    return None


def validate_param_write(name: str, value: Any) -> Optional[str]:
    """
    Returns the *mirror target name* if a mirror should fire, else None.
    Logs a warning when validation finds something off; never raises.
    """
    spec, prefix = _lookup(name)
    chosen = spec or prefix
    if chosen is None:
        # Unknown key — track only.
        _bump(name, "write", value)
        return _MIRRORS.get(name)

    kind = chosen.kind
    err = _coerce_check(value, kind)
    if err:
        logger.warning(f"[dynamic_params] {name}={value!r} — {err}")
    elif kind in ("float", "int"):
        try:
            f = float(value)
            lo = getattr(chosen, "min_value", None)
            hi = getattr(chosen, "max_value", None)
            if lo is not None and f < lo:
                logger.warning(
                    f"[dynamic_params] {name}={f} below soft-min {lo} (domain={chosen.domain})"
                )
            if hi is not None and f > hi:
                logger.warning(
                    f"[dynamic_params] {name}={f} above soft-max {hi} (domain={chosen.domain})"
                )
        except (TypeError, ValueError):
            pass
    _bump(name, "write", value)
    return _MIRRORS.get(name)


def track_read(name: str) -> None:
    """Hook from get_param — only updates usage stats."""
    _bump(name, "read")


# ── Drift watchdog ────────────────────────────────────────────────────


def find_drifts(now: Optional[float] = None, write_only_grace_s: float = 600.0) -> list[dict[str, Any]]:
    """
    Returns a list of suspicious keys for periodic logging:
      - `write_only`  — written but never read since process start.
      - `read_only`   — read but never written (pure consumer; usually OK).
      - `dead_write`  — last write was recent but no reader has touched
                        the key for `write_only_grace_s` seconds.
    """
    now = now or time.time()
    with _usage_lock:
        snapshot = list(_usage.items())
    out: list[dict[str, Any]] = []
    for name, s in snapshot:
        kind = None
        if s.n_writes > 0 and s.n_reads == 0:
            kind = "write_only"
        elif s.n_reads > 0 and s.n_writes == 0:
            kind = "read_only"
        elif s.n_writes > 0 and s.n_reads > 0 and s.last_write_ts - s.last_read_ts > write_only_grace_s:
            kind = "dead_write"
        if kind:
            spec, prefix = _lookup(name)
            domain = (spec or prefix).domain if (spec or prefix) else "unknown"
            out.append({
                "name": name,
                "kind": kind,
                "domain": domain,
                "n_writes": s.n_writes,
                "n_reads": s.n_reads,
                "last_value_repr": s.last_value_repr,
            })
    return out


# ── Helper for callers wanting the registry ─────────────────────────


def known_keys() -> list[str]:
    return [s.name for s in _REGISTRY]


def known_prefixes() -> list[str]:
    return [p.prefix for p in _PREFIXES]


def mirror_targets() -> dict[str, str]:
    return dict(_MIRRORS)


# Re-exported for callers in api/main.py periodic logger
SetCallback = Callable[[str, Any], None]
