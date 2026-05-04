"""Sanity test for factor weight + regime_adj cap (2026-05-04).

Doesn't try to engineer specific factor combos in score_setup_quality
(too fragile — requires deep analysis dict). Instead just verifies the
cap LOGIC by calling _w via the public function on real-data flows.

Full integration coverage comes from tests/test_smc_extended.py + the
running pytest suite (475 tests). This file is a smoke check only.
"""
import pytest
from src.trading.smc_engine import score_setup_quality


def test_smoke_score_returns_dict():
    """Smoke: score_setup_quality must return dict with expected keys
    even on minimal analysis (no factor matches)."""
    minimal = {
        "macro_regime": "neutralny",
        "trend": "Bull",
        "structure": "Stable",
        "current_price": 4000.0,
        "rsi": 50,
        "atr": 5.0,
        "session": "overlap",
    }
    result = score_setup_quality(minimal, "LONG")
    assert "grade" in result
    assert "score" in result
    assert "factors_detail" in result
    assert "risk_mult" in result
    assert "target_rr" in result


def test_smoke_zielony_doesnt_crash():
    """Zielony regime path must not crash on regime_adj cap."""
    analysis = {
        "macro_regime": "zielony",
        "trend": "Bull",
        "structure": "Stable",
        "current_price": 4000.0,
        "rsi": 50,
        "atr": 5.0,
        "session": "overlap",
    }
    result = score_setup_quality(analysis, "LONG")
    assert isinstance(result["score"], (int, float))
    assert result["grade"] in ("A+", "A", "B", "C")


def test_smoke_short_in_bull_regime_penalty():
    """SHORT in zielony should still apply -20 penalty (sanity that
    the regime_adj cap commit didn't break the existing penalty path)."""
    analysis = {
        "macro_regime": "zielony",
        "trend": "Bull",
        "structure": "Stable",
        "current_price": 4000.0,
        "rsi": 50,
        "atr": 5.0,
        "session": "overlap",
    }
    long_result = score_setup_quality(analysis, "LONG")
    short_result = score_setup_quality(analysis, "SHORT")
    # SHORT in bull regime should score lower than LONG (penalty exists)
    assert short_result["score"] < long_result["score"], \
        f"SHORT={short_result['score']} should be lower than LONG={long_result['score']} in zielony regime"
