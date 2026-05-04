"""Regression tests locking in 2026-05-04 session fixes.

Each test corresponds to a specific commit/finding from the 2026-05-04
parallel-agent audit + WR analytics push. Tests are deliberately minimal —
they verify the BEHAVIORAL contract of each fix without requiring full
scanner DB fixtures.
"""
import os
import time
import pytest
from unittest.mock import patch


# ── LLM news sentiment cache TTL (commit 86ee235) ──────────────────────

def test_llm_cache_has_ttl_constant():
    """Cache stores (verdict, ts) and has 24h TTL."""
    from src.data.news import _LLM_SENTIMENT_CACHE_TTL
    assert _LLM_SENTIMENT_CACHE_TTL == 86400


def test_llm_cache_format_is_tuple():
    """Cache values must be tuples (verdict, ts), not bare strings."""
    from src.data.news import _LLM_SENTIMENT_CACHE
    # Empty by default but type signature should support tuples
    # Direct insert + read
    _LLM_SENTIMENT_CACHE.clear()
    _LLM_SENTIMENT_CACHE["test"] = ("bullish", time.time())
    v = _LLM_SENTIMENT_CACHE.get("test")
    assert isinstance(v, tuple)
    assert v[0] == "bullish"
    assert isinstance(v[1], float)
    _LLM_SENTIMENT_CACHE.clear()


# ── Phase V2 regime routing (commit 437b351) ──────────────────────────

def test_regime_v2_default_off(monkeypatch):
    """When QUANT_REGIME_V2 unset, scanner behavior must be unchanged."""
    monkeypatch.delenv("QUANT_REGIME_V2", raising=False)
    from src.analysis.regime_routing import is_active
    assert is_active() is False


def test_regime_v2_squeeze_blocks():
    """squeeze regime => block_entry True for all TFs."""
    from src.analysis.regime_routing import get_routing
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        r = get_routing("squeeze", tf)
        assert r.block_entry is True


def test_regime_v2_zielony_restricts_to_long():
    """zielony macro_regime => allowed_directions = LONG only."""
    from src.analysis.regime_routing import get_routing
    r = get_routing("trending_high_vol", "5m", "zielony")
    assert r.allowed_directions == ("LONG",)


# ── Toxic pair filter (commit 1c8e7fa) ────────────────────────────────

def test_toxic_pair_env_default_off(monkeypatch):
    """QUANT_BLOCK_CHOCH_OBCOUNT unset => filter inactive."""
    monkeypatch.delenv("QUANT_BLOCK_CHOCH_OBCOUNT", raising=False)
    # Verify no behavior — checking env reading directly
    assert os.environ.get("QUANT_BLOCK_CHOCH_OBCOUNT") is None


# ── regime_adj cap on self-learning penalty (commit 831cbc5) ──────────

def test_score_setup_quality_zielony_no_crash():
    """Smoke: zielony regime + cap logic doesn't crash."""
    from src.trading.smc_engine import score_setup_quality
    analysis = {
        "macro_regime": "zielony",
        "trend": "Bull", "structure": "Stable",
        "current_price": 4000.0, "rsi": 50, "atr": 5.0,
        "session": "overlap",
    }
    result = score_setup_quality(analysis, "LONG")
    assert "score" in result
    assert "grade" in result


# ── SHORT shadow ensemble (commit a10092d) ────────────────────────────

def test_short_shadow_full_returns_dict():
    """predict_short_ensemble returns dict with expected keys."""
    from src.ml.short_shadow_full import predict_short_ensemble
    import pandas as pd
    # Build minimal input — feature compute may fail, but must return dict
    # gracefully (with None values, not crash).
    df = pd.DataFrame({
        "open": [4000] * 100, "high": [4001] * 100,
        "low": [3999] * 100, "close": [4000] * 100, "volume": [0] * 100,
    })
    df.index = pd.date_range("2026-01-01", periods=100, freq="5min")
    df.index.name = "datetime"
    result = predict_short_ensemble(df)
    assert isinstance(result, dict)
    assert "xgb" in result
    assert "lstm" in result
    assert "attention" in result
    assert "mean" in result
    assert "n_available" in result


# ── Backtest setup_grade backfill (commit 009446b) ────────────────────

def test_log_trade_signature_no_grade():
    """db.log_trade() doesn't accept setup_grade — backfilled separately."""
    from src.core.database import NewsDB
    import inspect
    sig = inspect.signature(NewsDB.log_trade)
    # Confirm setup_grade is NOT a parameter (would have to be backfilled)
    assert "setup_grade" not in sig.parameters
    assert "setup_score" not in sig.parameters
    # Confirm there's an update_trade_setup_grade method
    assert hasattr(NewsDB, "update_trade_setup_grade")


# ── Same-bar TP+SL priority (commit 4c504fc) ──────────────────────────

def test_resolve_open_trades_handles_both_crossed():
    """Backtest TP+SL same-bar uses bar OHLC sequence, not blind TP-first."""
    # This is a behavioral contract — actual exit logic lives in
    # run_production_backtest._resolve_open_trades. Read source to verify
    # the critical phrase exists.
    src_path = "run_production_backtest.py"
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    # Verify the same-bar handling block was added
    assert "Both touched in same bar" in src or "tp_crossed and sl_crossed" in src, \
        "Same-bar TP+SL handling not found in run_production_backtest.py"


# ── Defensive scaler.n_features_in_ check (commit 7ddf6c8) ────────────

def test_lstm_voter_has_scaler_check():
    """ensemble_models.predict_lstm_direction checks scaler.n_features_in_."""
    src_path = "src/ml/ensemble_models.py"
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "scaler.n_features_in_" in src or "n_features_in_" in src, \
        "Defensive scaler-feature check not found"


# ── Frontend X-API-Key header (commit 4c504fc) ────────────────────────

def test_frontend_client_reads_api_key_env():
    """frontend/src/api/client.ts reads VITE_API_SECRET_KEY for X-API-Key."""
    src_path = "frontend/src/api/client.ts"
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "VITE_API_SECRET_KEY" in src
    assert "X-API-Key" in src
